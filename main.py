"""
Main application for Bitbucket to GitHub PR migration
"""
import sys
import logging
import yaml
import argparse
import os
from datetime import datetime
from typing import Dict, List, Optional
from clients import BitbucketClient, GitHubClient
from models import PullRequest
from utils import UserMapper, PRLogger


# Configure logging
def setup_logging(log_file: str = './logs/migration_summary.log'):
    """Setup logging configuration"""
    # Ensure logs directory exists
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, mode='a', encoding='utf-8')
        ]
    )


class PRMigrationOrchestrator:
    """Orchestrates the PR migration process"""
    
    def __init__(self, config_file: str = "config.yaml", dry_run: bool = False, test_mode: bool = False):
        """
        Initialize the migration orchestrator
        
        Args:
            config_file: Path to configuration YAML file
            dry_run: If True, no changes will be made to GitHub
            test_mode: If True, use test repository from config
        """
        self.logger = logging.getLogger(__name__)
        self.config = self._load_config(config_file)
        self.dry_run = dry_run
        self.test_mode = test_mode
        
        if self.dry_run:
            self.logger.warning("\n" + "*" * 70)
            self.logger.warning("DRY-RUN MODE: No changes will be made to GitHub")
            self.logger.warning("*" * 70 + "\n")
        
        if self.test_mode:
            self._enable_test_mode()
        
        # Validate configuration BEFORE initializing clients
        if not self.validate_config():
            self.logger.error("\n" + "=" * 70)
            self.logger.error("CONFIGURATION ERROR")
            self.logger.error("=" * 70)
            self.logger.error("Please update config.yaml with the required information:")
            self.logger.error("  1. Bitbucket workspace and repository names")
            self.logger.error("  2. GitHub owner and repository names")
            self.logger.error("  3. Valid API tokens for both services")
            self.logger.error("=" * 70 + "\n")
            sys.exit(1)
        
        # Initialize components
        self.user_mapper = UserMapper()
        self.pr_logger = PRLogger(
            self.config['logging']['closed_pr_archive'],
            self.config['logging']['failed_prs']
        )
        
        # Initialize API clients
        # Support both OAuth (key/secret) and Bearer token authentication
        if 'oauth_key' in self.config['bitbucket'] and 'oauth_secret' in self.config['bitbucket']:
            self.bitbucket_client = BitbucketClient(
                workspace=self.config['bitbucket']['workspace'],
                repository=self.config['bitbucket']['repository'],
                oauth_key=self.config['bitbucket']['oauth_key'],
                oauth_secret=self.config['bitbucket']['oauth_secret']
            )
        else:
            self.bitbucket_client = BitbucketClient(
                workspace=self.config['bitbucket']['workspace'],
                repository=self.config['bitbucket']['repository'],
                token=self.config['bitbucket']['token']
            )
        
        self.github_client = GitHubClient(
            token=self.config['github']['token'],
            owner=self.config['github']['owner'],
            repository=self.config['github']['repository'],
            user_mapper=self.user_mapper
        )
        
        # Migration statistics
        self.stats = {
            'total_prs': 0,
            'open_prs': 0,
            'closed_prs': 0,
            'migrated_successfully': 0,
            'migration_failed': 0
        }
    
    def _enable_test_mode(self):
        """Enable test mode using test repository from config"""
        if not self.config.get('test_mode', {}).get('enabled'):
            self.logger.warning("Test mode requested but not enabled in config.yaml")
            self.logger.warning("Set test_mode.enabled=true and configure test_repo")
            sys.exit(1)
        
        test_repo = self.config.get('test_mode', {}).get('test_repo', {})
        if not test_repo.get('owner') or not test_repo.get('repository'):
            self.logger.error("Test mode enabled but test_repo not configured in config.yaml")
            sys.exit(1)
        
        # Override GitHub config with test repo
        self.config['github']['owner'] = test_repo['owner']
        self.config['github']['repository'] = test_repo['repository']
        
        self.logger.warning("\n" + "*" * 70)
        self.logger.warning(f"TEST MODE: PRs will be created in {test_repo['owner']}/{test_repo['repository']}")
        self.logger.warning("*" * 70 + "\n")
    
    def _load_config(self, config_file: str) -> dict:
        """Load configuration from YAML file"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            self.logger.error(f"Configuration file not found: {config_file}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"Error loading configuration: {e}")
            sys.exit(1)
    
    def validate_config(self) -> bool:
        """
        Validate that all required configuration is present
        
        Returns:
            True if valid, False otherwise
        """
        required_fields = {
            'bitbucket': ['workspace', 'repository'],
            'github': ['owner', 'repository', 'token']
        }
        
        missing_fields = []
        empty_fields = []
        
        for section, fields in required_fields.items():
            if section not in self.config:
                for field in fields:
                    missing_fields.append(f"{section}.{field}")
                continue
                
            for field in fields:
                value = self.config.get(section, {}).get(field)
                if value is None:
                    missing_fields.append(f"{section}.{field}")
                elif isinstance(value, str) and value.strip() == "":
                    empty_fields.append(f"{section}.{field}")
        
        if missing_fields:
            self.logger.error("Missing required configuration fields:")
            for field in missing_fields:
                self.logger.error(f"  - {field}")
        
        if empty_fields:
            self.logger.error("Empty configuration fields (need values):")
            for field in empty_fields:
                self.logger.error(f"  - {field}")
        
        # Check Bitbucket authentication: either OAuth OR token
        bb_config = self.config.get('bitbucket', {})
        has_oauth = ('oauth_key' in bb_config and bb_config['oauth_key'] and 
                     'oauth_secret' in bb_config and bb_config['oauth_secret'])
        has_token = 'token' in bb_config and bb_config['token']
        
        if not has_oauth and not has_token:
            self.logger.error("Bitbucket authentication missing:")
            self.logger.error("  Either provide 'oauth_key' and 'oauth_secret'")
            self.logger.error("  Or provide 'token' for Bearer authentication")
            return False
        
        return len(missing_fields) == 0 and len(empty_fields) == 0
    
    def fetch_all_prs(self) -> List[PullRequest]:
        """
        Fetch all pull requests from Bitbucket
        
        Returns:
            List of all PullRequest objects
        """
        all_prs = self.bitbucket_client.get_all_pull_requests()
        self.stats['total_prs'] = len(all_prs)
        
        # Categorize PRs
        open_prs = [pr for pr in all_prs if pr.is_open()]
        closed_prs = [pr for pr in all_prs if pr.is_closed()]
        
        self.stats['open_prs'] = len(open_prs)
        self.stats['closed_prs'] = len(closed_prs)
        
        return all_prs
    
    def separate_prs(self, all_prs: List[PullRequest]) -> Dict[str, List[PullRequest]]:
        """
        Separate PRs into open and closed categories
        
        Args:
            all_prs: List of all pull requests
            
        Returns:
            Dictionary with 'open' and 'closed' lists
        """
        return {
            'open': [pr for pr in all_prs if pr.is_open()],
            'closed': [pr for pr in all_prs if pr.is_closed()]
        }
    
    def log_closed_prs(self, closed_prs: List[PullRequest]):
        """
        Log all closed PRs
        
        Args:
            closed_prs: List of closed pull requests
        """
        for pr in closed_prs:
            self.pr_logger.log_closed_pr(pr)
    
    def migrate_open_prs(self, open_prs: List[PullRequest]):
        """
        Migrate all open PRs to GitHub
        
        Args:
            open_prs: List of open pull requests
        """
        if not open_prs:
            return
        
        for i, pr in enumerate(open_prs, 1):
            
            if self.dry_run:
                # Simulate migration without making changes
                self.stats['migrated_successfully'] += 1
                continue
            
            success, error_message = self.github_client.migrate_pull_request(pr)
            
            if success:
                self.stats['migrated_successfully'] += 1
            else:
                self.stats['migration_failed'] += 1
                self.pr_logger.log_failed_pr(
                    pr,
                    reason=error_message or "Migration failed",
                    error_details=f"Source: {pr.source_branch} -> Destination: {pr.destination_branch}"
                )
    
    def print_summary(self):
        """Print final migration summary"""
        summary = self.pr_logger.get_summary()
        
        self.logger.info("\n" + "=" * 70)
        self.logger.info("MIGRATION SUMMARY")
        self.logger.info("=" * 70)
        self.logger.info(f"Total PRs processed: {self.stats['total_prs']}")
        
        self.logger.info(f"\n📂 Open PRs:")
        self.logger.info(f"  - Total: {self.stats['open_prs']}")
        self.logger.info(f"  - ✅ Successfully migrated: {self.stats['migrated_successfully']}")
        self.logger.info(f"  - ❌ Failed: {self.stats['migration_failed']}")
        
        self.logger.info(f"\n📂 Closed PRs (Not Migrated - Logged):")
        self.logger.info(f"  - Total: {self.stats['closed_prs']}")
        self.logger.info(f"  - ✔️  Merged: {summary['merged_prs_count']}")
        self.logger.info(f"  - ✖️  Declined: {summary['declined_prs_count']}")
        self.logger.info(f"  - 🔄 Superseded: {summary['superseded_prs_count']}")
        
        self.logger.info(f"\n📄 Log Files:")
        self.logger.info(f"  - Closed PRs (merged/declined/superseded): {self.config['logging']['closed_pr_archive']}")
        
        if self.stats['migration_failed'] > 0:
            self.logger.info(f"  - Failed migrations: {self.config['logging']['failed_prs']}")
        
        self.logger.info("=" * 70)
    
    def run(self):
        """Execute the full migration process"""
        try:
            self.logger.info("\n" + "=" * 70)
            self.logger.info("BITBUCKET TO GITHUB PR MIGRATION")
            self.logger.info("=" * 70)
            
            # Configuration already validated in __init__
            
            # Fetch all PRs
            all_prs = self.fetch_all_prs()
            
            if not all_prs:
                return
            
            # Separate open and closed PRs
            categorized_prs = self.separate_prs(all_prs)
            
            # Log closed PRs
            if categorized_prs['closed']:
                self.log_closed_prs(categorized_prs['closed'])
            
            # Migrate open PRs
            if categorized_prs['open']:
                self.migrate_open_prs(categorized_prs['open'])
            else:
                self.logger.info("\nNo open PRs to migrate")
            
            # Print summary
            self.print_summary()
            
            self.logger.info(f"\nCompleted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        except KeyboardInterrupt:
            self.logger.warning("\n\nMigration interrupted by user")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"\nUnexpected error during migration: {e}", exc_info=True)
            sys.exit(1)


def main():
    """Main entry point"""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Migrate pull requests from Bitbucket to GitHub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test credentials (quick validation)
  python main.py --test-connection
  
  # Normal migration
  python main.py
  
  # Dry-run mode (no changes made)
  python main.py --dry-run
  
  # Test mode (use test repository)
  python main.py --test-mode
  
  # Dry-run with test mode
  python main.py --dry-run --test-mode
  
  # Custom config file
  python main.py --config custom_config.yaml
        """
    )
    
    parser.add_argument(
        '--test-connection',
        action='store_true',
        help='Test API credentials without fetching PRs (quick validation)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate migration without making any changes to GitHub'
    )
    
    parser.add_argument(
        '--test-mode',
        action='store_true',
        help='Use test repository from config.yaml (test_mode.test_repo)'
    )
    
    parser.add_argument(
        '--config',
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging()
    
    print("\n" + "=" * 70)
    print("  BITBUCKET TO GITHUB PR MIGRATION TOOL")
    if args.test_connection:
        print("  MODE: CONNECTION TEST")
    if args.dry_run:
        print("  MODE: DRY-RUN (No changes will be made)")
    if args.test_mode:
        print("  MODE: TEST (Using test repository)")
    print("=" * 70 + "\n")
    
    # Quick connection test mode
    if args.test_connection:
        test_credentials(args.config)
        return
    
    orchestrator = PRMigrationOrchestrator(
        config_file=args.config,
        dry_run=args.dry_run,
        test_mode=args.test_mode
    )
    orchestrator.run()


def test_credentials(config_file: str = "config.yaml"):
    """Test API credentials without full migration"""
    import yaml
    import requests
    from github import Github, GithubException
    
    logger = logging.getLogger(__name__)
    
    try:
        # Load config
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        logger.info("Testing Bitbucket credentials...")
        # Test Bitbucket
        bb_workspace = config['bitbucket']['workspace']
        bb_repo = config['bitbucket']['repository']
        
        # Support both OAuth 2.0 and Bearer token
        headers = {'Accept': 'application/json'}
        
        if 'oauth_key' in config['bitbucket'] and 'oauth_secret' in config['bitbucket']:
            # Use OAuth 2.0 client credentials flow
            oauth_key = config['bitbucket']['oauth_key']
            oauth_secret = config['bitbucket']['oauth_secret']
            logger.info(f"Using OAuth 2.0 client credentials (key: {oauth_key[:8]}...)")
            
            # Get access token
            token_response = requests.post(
                "https://bitbucket.org/site/oauth2/access_token",
                auth=(oauth_key, oauth_secret),
                data={'grant_type': 'client_credentials'}
            )
            
            if token_response.status_code != 200:
                logger.error(f"❌ Bitbucket: Failed to get OAuth token (status {token_response.status_code})")
                logger.error(f"   Check OAuth consumer credentials at: https://bitbucket.org/{bb_workspace}/workspace/settings/api")
                return
            
            token_data = token_response.json()
            access_token = token_data['access_token']
            expires_in = token_data.get('expires_in', 7200)
            logger.info(f"✅ OAuth token obtained (expires in {expires_in} seconds)")
            headers['Authorization'] = f'Bearer {access_token}'
        else:
            # Use Bearer token directly
            bb_token = config['bitbucket']['token']
            headers['Authorization'] = f'Bearer {bb_token}'
            logger.info("Using Bearer token authentication")
        
        # Simple API call to test auth
        test_url = f"https://api.bitbucket.org/2.0/repositories/{bb_workspace}/{bb_repo}"
        response = requests.get(test_url, headers=headers)
        
        if response.status_code == 200:
            logger.info(f"✅ Bitbucket: Successfully authenticated to {bb_workspace}/{bb_repo}")
        elif response.status_code == 401:
            logger.error(f"❌ Bitbucket: Authentication failed (401 Unauthorized)")
            if 'oauth_key' in config['bitbucket'] and 'oauth_secret' in config['bitbucket']:
                logger.error(f"   OAuth credentials are invalid or lack permissions")
                logger.error(f"   Check: https://bitbucket.org/{bb_workspace}/workspace/settings/api")
            else:
                logger.error(f"   Token is invalid or lacks permissions")
                logger.error(f"   Generate new token: https://bitbucket.org/account/settings/api-tokens/")
            return
        elif response.status_code == 404:
            logger.error(f"❌ Bitbucket: Repository not found (404)")
            logger.error(f"   Workspace: {bb_workspace}")
            logger.error(f"   Repository: {bb_repo}")
            return
        else:
            logger.error(f"❌ Bitbucket: Unexpected error (status {response.status_code})")
            return
        
        logger.info("\nTesting GitHub credentials...")
        # Test GitHub
        gh_token = config['github']['token']
        gh_owner = config['github']['owner']
        gh_repo = config['github']['repository']
        
        from github import Auth
        auth = Auth.Token(gh_token)
        github = Github(auth=auth)
        try:
            repo = github.get_repo(f"{gh_owner}/{gh_repo}")
            logger.info(f"✅ GitHub: Successfully authenticated to {gh_owner}/{gh_repo}")
            logger.info(f"   Repository: {repo.full_name}")
            logger.info(f"   Default branch: {repo.default_branch}")
        except GithubException as e:
            if e.status == 401:
                logger.error(f"❌ GitHub: Authentication failed (401 Unauthorized)")
                logger.error(f"   Token is invalid or expired")
                logger.error(f"   Generate new token: https://github.com/settings/tokens")
            elif e.status == 404:
                logger.error(f"❌ GitHub: Repository not found (404)")
                logger.error(f"   Owner: {gh_owner}")
                logger.error(f"   Repository: {gh_repo}")
            else:
                logger.error(f"❌ GitHub: Error {e.status} - {e.data.get('message', str(e))}")
            return
        
        logger.info("\n" + "=" * 70)
        logger.info("✅ CONNECTION TEST PASSED")
        logger.info("=" * 70)
        logger.info("Both Bitbucket and GitHub credentials are valid.")
        logger.info("You can now run the migration with: python main.py --dry-run")
        
    except Exception as e:
        logger.error(f"\n❌ Connection test failed: {e}")
        logger.error("Please check your config.yaml file")


if __name__ == "__main__":
    main()
