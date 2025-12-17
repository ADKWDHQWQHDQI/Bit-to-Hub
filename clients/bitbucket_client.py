"""
Bitbucket API client for fetching pull requests
"""
import requests
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from dateutil import parser
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from models import PullRequest, PRComment, PRReviewer, PRTask


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
    
    def get_pull_request_data(self, pr_number: int) -> Optional[dict]:
        """
        Fetch raw PR data from Bitbucket API
        
        Args:
            pr_number: The PR number to fetch
            
        Returns:
            Raw PR data dict or None if not found
        """
        url = f"{self.BASE_URL}/repositories/{self.workspace}/{self.repository}/pullrequests/{pr_number}"
        
        try:
            response = self.session.get(url)
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"PR #{pr_number} not found in {self.workspace}/{self.repository}")
                return None
            else:
                logger.error(f"Failed to fetch PR #{pr_number}: {e}")
                return None
        except Exception as e:
            logger.error(f"Error fetching PR #{pr_number}: {e}")
            return None
    
    def get_pull_request(self, pr_number: int) -> Optional[PullRequest]:
        """
        Fetch a specific pull request by its number
        
        Args:
            pr_number: The PR number to fetch
            
        Returns:
            PullRequest object or None if not found
        """
        pr_data = self.get_pull_request_data(pr_number)
        if pr_data:
            # Parse and return the PR (skip fetching full details since we already have them)
            pr = self._parse_pull_request(pr_data, fetch_full_details=False)
            return pr
        return None
    
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
    
    def _parse_pull_request(self, pr_data: dict, fetch_full_details: bool = True) -> PullRequest:
        """Parse Bitbucket PR data into PullRequest object"""
        pr_id = pr_data['id']
        
        # If we don't have reviewers/participants data (from paginated list), fetch full PR details
        if fetch_full_details and ('reviewers' not in pr_data or 'participants' not in pr_data):
            logger.info(f"Fetching full PR details for PR #{pr_id} (reviewers/participants missing from summary)")
            full_pr_data = self.get_pull_request_data(pr_id)
            if full_pr_data:
                pr_data = full_pr_data
        
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
        pr.tasks = self._get_pr_tasks(pr_id)
        
        return pr
    
    def _get_pr_comments(self, pr_id: int) -> List[PRComment]:
        """Fetch comments for a pull request"""
        url = f"{self.BASE_URL}/repositories/{self.workspace}/{self.repository}/pullrequests/{pr_id}/comments"
        
        try:
            comments_data = self._get_paginated(url)
            comments = []
            
            # First pass: Build a mapping of comment IDs to authors for parent lookups
            comment_authors = {}
            for comment_data in comments_data:
                comment_id = comment_data['id']
                author_data = comment_data.get('user', {})
                author = author_data.get('nickname') or author_data.get('display_name') or author_data.get('account_id', 'unknown')
                comment_authors[comment_id] = author
            
            # Second pass: Process all comments with correct parent author lookup
            for comment_data in comments_data:
                # Get author info (Issue #5: Prioritize username over display_name)
                author_data = comment_data.get('user', {})
                # Priority: nickname (username) > display_name > account_id
                author = author_data.get('nickname') or author_data.get('display_name') or author_data.get('account_id', 'unknown')
                author_email = author_data.get('account_id')
                
                # Extract parent comment information (for replies)
                parent_id = None
                parent_author = None
                if comment_data.get('parent'):
                    parent_id = comment_data['parent'].get('id')
                    # Look up parent author from our mapping (more reliable than nested API data)
                    parent_author = comment_authors.get(parent_id, 'Unknown User')
                    logger.debug(f"Comment {comment_data['id']} is a reply to comment {parent_id} by {parent_author}")
                
                # Extract inline comment data (file, line numbers)
                inline = None
                if comment_data.get('inline'):
                    inline_data = comment_data['inline']
                    inline = {
                        'path': inline_data.get('path', ''),
                        'from': inline_data.get('from'),
                        'to': inline_data.get('to')
                    }
                
                # Extract attachments from comment (separate from inline markdown images)
                attachments = []
                if comment_data.get('links') and comment_data['links'].get('attachments'):
                    # Fetch attachments for this comment
                    attachments = self._get_comment_attachments(pr_id, comment_data['id'])
                
                comment = PRComment(
                    id=comment_data['id'],
                    author=author,
                    author_email=author_email,
                    content=comment_data['content']['raw'],
                    created_date=parser.parse(comment_data['created_on']),
                    updated_date=parser.parse(comment_data['updated_on']) if comment_data.get('updated_on') else None,
                    inline=inline,
                    parent_id=parent_id,
                    parent_author=parent_author,
                    attachments=attachments
                )
                comments.append(comment)
            
            # Sort comments by date
            comments.sort(key=lambda x: x.created_date)
            
            logger.debug(f"Fetched {len(comments)} comments")
            return comments
        
        except Exception as e:
            logger.error(f"Failed to fetch comments for PR #{pr_id}: {e}")
            return []
    
    
    def _get_pr_reviewers(self, pr_data: dict) -> List[PRReviewer]:
        """Extract reviewers from PR data"""
        reviewers = []
        reviewer_usernames_seen = set()  # Track to avoid duplicates
        
        # Log what we're processing
        logger.info(f"Extracting reviewers from PR data. Top-level 'reviewers': {len(pr_data.get('reviewers', []))}, 'participants': {len(pr_data.get('participants', []))}")
        
        # First, extract from the top-level 'reviewers' array (explicitly assigned reviewers)
        for reviewer_data in pr_data.get('reviewers', []):
            user_data = reviewer_data if isinstance(reviewer_data, dict) and 'nickname' in reviewer_data else reviewer_data
            # Priority: nickname (username) > display_name > account_id (Issue #5)
            username = user_data.get('nickname') or user_data.get('display_name') or user_data.get('account_id', 'unknown')
            email = user_data.get('account_id')
            
            if username not in reviewer_usernames_seen:
                reviewer_usernames_seen.add(username)
                # Check participants for approval status
                approval_status = None
                for participant in pr_data.get('participants', []):
                    part_user = participant.get('user', {})
                    part_username = part_user.get('nickname') or part_user.get('display_name') or part_user.get('account_id', 'unknown')
                    if part_username == username:
                        if participant.get('approved'):
                            approval_status = 'approved'
                        elif participant.get('state') == 'changes_requested':
                            approval_status = 'changes_requested'
                        break
                
                reviewer = PRReviewer(
                    username=username,
                    email=email,
                    approval_status=approval_status
                )
                reviewers.append(reviewer)
                logger.info(f"Added reviewer from 'reviewers' array: {username} (approval: {approval_status})")
        
        # Then, extract from 'participants' array (people with REVIEWER role not already added)
        for participant in pr_data.get('participants', []):
            if participant.get('role') == 'REVIEWER':
                user_data = participant.get('user', {})
                # Priority: nickname (username) > display_name > account_id (Issue #5)
                username = user_data.get('nickname') or user_data.get('display_name') or user_data.get('account_id', 'unknown')
                email = user_data.get('account_id')
                
                if username not in reviewer_usernames_seen:
                    reviewer_usernames_seen.add(username)
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
                    logger.info(f"Added reviewer from 'participants' array: {username} (approval: {approval_status})")
        
        logger.info(f"Total reviewers extracted: {len(reviewers)}")
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
    
    def _get_comment_attachments(self, pr_id: int, comment_id: int) -> List[dict]:
        """
        Fetch attachments for a specific comment
        
        Args:
            pr_id: Pull request ID
            comment_id: Comment ID
            
        Returns:
            List of attachment dictionaries with 'name' and 'url'
        """
        url = f"{self.BASE_URL}/repositories/{self.workspace}/{self.repository}/pullrequests/{pr_id}/comments/{comment_id}/attachments"
        
        try:
            response = self.session.get(url)
            
            # Check for payment required error (free tier limitation)
            if response.status_code == 402:
                logger.warning(
                    f"Cannot access attachments for comment {comment_id}: "
                    "Bitbucket workspace requires paid plan (Standard/Premium) to access file attachments via API. "
                    "Inline images in markdown will still be migrated."
                )
                return []
            
            response.raise_for_status()
            data = response.json()
            
            attachments_data = data.get('values', [])
            attachments = []
            
            for attachment_data in attachments_data:
                # Get attachment name and download URL
                name = attachment_data.get('name', 'attachment')
                # Use the 'href' from 'links.self' for download URL
                download_url = attachment_data.get('links', {}).get('self', {}).get('href', '')
                
                if download_url:
                    attachments.append({
                        'name': name,
                        'url': download_url
                    })
                    logger.info(f"Found attachment: {name}")
            
            return attachments
        
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 402:
                logger.warning(
                    f"Cannot access attachments: Bitbucket free tier does not support file attachments API. "
                    "Upgrade to Standard/Premium plan to migrate file attachments (PDF, DOC, ZIP, etc.)."
                )
            else:
                logger.debug(f"No attachments found for comment {comment_id}: {e}")
            return []
        except Exception as e:
            logger.debug(f"No attachments accessible for comment {comment_id}: {e}")
            return []
    
    def _get_pr_tasks(self, pr_id: int) -> List[PRTask]:
        """
        Fetch tasks/todos for a pull request
        
        Args:
            pr_id: Pull request ID
            
        Returns:
            List of PRTask objects
        """
        url = f"{self.BASE_URL}/repositories/{self.workspace}/{self.repository}/pullrequests/{pr_id}/tasks"
        
        try:
            tasks_data = self._get_paginated(url)
            tasks = []
            
            for task_data in tasks_data:
                # Get creator info
                creator_data = task_data.get('creator', {})
                creator = creator_data.get('nickname') or creator_data.get('display_name') or creator_data.get('account_id', 'unknown')
                creator_email = creator_data.get('account_id')
                
                # Parse dates
                created_date = parser.parse(task_data['created_on'])
                updated_date = None
                if task_data.get('updated_on'):
                    updated_date = parser.parse(task_data['updated_on'])
                
                # Get comment ID if task is attached to a comment
                comment_id = None
                comment_data = task_data.get('comment')
                if comment_data and 'id' in comment_data:
                    comment_id = comment_data['id']
                
                # Extract content - it's a dict with 'raw', 'markup', 'html'
                content_data = task_data.get('content', {})
                if isinstance(content_data, dict):
                    content = content_data.get('raw', '')
                else:
                    content = str(content_data)
                
                task = PRTask(
                    id=task_data['id'],
                    content=content,
                    state=task_data.get('state', 'UNRESOLVED'),
                    creator=creator,
                    creator_email=creator_email,
                    created_date=created_date,
                    updated_date=updated_date,
                    comment_id=comment_id
                )
                tasks.append(task)
            
            logger.debug(f"Fetched {len(tasks)} tasks")
            return tasks
        
        except Exception as e:
            logger.error(f"Failed to fetch tasks for PR #{pr_id}: {e}")
            return []
