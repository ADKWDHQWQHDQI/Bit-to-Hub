"""
GitHub API client for migrating pull requests
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
from github import Github, GithubException
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from models import PullRequest, PRComment, PRReviewer, PRTask
from utils import UserMapper, MarkdownConverter, ImageMigrator


logger = logging.getLogger(__name__)


class GitHubClient:
    """Client for interacting with GitHub API to create pull requests"""
    
    def __init__(self, token: str, owner: str, repository: str,
                 bitbucket_workspace: Optional[str] = None, bitbucket_repo: Optional[str] = None, 
                 bitbucket_token: Optional[str] = None, skip_commit_verification: bool = False,
                 skip_prs_with_missing_branches: bool = False):
        """
        Initialize GitHub client
        
        Args:
            token: GitHub Personal Access Token
            owner: Repository owner (org or user)
            repository: Repository name
            bitbucket_workspace: Bitbucket workspace (for image migration)
            bitbucket_repo: Bitbucket repository (for image migration)
            bitbucket_token: Bitbucket token (for image migration)
            skip_commit_verification: Skip commit SHA verification (useful for rebased repos)
            skip_prs_with_missing_branches: Skip PRs with missing source branches
        """
        self.github = Github(token)
        self.owner = owner
        self.repository = repository
        self.user_mapper = UserMapper()
        self.markdown_converter = MarkdownConverter()
        self.repo = self.github.get_repo(f"{owner}/{repository}")
        self.skip_commit_verification = skip_commit_verification
        self.skip_prs_with_missing_branches = skip_prs_with_missing_branches
        
        # Store Bitbucket info for URL generation in closed issues
        self.bitbucket_workspace = bitbucket_workspace or "unknown"
        self.bitbucket_repo = bitbucket_repo or "unknown"
        
        # Initialize image migrator if Bitbucket credentials provided
        self.image_migrator = None
        if bitbucket_workspace and bitbucket_repo and bitbucket_token:
            self.image_migrator = ImageMigrator(
                bitbucket_workspace=bitbucket_workspace,
                bitbucket_repo=bitbucket_repo,
                github_owner=owner,
                github_repo=repository,
                bitbucket_token=bitbucket_token,
                github_token=token
            )
            logger.info("Image migration enabled")
    
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
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    self.repo.get_commit(sha)
                    break  # Success, move to next SHA
                except GithubException as e:
                    if e.status == 404:
                        missing_shas.append(sha)
                        logger.warning(f"Commit {sha} not found in GitHub repository")
                        break  # 404 is definitive, no retry needed
                    elif attempt < max_attempts - 1:
                        # Retry on other errors (rate limits, timeouts, etc.)
                        wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4 seconds
                        logger.warning(f"Retrying commit verification for {sha} (attempt {attempt + 1}/{max_attempts})...")
                        import time
                        time.sleep(wait_time)
                    else:
                        # Final attempt failed, treat as missing
                        logger.error(f"Failed to verify commit {sha} after {max_attempts} attempts: {e}")
                        missing_shas.append(sha)
                except Exception as e:
                    # Handle any other unexpected errors
                    logger.error(f"Unexpected error verifying commit {sha}: {e}")
                    missing_shas.append(sha)
                    break
        
        return len(missing_shas) == 0, missing_shas
    
    def _utc_to_ist(self, utc_datetime: datetime) -> str:
        """
        Convert UTC datetime to IST (India Standard Time) format
        
        Args:
            utc_datetime: Datetime in UTC
            
        Returns:
            Formatted string in IST
        """
        # IST is UTC + 5:30
        ist_offset = timedelta(hours=5, minutes=30)
        
        # Ensure the datetime is timezone-aware
        if utc_datetime.tzinfo is None:
            utc_datetime = utc_datetime.replace(tzinfo=timezone.utc)
        
        ist_datetime = utc_datetime + ist_offset
        return ist_datetime.strftime('%Y-%m-%d %H:%M:%S IST')
    
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
                if self.skip_prs_with_missing_branches:
                    logger.warning(f"Skipping PR #{pr.id}: {error_msg}")
                    return False, error_msg
                logger.error(error_msg)
                return False, error_msg
            
            if not self.verify_branch_exists(pr.destination_branch):
                error_msg = f"Destination branch '{pr.destination_branch}' does not exist in GitHub"
                logger.error(error_msg)
                return False, error_msg
            
            # Verify commits exist on GitHub (Issue A: Commit validation)
            if pr.commits and not self.skip_commit_verification:
                all_commits_exist, missing_commits = self.verify_commits_exist(pr.commits)
                if not all_commits_exist:
                    error_msg = (
                        f"Some commits from Bitbucket PR are missing in GitHub. "
                        f"Missing SHAs: {missing_commits[:5]}{'...' if len(missing_commits) > 5 else ''}. "
                        f"This may indicate the repository was rebased/squashed during migration. "
                        f"Set skip_commit_verification=true in config.yaml to bypass this check."
                    )
                    logger.error(error_msg)
                    return False, error_msg
            elif self.skip_commit_verification:
                logger.info(f"Skipping commit verification for PR #{pr.id} (skip_commit_verification=true)")
            
            
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
            
            # Migrate images in PR description if image migrator is available
            if self.image_migrator and pr.description:
                logger.info(f"Migrating images in PR #{pr.id} description...")
                updated_body = self.image_migrator.migrate_images_in_text(body, github_pr.number)
                if updated_body != body:
                    github_pr.edit(body=updated_body)
                    logger.info("PR description updated with migrated images")
            
            # Add reviewers
            self._add_reviewers(github_pr, pr.reviewers)
            
            # Add comments and tasks together (tasks inserted after their parent comments)
            self._add_comments_and_tasks(github_pr, pr.comments, pr.tasks)
            
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
            
            logger.error(f"Failed to migrate PR #{pr.id}: {error_msg}")
            return False, error_msg
        except Exception as e:
            # Handle any other unexpected exceptions
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"Failed to migrate PR #{pr.id}: {error_msg}")
            return False, error_msg
    
    def _build_pr_body(self, pr: PullRequest) -> str:
        """
        Build PR body with original description only
        
        Args:
            pr: PullRequest object
            
        Returns:
            Original PR description
        """
        if pr.description:
            return self.markdown_converter.convert_pr_description(pr.description)
        return ""
    
    def _add_reviewers(self, github_pr, reviewers: List[PRReviewer]):
        """
        Add reviewers to GitHub PR
        
        Args:
            github_pr: GitHub PR object
            reviewers: List of PRReviewer objects
        """
        if not reviewers:
            logger.debug("No reviewers to add")
            return
        
        logger.info(f"Processing {len(reviewers)} reviewer(s) for PR")
        
        valid_reviewers = []
        invalid_reviewers = []
        unmapped_reviewers = []
        
        for reviewer in reviewers:
            logger.debug(f"Processing reviewer: {reviewer.username}")
            mapped_username = self.user_mapper.get_github_user(reviewer.username)
            if mapped_username:
                logger.info(f"Reviewer '{reviewer.username}' mapped to GitHub user '{mapped_username}'")
                # Validate that the reviewer has access to the repository
                if self._validate_reviewer(mapped_username):
                    valid_reviewers.append(mapped_username)
                    logger.info(f"✓ Reviewer '{mapped_username}' validated as collaborator")
                else:
                    logger.warning(f"✗ Reviewer '{mapped_username}' is not a repository collaborator")
                    invalid_reviewers.append({
                        'bitbucket': reviewer.username,
                        'github': mapped_username,
                        'reason': 'No repository access or not a collaborator'
                    })
            else:
                logger.warning(f"✗ Reviewer '{reviewer.username}' has no GitHub mapping")
                unmapped_reviewers.append(reviewer.username)
        
        # Request reviews from valid reviewers only
        if valid_reviewers:
            try:
                logger.info(f"Requesting reviews from: {', '.join(valid_reviewers)}")
                github_pr.create_review_request(reviewers=valid_reviewers)
                logger.info(f"✓ Successfully added {len(valid_reviewers)} reviewer(s) to GitHub PR")
            except GithubException as e:
                # This should rarely happen now since we validated reviewers
                logger.error(f"Failed to add reviewers: {e}")
                # Move all to invalid list
                for username in valid_reviewers:
                    invalid_reviewers.append({
                        'bitbucket': 'unknown',
                        'github': username,
                        'reason': str(e)
                    })
        else:
            logger.warning("No valid reviewers to add (all unmapped or lack repository access)")
        
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
                logger.info("Added comment listing unmapped/invalid reviewers")
            except GithubException as e:
                logger.error(f"Failed to add reviewer warning comment: {e}")
    
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
    
    def _add_comments_and_tasks(self, github_pr, comments: List[PRComment], tasks: List[PRTask]):
        """
        Add comments and tasks to GitHub PR with formatting preservation
        Tasks are inserted right after their parent comment
        
        Args:
            github_pr: GitHub PR object
            comments: List of PRComment objects
            tasks: List of PRTask objects
        """
        if not comments:
            return
        
        # Build a mapping of Bitbucket account IDs to usernames for mention resolution
        # Format: {"712020:uuid": "Username"}
        account_id_to_username = {}
        for comment in comments:
            if comment.author_email and comment.author:
                # author_email contains the account ID like "712020:634d5063-6091-4f3c-8b08-64ccd298144d"
                account_id_to_username[comment.author_email] = comment.author
        
        # Build a mapping of comment IDs to their content and authors for reply quoting
        # Format: {comment_id: {"author": "Username", "content": "comment text"}}
        comment_data_map = {}
        for comment in comments:
            comment_data_map[comment.id] = {
                "author": comment.author,
                "content": comment.content[:200]  # First 200 chars for quote preview
            }
        
        for comment in comments:
            try:
                # Build comment body
                comment_body_parts = []
                
                # Add reply with quoted parent comment if this is a response
                if comment.parent_id and comment.parent_id in comment_data_map:
                    parent_data = comment_data_map[comment.parent_id]
                    parent_author = parent_data["author"]
                    parent_content = parent_data["content"]
                    
                    # Get mapped parent author or use original
                    mapped_parent_author = self.user_mapper.get_github_user(parent_author)
                    parent_display = f"@{mapped_parent_author}" if mapped_parent_author else parent_author
                    
                    # Format as GitHub quote block
                    comment_body_parts.append(f"> {parent_display} wrote:\n")
                    # Quote each line of parent content
                    for line in parent_content.split('\n'):
                        comment_body_parts.append(f"> {line}\n")
                    comment_body_parts.append("\n")  # Blank line after quote
                
                # Add comment content (convert markdown)
                converted_content = self.markdown_converter.convert_comment(comment.content)
                
                # Replace Bitbucket UUID mentions with actual usernames
                # Pattern: @{712020:634d5063-6091-4f3c-8b08-64ccd298144d}
                import re
                def replace_uuid_mention(match):
                    account_id = match.group(1)
                    username = account_id_to_username.get(account_id)
                    if username:
                        # Try to get GitHub username mapping
                        github_user = self.user_mapper.get_github_user(username)
                        if github_user:
                            return f"@{github_user}"
                        return f"@{username}"
                    return "*(user mention)*"  # Fallback if not found
                
                converted_content = re.sub(r'@\{([0-9]+:[a-f0-9-]+)\}', replace_uuid_mention, converted_content)
                
                comment_body_parts.append(converted_content)
                
                # Migrate attachments if present
                if comment.attachments and self.image_migrator:
                    comment_body_parts.append("\n\n---\n**Attachments:**\n")
                    for attachment in comment.attachments:
                        try:
                            # Download and upload attachment
                            github_url = self.image_migrator.migrate_attachment(
                                attachment['url'], 
                                attachment['name'],
                                github_pr.number
                            )
                            if github_url:
                                # Add attachment link to comment
                                comment_body_parts.append(f"\n- [{attachment['name']}]({github_url})")
                                logger.info(f"Migrated attachment: {attachment['name']}")
                            else:
                                comment_body_parts.append(f"\n- ⚠️ {attachment['name']} (migration failed)")
                        except Exception as e:
                            logger.error(f"Failed to migrate attachment {attachment['name']}: {e}")
                            comment_body_parts.append(f"\n- ⚠️ {attachment['name']} (migration failed)")
                
                # Combine all parts
                comment_body = "".join(comment_body_parts)
                
                # Migrate images in comment if image migrator is available
                if self.image_migrator:
                    comment_body = self.image_migrator.migrate_images_in_text(comment_body, github_pr.number)
                
                # Create comment
                github_pr.create_issue_comment(comment_body)
                logger.debug(f"Added comment {comment.id}")
                
                # Check if any tasks are attached to this comment
                comment_tasks = [t for t in tasks if t.comment_id == comment.id]
                if comment_tasks:
                    # Add tasks right after this comment
                    task_lines = []
                    for task in comment_tasks:
                        checkbox = "[x]" if task.is_resolved() else "[ ]"
                        task_lines.append(f"- {checkbox} {task.content}")
                    
                    task_body = "\n".join(task_lines)
                    github_pr.create_issue_comment(task_body)
                    logger.debug(f"Added {len(comment_tasks)} task(s) after comment {comment.id}")
            
            except GithubException as e:
                logger.error(f"Failed to add comment {comment.id}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error adding comment {comment.id}: {e}")
    
    def create_closed_issue(self, pr: PullRequest) -> tuple[bool, str]:
        """
        Create a closed issue in GitHub for a closed Bitbucket PR
        
        Args:
            pr: PullRequest object (closed PR from Bitbucket)
            
        Returns:
            Tuple of (success: bool, error_message: str)
        """
        try:
            # Build issue title
            title = f"[Closed PR #{pr.id}] {pr.title}"
            
            # Build issue body with Bitbucket URL and description
            body_parts = []
            
            # Add plain Bitbucket PR URL
            bitbucket_url = f"https://bitbucket.org/{self.bitbucket_workspace}/{self.bitbucket_repo}/pull-requests/{pr.id}"
            body_parts.append(bitbucket_url)
            body_parts.append("\n---\n")
            
            # Add PR description with full formatting support
            if pr.description:
                converted_description = self.markdown_converter.convert_pr_description(pr.description)
                body_parts.append(converted_description)
            else:
                body_parts.append("*No description provided*")
            
            body = "\n".join(body_parts)
            
            # Migrate images in description if image migrator is available
            # Note: We use pr.id as placeholder since issue number doesn't exist yet
            if self.image_migrator and pr.description:
                logger.info(f"Migrating images in closed PR #{pr.id} description...")
                body = self.image_migrator.migrate_images_in_text(body, pr.id)
            
            # Create the issue
            github_issue = self.repo.create_issue(
                title=title,
                body=body
            )
            
            logger.info(f"Created GitHub issue #{github_issue.number} for closed PR #{pr.id}")
            
            # Add comments if present
            if pr.comments:
                logger.info(f"Adding {len(pr.comments)} comment(s) to issue #{github_issue.number}")
                self._add_comments_to_issue(github_issue, pr.comments)
            
            # Add tasks as comment if present
            if pr.tasks:
                self._add_tasks_to_issue(github_issue, pr.tasks)
            
            # Close the issue with appropriate state reason
            close_reason = None
            if pr.state == 'MERGED':
                close_reason = "completed"
            elif pr.state == 'DECLINED':
                close_reason = "not_planned"
            # For SUPERSEDED, use default (None)
            
            if close_reason:
                github_issue.edit(state='closed', state_reason=close_reason)
            else:
                github_issue.edit(state='closed')
            
            logger.info(f"Closed issue #{github_issue.number} with state: {pr.state}")
            
            return True, ""
        
        except GithubException as e:
            error_details = {
                'status': e.status,
                'message': e.data.get('message', str(e)) if hasattr(e, 'data') and e.data else str(e),
                'errors': e.data.get('errors', []) if hasattr(e, 'data') and e.data else []
            }
            
            error_msg = f"GitHub API error: {error_details['status']} - {error_details['message']}"
            if error_details['errors']:
                error_msg += f" | Errors: {error_details['errors']}"
            
            return False, error_msg
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"
    
    def _add_comments_to_issue(self, github_issue, comments: List[PRComment]):
        """
        Add comments to GitHub issue (similar to PR comments but for issues)
        
        Args:
            github_issue: GitHub Issue object
            comments: List of PRComment objects
        """
        if not comments:
            return
        
        # Build mappings
        account_id_to_username = {}
        for comment in comments:
            if comment.author_email and comment.author:
                account_id_to_username[comment.author_email] = comment.author
        
        comment_data_map = {}
        for comment in comments:
            comment_data_map[comment.id] = {
                "author": comment.author,
                "content": comment.content[:200]
            }
        
        for comment in comments:
            try:
                # Build comment body
                comment_body_parts = []
                
                # Add comment metadata with IST timestamp
                mapped_author = self.user_mapper.get_github_user(comment.author)
                author_display = f"@{mapped_author}" if mapped_author else comment.author
                comment_body_parts.append(f"**{author_display}** commented on {self._utc_to_ist(comment.created_date)}")
                if comment.updated_date and comment.updated_date != comment.created_date:
                    comment_body_parts.append(f" *(edited {self._utc_to_ist(comment.updated_date)})*")
                comment_body_parts.append("\n\n")
                
                # Add reply quote if present
                if comment.parent_id and comment.parent_id in comment_data_map:
                    parent_data = comment_data_map[comment.parent_id]
                    parent_author = parent_data["author"]
                    parent_content = parent_data["content"]
                    
                    mapped_parent_author = self.user_mapper.get_github_user(parent_author)
                    parent_display = f"@{mapped_parent_author}" if mapped_parent_author else parent_author
                    
                    comment_body_parts.append(f"> {parent_display} wrote:\n")
                    for line in parent_content.split('\n'):
                        comment_body_parts.append(f"> {line}\n")
                    comment_body_parts.append("\n")
                
                # Add inline comment context if present
                if comment.inline:
                    file_path = comment.inline.get('path', 'unknown')
                    from_line = comment.inline.get('from')
                    to_line = comment.inline.get('to')
                    if from_line and to_line:
                        comment_body_parts.append(f"📄 **Inline comment on** `{file_path}` (lines {from_line}-{to_line})\n\n")
                    else:
                        comment_body_parts.append(f"📄 **Inline comment on** `{file_path}`\n\n")
                
                # Add content
                converted_content = self.markdown_converter.convert_comment(comment.content)
                
                # Replace UUID mentions
                import re
                def replace_uuid_mention(match):
                    account_id = match.group(1)
                    username = account_id_to_username.get(account_id)
                    if username:
                        github_user = self.user_mapper.get_github_user(username)
                        if github_user:
                            return f"@{github_user}"
                        return f"@{username}"
                    return "*(user mention)*"
                
                converted_content = re.sub(r'@\{([0-9]+:[a-f0-9-]+)\}', replace_uuid_mention, converted_content)
                comment_body_parts.append(converted_content)
                
                # Migrate attachments if present
                if comment.attachments and self.image_migrator:
                    comment_body_parts.append("\n\n---\n**Attachments:**\n")
                    for attachment in comment.attachments:
                        try:
                            github_url = self.image_migrator.migrate_attachment(
                                attachment['url'], 
                                attachment['name'],
                                github_issue.number
                            )
                            if github_url:
                                comment_body_parts.append(f"\n- [{attachment['name']}]({github_url})")
                                logger.info(f"Migrated attachment: {attachment['name']}")
                            else:
                                comment_body_parts.append(f"\n- ⚠️ {attachment['name']} (migration failed)")
                        except Exception as e:
                            logger.error(f"Failed to migrate attachment {attachment['name']}: {e}")
                            comment_body_parts.append(f"\n- ⚠️ {attachment['name']} (migration failed)")
                
                comment_body = "".join(comment_body_parts)
                
                # Migrate images
                if self.image_migrator:
                    comment_body = self.image_migrator.migrate_images_in_text(comment_body, github_issue.number)
                
                # Create comment
                github_issue.create_comment(comment_body)
                logger.debug(f"Added comment {comment.id} to issue")
            
            except GithubException as e:
                logger.error(f"Failed to add comment {comment.id} to issue: {e}")
            except Exception as e:
                logger.error(f"Unexpected error adding comment {comment.id} to issue: {e}")
    
    def _add_tasks_to_issue(self, github_issue, tasks: List[PRTask]):
        """
        Add tasks to GitHub issue as a formatted comment
        
        Args:
            github_issue: GitHub Issue object
            tasks: List of PRTask objects
        """
        if not tasks:
            return
        
        try:
            # Group tasks by comment ID
            comment_tasks = {}
            orphan_tasks = []
            
            for task in tasks:
                if task.comment_id:
                    if task.comment_id not in comment_tasks:
                        comment_tasks[task.comment_id] = []
                    comment_tasks[task.comment_id].append(task)
                else:
                    orphan_tasks.append(task)
            
            # Add tasks grouped by comment
            for comment_id, task_list in comment_tasks.items():
                task_body_parts = [f"**📋 Tasks from comment {comment_id}:**\n\n"]
                for task in task_list:
                    checkbox = "[x]" if task.is_resolved() else "[ ]"
                    mapped_creator = self.user_mapper.get_github_user(task.creator)
                    creator_display = f"@{mapped_creator}" if mapped_creator else task.creator
                    task_body_parts.append(f"- {checkbox} {task.content} *(by {creator_display} on {self._utc_to_ist(task.created_date)})*\n")
                
                github_issue.create_comment("".join(task_body_parts))
                logger.debug(f"Added {len(task_list)} task(s) from comment {comment_id}")
            
            # Add orphan tasks (not attached to any comment)
            if orphan_tasks:
                task_body_parts = ["**📋 Tasks:**\n\n"]
                for task in orphan_tasks:
                    checkbox = "[x]" if task.is_resolved() else "[ ]"
                    mapped_creator = self.user_mapper.get_github_user(task.creator)
                    creator_display = f"@{mapped_creator}" if mapped_creator else task.creator
                    task_body_parts.append(f"- {checkbox} {task.content} *(by {creator_display} on {self._utc_to_ist(task.created_date)})*\n")
                
                github_issue.create_comment("".join(task_body_parts))
                logger.debug(f"Added {len(orphan_tasks)} orphan task(s)")
        
        except GithubException as e:
            logger.error(f"Failed to add tasks to issue: {e}")
        except Exception as e:
            logger.error(f"Unexpected error adding tasks to issue: {e}")


