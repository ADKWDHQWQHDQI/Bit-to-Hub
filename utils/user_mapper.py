"""
User mapping utility to map Bitbucket users to GitHub users
"""
import yaml
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class UserMapper:
    """Handles mapping between Bitbucket and GitHub users"""
    
    def __init__(self, mapping_file: str = "user_mapping.yaml"):
        self.mapping_file = mapping_file
        self.mapping: Dict[str, str] = {}
        self.warned_users: set = set()  # Track users we've already warned about
        self.load_mapping()
    
    def load_mapping(self):
        """Load user mapping from YAML file"""
        try:
            with open(self.mapping_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                if data:
                    self.mapping = data
                    logger.info(f"Loaded {len(self.mapping)} user mappings from {self.mapping_file}")
                else:
                    logger.warning(f"No user mappings found in {self.mapping_file}")
        except FileNotFoundError:
            logger.error(f"User mapping file not found: {self.mapping_file}")
            self.mapping = {}
        except Exception as e:
            logger.error(f"Error loading user mapping: {e}")
            self.mapping = {}
    
    def get_github_user(self, bitbucket_identifier: str) -> Optional[str]:
        """
        Get GitHub username for a Bitbucket user
        
        Args:
            bitbucket_identifier: Bitbucket username, display_name, or account_id
            
        Returns:
            GitHub username if mapped, None otherwise
        """
        if not bitbucket_identifier:
            return None
        
        # Clean identifier (remove Bitbucket account_id format if present)
        # Account IDs look like: "712020:634d5063-6091-4f3c-8b08-64ccd298144d"
        clean_identifier = bitbucket_identifier
        if ':' in bitbucket_identifier and len(bitbucket_identifier) > 20:
            # This looks like an account_id, skip mapping attempt
            logger.debug(f"Skipping mapping for account_id: {bitbucket_identifier[:20]}...")
            return None
            
        # Try direct username lookup
        if clean_identifier in self.mapping:
            github_user = self.mapping[clean_identifier]
            logger.debug(f"Mapped {clean_identifier} -> {github_user}")
            return github_user
        
        # Try case-insensitive lookup
        for bb_key, gh_value in self.mapping.items():
            if bb_key.lower() == clean_identifier.lower():
                logger.debug(f"Mapped (case-insensitive) {clean_identifier} -> {gh_value}")
                return gh_value
        
        # Only warn once per unique user (avoid spam)
        if clean_identifier not in self.warned_users:
            self.warned_users.add(clean_identifier)
            logger.warning(
                f"No mapping found for Bitbucket user: {clean_identifier}. "
                f"Consider adding this user to {self.mapping_file} for proper attribution."
            )
        
        return None
    
    def get_mapped_or_original(self, bitbucket_identifier: str) -> str:
        """
        Get GitHub username if mapped, otherwise return original identifier
        
        Args:
            bitbucket_identifier: Bitbucket username or email
            
        Returns:
            GitHub username if mapped, original identifier otherwise
        """
        mapped = self.get_github_user(bitbucket_identifier)
        return mapped if mapped else bitbucket_identifier
    
    def is_mapped(self, bitbucket_identifier: str) -> bool:
        """Check if a Bitbucket user is mapped to GitHub"""
        return self.get_github_user(bitbucket_identifier) is not None
