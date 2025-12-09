"""
Logging utilities for PR migration
"""
import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Any
from models import PullRequest


class PRLogger:
    """Handles logging of closed PRs and failed migrations"""
    
    def __init__(self, closed_pr_file: str, failed_pr_file: str):
        self.closed_pr_file = closed_pr_file
        self.failed_pr_file = failed_pr_file
        self.logger = logging.getLogger(__name__)
        
        # Track counts for current session only
        self.session_stats = {
            'merged_count': 0,
            'declined_count': 0,
            'superseded_count': 0,
            'failed_count': 0
        }
        
        # Create logs directory if it doesn't exist
        closed_dir = os.path.dirname(closed_pr_file)
        if closed_dir:  # Only create if there's a directory path
            os.makedirs(closed_dir, exist_ok=True)
        
        failed_dir = os.path.dirname(failed_pr_file)
        if failed_dir:  # Only create if there's a directory path
            os.makedirs(failed_dir, exist_ok=True)
        
        # Initialize files if they don't exist
        self._initialize_file(closed_pr_file)
        self._initialize_file(failed_pr_file)
    
    def _initialize_file(self, filepath: str):
        """Initialize JSON file if it doesn't exist"""
        if not os.path.exists(filepath):
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump([], f)
    
    def log_closed_pr(self, pr: PullRequest):
        """
        Log a closed PR that was not migrated
        All closed PRs logged to single file with status field
        
        Args:
            pr: PullRequest object to log
        """
        try:
            # Determine PR status type
            if pr.is_merged():
                pr_status = "MERGED"
            elif pr.is_declined():
                pr_status = "DECLINED"
            elif pr.is_superseded():
                pr_status = "SUPERSEDED"
            else:
                pr_status = pr.state
            
            # Read existing data
            with open(self.closed_pr_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Append new PR with comprehensive details
            pr_data = pr.to_dict()
            # Remove fork-related fields for closed PRs
            pr_data.pop('is_fork', None)
            pr_data.pop('fork_repo_owner', None)
            pr_data.pop('fork_repo_name', None)
            pr_data['status'] = pr_status
            pr_data['logged_at'] = datetime.now().isoformat()
            pr_data['reason_not_migrated'] = f"PR is {pr_status} - Only OPEN PRs are migrated"
            data.append(pr_data)
            
            # Write back
            with open(self.closed_pr_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Update session stats
            if pr_status == "MERGED":
                self.session_stats['merged_count'] += 1
            elif pr_status == "DECLINED":
                self.session_stats['declined_count'] += 1
            elif pr_status == "SUPERSEDED":
                self.session_stats['superseded_count'] += 1
            
            self.logger.info(f"Logged {pr_status} PR #{pr.id}: {pr.title} to {os.path.basename(self.closed_pr_file)}")
        
        except Exception as e:
            self.logger.error(f"Failed to log closed PR #{pr.id}: {e}")
    
    def log_failed_pr(self, pr: PullRequest, reason: str, error_details: str = ""):
        """
        Log a PR that failed to migrate
        
        Args:
            pr: PullRequest object that failed
            reason: Reason for failure
            error_details: Additional error details
        """
        try:
            # Read existing data
            with open(self.failed_pr_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Create failure record
            failure_record = {
                'pr_id': pr.id,
                'title': pr.title,
                'reason': reason,
                'error_details': error_details,
                'source_branch': pr.source_branch,
                'destination_branch': pr.destination_branch,
                'author': pr.author,
                'created_date': pr.created_date.isoformat(),
                'failed_at': datetime.now().isoformat()
            }
            
            data.append(failure_record)
            
            # Write back
            with open(self.failed_pr_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Update session stats
            self.session_stats['failed_count'] += 1
            
            self.logger.error(f"Logged failed PR #{pr.id}: {reason}")
        
        except Exception as e:
            self.logger.error(f"Failed to log failed PR #{pr.id}: {e}")
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary of logged PRs for CURRENT SESSION only
        (not historical data from previous runs)
        """
        summary = {
            'closed_prs_count': (
                self.session_stats['merged_count'] + 
                self.session_stats['declined_count'] + 
                self.session_stats['superseded_count']
            ),
            'merged_prs_count': self.session_stats['merged_count'],
            'declined_prs_count': self.session_stats['declined_count'],
            'superseded_prs_count': self.session_stats['superseded_count'],
            'failed_prs_count': self.session_stats['failed_count']
        }
        
        return summary
