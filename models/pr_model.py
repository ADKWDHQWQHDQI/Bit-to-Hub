"""
Data models for Pull Request representation
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class PRComment:
    """Represents a comment on a pull request"""
    id: int
    author: str
    author_email: Optional[str]
    content: str
    created_date: datetime
    updated_date: Optional[datetime] = None
    
    def to_dict(self):
        return {
            'id': self.id,
            'author': self.author,
            'author_email': self.author_email,
            'content': self.content,
            'created_date': self.created_date.isoformat(),
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }


@dataclass
class PRReviewer:
    """Represents a reviewer on a pull request"""
    username: str
    email: Optional[str]
    approval_status: Optional[str] = None  # approved, changes_requested, etc.
    
    def to_dict(self):
        return {
            'username': self.username,
            'email': self.email,
            'approval_status': self.approval_status
        }


@dataclass
class PullRequest:
    """Represents a Pull Request from Bitbucket"""
    id: int
    title: str
    description: Optional[str]
    author: str
    author_email: Optional[str]
    source_branch: str
    destination_branch: str
    state: str  # OPEN, MERGED, DECLINED, SUPERSEDED
    created_date: datetime
    updated_date: datetime
    closed_date: Optional[datetime] = None
    merge_commit: Optional[str] = None
    comments: List[PRComment] = field(default_factory=list)
    reviewers: List[PRReviewer] = field(default_factory=list)
    commits: List[str] = field(default_factory=list)  # List of commit SHAs
    # Additional fields for comprehensive logging
    close_source_commit: Optional[str] = None  # Last commit on source branch when closed
    participants_count: int = 0  # Number of participants
    task_count: int = 0  # Number of tasks/todos in PR
    # Fork-related fields
    is_fork: bool = False  # True if PR is from a forked repository
    fork_repo_owner: Optional[str] = None  # Owner of the fork repository
    fork_repo_name: Optional[str] = None  # Name of the fork repository
    
    def to_dict(self):
        """Convert PR to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'author': self.author,
            'author_email': self.author_email,
            'source_branch': self.source_branch,
            'destination_branch': self.destination_branch,
            'state': self.state,
            'created_date': self.created_date.isoformat(),
            'updated_date': self.updated_date.isoformat(),
            'closed_date': self.closed_date.isoformat() if self.closed_date else None,
            'merge_commit': self.merge_commit,
            'close_source_commit': self.close_source_commit,
            'comments': [c.to_dict() for c in self.comments],
            'reviewers': [r.to_dict() for r in self.reviewers],
            'commits': self.commits,
            'participants_count': self.participants_count,
            'task_count': self.task_count,
            'comments_count': len(self.comments),
            'reviewers_count': len(self.reviewers),
            'commits_count': len(self.commits),
            'is_fork': self.is_fork,
            'fork_repo_owner': self.fork_repo_owner,
            'fork_repo_name': self.fork_repo_name
        }
    
    def is_open(self) -> bool:
        """Check if PR is open"""
        return self.state == 'OPEN'
    
    def is_closed(self) -> bool:
        """Check if PR is closed (merged, declined, or superseded)"""
        return self.state in ['MERGED', 'DECLINED', 'SUPERSEDED']
    
    def is_merged(self) -> bool:
        """Check if PR is merged"""
        return self.state == 'MERGED'
    
    def is_declined(self) -> bool:
        """Check if PR is declined"""
        return self.state == 'DECLINED'
    
    def is_superseded(self) -> bool:
        """Check if PR is superseded"""
        return self.state == 'SUPERSEDED'
