"""
Bitbucket API client for fetching pull requests
"""
import requests
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from dateutil import parser
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from models import PullRequest, PRComment, PRReviewer


logger = logging.getLogger(__name__)


class BitbucketClient:
    """Client for interacting with Bitbucket REST API 2.0"""
    
    BASE_URL = "https://api.bitbucket.org/2.0"
    OAUTH_TOKEN_URL = "https://bitbucket.org/site/oauth2/access_token"
    
    def __init__(self, workspace: str, repository: str, oauth_key: str = None, oauth_secret: str = None, token: str = None):#type: ignore
        """
        Initialize Bitbucket client
        
        Args:
            workspace: Bitbucket workspace name
            repository: Repository name
            oauth_key: OAuth Consumer Key (for OAuth 2.0 client credentials)
            oauth_secret: OAuth Consumer Secret (for OAuth 2.0 client credentials)
            token: Bitbucket API token (Bearer token) - alternative to OAuth
        """
        self.workspace = workspace
        self.repository = repository
        self.session = requests.Session()
        self.oauth_key = oauth_key
        self.oauth_secret = oauth_secret
        self.access_token = None
        self.token_expires_at = None
        
        # Use OAuth credentials if provided, otherwise use Bearer token
        if oauth_key and oauth_secret:
            self._refresh_oauth_token()
        elif token:
            self.access_token = token
            self.session.headers.update({
                'Authorization': f'Bearer {token}'
            })
        else:
            raise ValueError("Either oauth_key/oauth_secret or token must be provided")
        
        self.session.headers.update({
            'Accept': 'application/json'
        })
    
    def _refresh_oauth_token(self):
        """Get or refresh OAuth 2.0 access token using client credentials flow"""
        try:
            response = requests.post(
                self.OAUTH_TOKEN_URL,
                auth=(self.oauth_key, self.oauth_secret),
                data={'grant_type': 'client_credentials'}
            )
            response.raise_for_status()
            
            token_data = response.json()
            self.access_token = token_data['access_token']
            expires_in = token_data.get('expires_in', 7200)  # Default 2 hours
            
            # Set expiration time (subtract 60 seconds buffer)
            self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 60)
            
            # Update session with new token
            self.session.headers.update({
                'Authorization': f'Bearer {self.access_token}'
            })
            
            logger.info(f"OAuth token obtained, expires in {expires_in} seconds")
            
        except Exception as e:
            logger.error(f"Failed to get OAuth access token: {e}")
            raise
    
    def _ensure_valid_token(self):
        """Ensure we have a valid access token, refresh if needed"""
        if not self.oauth_key or not self.oauth_secret:
            return  # Using static Bearer token, no refresh needed
        
        if self.token_expires_at is None or datetime.now() >= self.token_expires_at:
            self._refresh_oauth_token()
    
    @retry(
        retry=retry_if_exception_type((requests.exceptions.RequestException,)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        before_sleep=lambda retry_state: logger.warning(
            f"Retrying Bitbucket API call (attempt {retry_state.attempt_number}/5)..."
        ),
        retry_error_callback=lambda retry_state: logger.error(
            "All retry attempts failed. Please check your Bitbucket credentials and permissions."
        )
    )
    def _get(self, url: str, params: Optional[dict] = None) -> dict:
        """Make GET request to Bitbucket API"""
        # Ensure we have a valid OAuth token
        self._ensure_valid_token()
        
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            raise
        except requests.exceptions.RequestException as e:
            raise
    
    def _get_paginated(self, url: str, params: Optional[dict] = None) -> List[dict]:
        """Get all pages from paginated Bitbucket API endpoint"""
        results = []
        current_url = url
        
        while current_url:
            data = self._get(current_url, params)
            if data is None:
                raise RuntimeError("Bitbucket API request failed - check credentials and permissions")
            results.extend(data.get('values', []))
            current_url = data.get('next')
            params = None  # Params are included in 'next' URL
        
        return results
    
    def get_all_pull_requests(self, state: Optional[str] = None) -> List[PullRequest]:
        """
        Fetch all pull requests from the repository
        
        Args:
            state: Filter by state (OPEN, MERGED, DECLINED, SUPERSEDED). None for all.
            
        Returns:
            List of PullRequest objects
        """
        url = f"{self.BASE_URL}/repositories/{self.workspace}/{self.repository}/pullrequests"
        
        #  fetch ALL states
        # Bitbucket API supports multiple state parameters in single request
        if state is None:
            # Use query params with multiple state values for single API call
            params = {
                'state': ['OPEN', 'MERGED', 'DECLINED', 'SUPERSEDED']
            }
            pr_data_list = self._get_paginated(url, params)
        else:
            params = {'state': state}
            pr_data_list = self._get_paginated(url, params)
        
        pull_requests = []
        for pr_data in pr_data_list:
            try:
                pr = self._parse_pull_request(pr_data)
                pull_requests.append(pr)
            except Exception as e:
                pr_id = pr_data.get('id', 'unknown')
                logger.error(f"Failed to parse PR #{pr_id}: {e}")
        
        return pull_requests
    
    def _parse_pull_request(self, pr_data: dict) -> PullRequest:
        """Parse Bitbucket PR data into PullRequest object"""
        pr_id = pr_data['id']
        
        # Get author info (Issue #5: Prioritize username over display_name)
        author_data = pr_data.get('author', {})
        # Priority: nickname (username) > display_name > account_id
        author = author_data.get('nickname') or author_data.get('display_name') or author_data.get('account_id', 'unknown')
        author_email = author_data.get('account_id')  # Bitbucket account_id for reference
        
        # Parse dates
        created_date = parser.parse(pr_data['created_on'])
        updated_date = parser.parse(pr_data['updated_on'])
        closed_date = None
        if pr_data.get('closed_on'):
            closed_date = parser.parse(pr_data['closed_on'])
        
        # Get branch info
        source_branch = pr_data['source']['branch']['name']
        dest_branch = pr_data['destination']['branch']['name']
        
        # Check if source is from a fork (different repository)
        source_repo_data = pr_data.get('source', {}).get('repository', {})
        dest_repo_data = pr_data.get('destination', {}).get('repository', {})
        
        is_fork = False
        fork_repo_owner = None
        fork_repo_name = None
        
        if source_repo_data and dest_repo_data:
            source_full_name = source_repo_data.get('full_name', '')
            dest_full_name = dest_repo_data.get('full_name', '')
            
            if source_full_name and dest_full_name and source_full_name != dest_full_name:
                is_fork = True
                # Extract owner from full_name (format: "owner/repo")
                if '/' in source_full_name:
                    fork_repo_owner, fork_repo_name = source_full_name.split('/', 1)
                    logger.debug(f"PR #{pr_id} is from fork: {source_full_name}")
        
        # Get merge commit if merged
        merge_commit = None
        if pr_data['state'] == 'MERGED' and pr_data.get('merge_commit'):
            merge_commit = pr_data['merge_commit'].get('hash')
        
        # Create PR object
        pr = PullRequest(
            id=pr_id,
            title=pr_data['title'],
            description=pr_data.get('description', ''),
            author=author,
            author_email=author_email,
            source_branch=source_branch,
            destination_branch=dest_branch,
            state=pr_data['state'],
            created_date=created_date,
            updated_date=updated_date,
            closed_date=closed_date,
            merge_commit=merge_commit,
            participants_count=len(pr_data.get('participants', [])),
            task_count=pr_data.get('task_count', 0),
            is_fork=is_fork,
            fork_repo_owner=fork_repo_owner,
            fork_repo_name=fork_repo_name
        )
        
        # Get close source commit if PR is closed
        if pr.is_closed() and pr_data.get('source', {}).get('commit', {}).get('hash'):
            pr.close_source_commit = pr_data['source']['commit']['hash']
        
        # Fetch additional details
        logger.debug(f"Fetching details for PR #{pr_id}: {pr.title}")
        pr.comments = self._get_pr_comments(pr_id)
        pr.reviewers = self._get_pr_reviewers(pr_data)
        pr.commits = self._get_pr_commits(pr_id)
        
        return pr
    
    def _get_pr_comments(self, pr_id: int) -> List[PRComment]:
        """Fetch comments for a pull request"""
        url = f"{self.BASE_URL}/repositories/{self.workspace}/{self.repository}/pullrequests/{pr_id}/comments"
        
        try:
            comments_data = self._get_paginated(url)
            comments = []
            
            for comment_data in comments_data:
                # Get author info (Issue #5: Prioritize username over display_name)
                author_data = comment_data.get('user', {})
                # Priority: nickname (username) > display_name > account_id
                author = author_data.get('nickname') or author_data.get('display_name') or author_data.get('account_id', 'unknown')
                author_email = author_data.get('account_id')
                
                comment = PRComment(
                    id=comment_data['id'],
                    author=author,
                    author_email=author_email,
                    content=comment_data['content']['raw'],
                    created_date=parser.parse(comment_data['created_on']),
                    updated_date=parser.parse(comment_data['updated_on']) if comment_data.get('updated_on') else None
                )
                comments.append(comment)
            
            logger.debug(f"Fetched {len(comments)} comments")
            return comments
        
        except Exception as e:
            logger.error(f"Failed to fetch comments for PR #{pr_id}: {e}")
            return []
    
    def _get_pr_reviewers(self, pr_data: dict) -> List[PRReviewer]:
        """Extract reviewers from PR data"""
        reviewers = []
        
        for participant in pr_data.get('participants', []):
            if participant.get('role') in ['REVIEWER', 'PARTICIPANT']:
                user_data = participant.get('user', {})
                # Priority: nickname (username) > display_name > account_id (Issue #5)
                username = user_data.get('nickname') or user_data.get('display_name') or user_data.get('account_id', 'unknown')
                email = user_data.get('account_id')
                
                # Get approval status
                approval_status = None
                if participant.get('approved'):
                    approval_status = 'approved'
                elif participant.get('state') == 'changes_requested':
                    approval_status = 'changes_requested'
                
                reviewer = PRReviewer(
                    username=username,
                    email=email,
                    approval_status=approval_status
                )
                reviewers.append(reviewer)
        
        return reviewers
    
    def _get_pr_commits(self, pr_id: int) -> List[str]:
        """Fetch commit SHAs for a pull request"""
        url = f"{self.BASE_URL}/repositories/{self.workspace}/{self.repository}/pullrequests/{pr_id}/commits"
        
        try:
            commits_data = self._get_paginated(url)
            commit_shas = [commit['hash'] for commit in commits_data]
            logger.debug(f"Fetched {len(commit_shas)} commits")
            return commit_shas
        
        except Exception as e:
            logger.error(f"Failed to fetch commits for PR #{pr_id}: {e}")
            return []
