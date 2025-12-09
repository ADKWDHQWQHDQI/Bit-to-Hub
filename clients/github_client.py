"""
GitHub API client for migrating pull requests
"""
import logging
from typing import List, Optional, Tuple
from github import Github, GithubException
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from models import PullRequest, PRComment, PRReviewer
from utils import UserMapper


logger = logging.getLogger(__name__)


class GitHubClient:
    """Client for interacting with GitHub API to create pull requests"""
    
    def __init__(self, token: str, owner: str, repository: str, user_mapper: UserMapper):
        """
        Initialize GitHub client
        
        Args:
            token: GitHub Personal Access Token
            owner: Repository owner (org or user)
            repository: Repository name
            user_mapper: UserMapper instance for mapping users
        """
        self.github = Github(token)
        self.owner = owner
        self.repository = repository
        self.user_mapper = user_mapper
        self.repo = self.github.get_repo(f"{owner}/{repository}")
    
    @retry(
        retry=retry_if_exception_type((GithubException,)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        before_sleep=lambda retry_state: logger.warning(
            f"Retrying GitHub API call (attempt {retry_state.attempt_number}/5)..."
        )
    )
    def verify_branch_exists(self, branch_name: str) -> bool:
        """
        Verify if a branch exists in the GitHub repository
        
        Args:
            branch_name: Name of the branch to check
            
        Returns:
            True if branch exists, False otherwise
        """
        try:
            self.repo.get_branch(branch_name)
            return True
        except GithubException as e:
            if e.status == 404:
                return False
            raise
    
    @retry(
        retry=retry_if_exception_type((GithubException,)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        before_sleep=lambda retry_state: logger.warning(
            f"Retrying commit verification (attempt {retry_state.attempt_number}/3)..."
        )
    )
    def verify_commits_exist(self, commit_shas: List[str]) -> Tuple[bool, List[str]]:
        """
        Verify if commit SHAs exist in the GitHub repository
        
        Args:
            commit_shas: List of commit SHAs to verify
            
        Returns:
            Tuple of (all_exist: bool, missing_shas: List[str])
        """
        missing_shas = []
        
        for sha in commit_shas:
            try:
                self.repo.get_commit(sha)
            except GithubException as e:
                if e.status == 404:
                    missing_shas.append(sha)
                    logger.warning(f"Commit {sha} not found in GitHub repository")
                else:
                    # For other errors, re-raise
                    raise
        
        return len(missing_shas) == 0, missing_shas
    
    def migrate_pull_request(self, pr: PullRequest) -> tuple[bool, str]:
        """
        Migrate a single pull request to GitHub
        
        Args:
            pr: PullRequest object to migrate
            
        Returns:
            Tuple of (success: bool, error_message: str)
        """
        head = pr.source_branch  # Initialize head at the start
        
        try:
            # Skip forked PRs
            if pr.is_fork:
                error_msg = (
                    f"Fork PR from {pr.fork_repo_owner}/{pr.fork_repo_name} "
                    f"(branch: {pr.source_branch}). Fork PRs are not migrated."
                )
                logger.warning(f"Skipping PR #{pr.id}: {error_msg}")
                return False, error_msg
            
            # Verify branches exist
            if not self.verify_branch_exists(pr.source_branch):
                error_msg = f"Source branch '{pr.source_branch}' does not exist in GitHub"
                logger.error(error_msg)
                return False, error_msg
            
            if not self.verify_branch_exists(pr.destination_branch):
                error_msg = f"Destination branch '{pr.destination_branch}' does not exist in GitHub"
                logger.error(error_msg)
                return False, error_msg
            
            # Verify commits exist on GitHub (Issue A: Commit validation)
            if pr.commits:
                all_commits_exist, missing_commits = self.verify_commits_exist(pr.commits)
                if not all_commits_exist:
                    error_msg = (
                        f"Some commits from Bitbucket PR are missing in GitHub. "
                        f"Missing SHAs: {missing_commits[:5]}{'...' if len(missing_commits) > 5 else ''}. "
                        f"This may indicate the repository was rebased/squashed during migration."
                    )
                    logger.error(error_msg)
                    return False, error_msg
            
            
            existing_prs = self.repo.get_pulls(
                state='open',
                head=f"{self.owner}:{pr.source_branch}",
                base=pr.destination_branch
            )
            
            if existing_prs.totalCount > 0:
                existing_pr_numbers = [p.number for p in list(existing_prs)[:3]]  # Show first 3
                error_msg = f"PR already exists with head={pr.source_branch} and base={pr.destination_branch} (GitHub PR(s): {existing_pr_numbers})"
                logger.warning(error_msg)
                return False, error_msg
            
            # Build PR body with attribution
            body = self._build_pr_body(pr)
            
            # Create the pull request with appropriate head format
            github_pr = self.repo.create_pull(
                title=pr.title,
                body=body,
                head=head,
                base=pr.destination_branch
            )
            
            # Add reviewers
            self._add_reviewers(github_pr, pr.reviewers)
            
            # Add comments
            self._add_comments(github_pr, pr.comments)
            
            return True, ""
        
        except GithubException as e:
            # Extract detailed error information
            error_details = {
                'status': e.status,
                'message': e.data.get('message', str(e)) if hasattr(e, 'data') and e.data else str(e),
                'errors': e.data.get('errors', []) if hasattr(e, 'data') and e.data else [],
                'documentation_url': e.data.get('documentation_url', '') if hasattr(e, 'data') and e.data else ''
            }
            
            error_msg = f"GitHub API error: {error_details['status']} - {error_details['message']}"
            
            # Add detailed errors if available
            if error_details['errors']:
                error_msg += f" | Errors: {error_details['errors']}"
            
            return False, error_msg
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"
    
    def _build_pr_body(self, pr: PullRequest) -> str:
        """
        Build PR body with original author attribution
        
        Args:
            pr: PullRequest object
            
        Returns:
            Formatted PR body
        """
        # Get mapped GitHub username or original identifier
        mapped_author = self.user_mapper.get_github_user(pr.author)
        
        if mapped_author:
            author_line = f"**Original Author:** @{mapped_author}"
        else:
            author_line = f"**Original Author:** {pr.author}"
            if pr.author_email:
                author_line += f" ({pr.author_email})"
        
        # Build body
        body_parts = [
            "---",
            "**🔄 Migrated from Bitbucket**",
            f"**Bitbucket PR ID:** #{pr.id}",
            author_line,
            f"**Created:** {pr.created_date.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**Updated:** {pr.updated_date.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "---",
            ""
        ]
        
        # Add original description
        if pr.description:
            body_parts.append(pr.description)
        
        return "\n".join(body_parts)
    
    def _add_reviewers(self, github_pr, reviewers: List[PRReviewer]):
        """
        Add reviewers to GitHub PR
        
        Args:
            github_pr: GitHub PR object
            reviewers: List of PRReviewer objects
        """
        if not reviewers:
            return
        
        valid_reviewers = []
        invalid_reviewers = []
        unmapped_reviewers = []
        
        for reviewer in reviewers:
            mapped_username = self.user_mapper.get_github_user(reviewer.username)
            if mapped_username:
                # Validate that the reviewer has access to the repository
                if self._validate_reviewer(mapped_username):
                    valid_reviewers.append(mapped_username)
                else:
                    invalid_reviewers.append({
                        'bitbucket': reviewer.username,
                        'github': mapped_username,
                        'reason': 'No repository access or not a collaborator'
                    })
            else:
                unmapped_reviewers.append(reviewer.username)
        
        # Request reviews from valid reviewers only
        if valid_reviewers:
            try:
                github_pr.create_review_request(reviewers=valid_reviewers)
            except GithubException as e:
                # This should rarely happen now since we validated reviewers
                # Move all to invalid list
                for username in valid_reviewers:
                    invalid_reviewers.append({
                        'bitbucket': 'unknown',
                        'github': username,
                        'reason': str(e)
                    })
        
        # Log unmapped and invalid reviewers as comment
        failed_reviewers = []
        if unmapped_reviewers:
            failed_reviewers.append("**⚠️ Unmapped Reviewers from Bitbucket:**\n")
            failed_reviewers.extend([f"- {r} (no GitHub mapping found)" for r in unmapped_reviewers])
        
        if invalid_reviewers:
            if failed_reviewers:
                failed_reviewers.append("")  # Empty line separator
            failed_reviewers.append("**⚠️ Reviewers Without Repository Access:**\n")
            failed_reviewers.extend([
                f"- {r['bitbucket']} → @{r['github']} ({r['reason']})" 
                for r in invalid_reviewers
            ])
        
        if failed_reviewers:
            comment_body = "\n".join(failed_reviewers)
            comment_body += "\n\n*These reviewers could not be added automatically. Please add them manually if they need access.*"
            
            try:
                github_pr.create_issue_comment(comment_body)
            except GithubException as e:
                pass
    
    def _validate_reviewer(self, github_username: str) -> bool:
        """
        Validate if a GitHub user can be added as a reviewer
        
        Args:
            github_username: GitHub username to validate
            
        Returns:
            True if user is a valid collaborator, False otherwise
        """
        try:
            # Check if user is a collaborator on the repository
            # This includes org members with repo access and external collaborators
            collaborators = self.repo.get_collaborators()
            for collaborator in collaborators:
                if collaborator.login.lower() == github_username.lower():
                    return True
            
            return False
            
        except GithubException as e:
            return False
    
    def _add_comments(self, github_pr, comments: List[PRComment]):
        """
        Add comments to GitHub PR
        
        Args:
            github_pr: GitHub PR object
            comments: List of PRComment objects
        """
        if not comments:
            return
        
        for comment in comments:
            try:
                # Get mapped author or use original (Issue G: Enhanced fallback with email)
                mapped_author = self.user_mapper.get_github_user(comment.author)
                
                if mapped_author:
                    author_prefix = f"**Original Author:** @{mapped_author}\n\n"
                else:
                    # Include email if available for better user identification
                    author_prefix = f"**Original Author:** {comment.author}"
                    if comment.author_email:
                        author_prefix += f" ({comment.author_email})"
                    author_prefix += "\n\n"
                
                # Build comment body
                comment_body = author_prefix + comment.content
                comment_body += f"\n\n*Posted on: {comment.created_date.strftime('%Y-%m-%d %H:%M:%S UTC')}*"
                
                # Create comment
                github_pr.create_issue_comment(comment_body)
            
            except GithubException as e:
                pass
            except Exception as e:
                pass

