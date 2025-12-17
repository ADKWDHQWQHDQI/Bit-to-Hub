"""
Main application for Bitbucket to GitHub PR migration
"""
import sys
import logging
import yaml
import argparse
import os
import shutil
import getpass
from datetime import datetime
from typing import Dict, List, Optional
from tqdm import tqdm
from github import Github, Auth, GithubException
from clients import BitbucketClient, GitHubClient
from models import PullRequest
from utils import UserMapper, PRLogger


def validate_bitbucket_credentials(workspace, repository, auth_data):
    """Validate Bitbucket credentials by making a test API call"""
    import requests
    
    try:
        headers = {'Accept': 'application/json'}
        
        if 'oauth_key' in auth_data and 'oauth_secret' in auth_data:
            # Get OAuth token
            token_response = requests.post(
                "https://bitbucket.org/site/oauth2/access_token",
                auth=(auth_data['oauth_key'], auth_data['oauth_secret']),
                data={'grant_type': 'client_credentials'},
                timeout=10
            )
            
            if token_response.status_code != 200:
                return False, "Invalid OAuth credentials. Please check your Consumer Key and Secret."
            
            token_data = token_response.json()
            access_token = token_data['access_token']
            headers['Authorization'] = f'Bearer {access_token}'
        else:
            # Use Bearer token
            headers['Authorization'] = f'Bearer {auth_data["token"]}'
        
        # Test API call
        test_url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repository}"
        response = requests.get(test_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return True, "✓ Bitbucket credentials validated successfully"
        elif response.status_code == 401:
            return False, "Invalid credentials. Authentication failed."
        elif response.status_code == 404:
            return False, f"Repository '{workspace}/{repository}' not found. Please check workspace and repository names."
        else:
            return False, f"Unexpected error (HTTP {response.status_code}). Please check your credentials."
    
    except requests.exceptions.Timeout:
        return False, "Connection timeout. Please check your internet connection."
    except requests.exceptions.ConnectionError:
        return False, "Connection error. Please check your internet connection."
    except Exception as e:
        return False, f"Error validating credentials: {str(e)}"


def validate_github_credentials(owner, repository, token):
    """Validate GitHub credentials by making a test API call"""
    from github import Github, Auth, GithubException
    
    try:
        auth = Auth.Token(token)
        github = Github(auth=auth, timeout=10)
        repo = github.get_repo(f"{owner}/{repository}")
        
        return True, "✓ GitHub credentials validated successfully"
    
    except GithubException as e:
        if e.status == 401:
            return False, "Invalid GitHub token. Please check your Personal Access Token."
        elif e.status == 404:
            return False, f"Repository '{owner}/{repository}' not found. Please check owner and repository names."
        else:
            error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') and e.data else str(e)
            return False, f"GitHub API error: {error_msg}"
    except Exception as e:
        return False, f"Error validating credentials: {str(e)}"


def create_config_interactive():
    """
    Create config.yaml interactively by prompting user for credentials.
    This is called when config.yaml doesn't exist (first run).
    Validates credentials before saving configuration.
    """
    print("\n" + "=" * 70)
    print("  BITBUCKET TO GITHUB PR MIGRATION TOOL - FIRST RUN SETUP")
    print("=" * 70)
    print("\nNo config.yaml found. Let's set up your configuration.\n")
    
    config = {
        'bitbucket': {},
        'github': {},
        'logging': {
            'closed_pr_archive': './logs/closed_prs.json',
            'failed_prs': './logs/failed_prs.json',
            'migration_summary': './logs/migration_summary.log'
        },
        'migration_options': {
            'skip_commit_verification': False,
            'skip_prs_with_missing_branches': True,
            'create_closed_issues': True
        },
        'test_mode': {
            'enabled': False,
            'test_repo': {
                'owner': 'your-test-owner',
                'repository': 'your-test-repository'
            }
        }
    }
    
    # Bitbucket Configuration with validation
    print("=" * 70)
    print("BITBUCKET CONFIGURATION")
    print("=" * 70)
    
    bb_valid = False
    while not bb_valid:
        bb_workspace = input("Enter Bitbucket Workspace name: ").strip()
        bb_repo = input("Enter Bitbucket Repository name: ").strip()
        
        if not bb_workspace or not bb_repo:
            print("\n❌ Workspace and repository names cannot be empty. Please try again.\n")
            continue
        
        print("\nChoose Bitbucket authentication method:")
        print("  1. OAuth 2.0 (Key + Secret)")
        print("  2. Bearer Token")
        auth_choice = input("Enter choice (1 or 2): ").strip()
        
        config['bitbucket']['workspace'] = bb_workspace
        config['bitbucket']['repository'] = bb_repo
        
        if auth_choice == '1':
            bb_key = getpass.getpass("Enter Bitbucket OAuth Key: ").strip()
            bb_secret = getpass.getpass("Enter Bitbucket OAuth Secret: ").strip()
            
            if not bb_key or not bb_secret:
                print("\n❌ OAuth credentials cannot be empty. Please try again.\n")
                continue
            
            config['bitbucket']['oauth_key'] = bb_key
            config['bitbucket']['oauth_secret'] = bb_secret
            auth_data = {'oauth_key': bb_key, 'oauth_secret': bb_secret}
        else:
            bb_token = getpass.getpass("Enter Bitbucket Token: ").strip()
            
            if not bb_token:
                print("\n❌ Token cannot be empty. Please try again.\n")
                continue
            
            config['bitbucket']['token'] = bb_token
            auth_data = {'token': bb_token}
        
        # Validate Bitbucket credentials
        print("\n🔍 Validating Bitbucket credentials...")
        bb_valid, bb_message = validate_bitbucket_credentials(bb_workspace, bb_repo, auth_data)
        
        if bb_valid:
            print(f"✅ {bb_message}\n")
        else:
            print(f"\n❌ {bb_message}")
            print("Please try again.\n")
            # Clear invalid credentials
            if 'oauth_key' in config['bitbucket']:
                del config['bitbucket']['oauth_key']
                del config['bitbucket']['oauth_secret']
            if 'token' in config['bitbucket']:
                del config['bitbucket']['token']
    
    # GitHub Configuration with validation
    print("=" * 70)
    print("GITHUB CONFIGURATION")
    print("=" * 70)
    
    gh_valid = False
    while not gh_valid:
        gh_owner = input("Enter GitHub Owner/Organization: ").strip()
        gh_repo = input("Enter GitHub Repository name: ").strip()
        gh_token = getpass.getpass("Enter GitHub Personal Access Token: ").strip()
        
        if not gh_owner or not gh_repo or not gh_token:
            print("\n❌ Owner, repository, and token cannot be empty. Please try again.\n")
            continue
        
        # Validate GitHub credentials
        print("\n🔍 Validating GitHub credentials...")
        gh_valid, gh_message = validate_github_credentials(gh_owner, gh_repo, gh_token)
        
        if gh_valid:
            print(f"✅ {gh_message}\n")
            config['github']['owner'] = gh_owner
            config['github']['repository'] = gh_repo
            config['github']['token'] = gh_token
        else:
            print(f"\n❌ {gh_message}")
            print("Please try again.\n")
    
    # Save configuration
    with open('config.yaml', 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    print("=" * 70)
    print("✅ Configuration saved to config.yaml")
    print("=" * 70)
    
    # Create user_mapping.yaml if it doesn't exist
    if not os.path.exists('user_mapping.yaml'):
        if os.path.exists('user_mapping.template.yaml'):
            shutil.copy('user_mapping.template.yaml', 'user_mapping.yaml')
            print("✅ user_mapping.yaml created from template")
            print("   Edit this file to map Bitbucket users to GitHub users")
        else:
            # Create basic user_mapping.yaml
            with open('user_mapping.yaml', 'w', encoding='utf-8') as f:
                f.write("# Bitbucket Username -> GitHub Username\n")
                f.write("# Example:\n")
                f.write("# john.doe: johndoe-github\n")
            print("✅ user_mapping.yaml created")
    
    print("\n✅ Setup complete! You can now run the migration.")
    print("=" * 70 + "\n")
    return config


# Configure logging
def setup_logging(log_file: str = './logs/migration_summary.log', verbose: bool = False):
    """Setup logging configuration for production-grade output"""
    # Ensure logs directory exists
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    # File logging - detailed technical logs
    file_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(file_format))
    
    # Console logging - production-grade user-friendly output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console_format = '%(message)s'
    console_handler.setFormatter(logging.Formatter(console_format))
    
    # Configure root logger
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[file_handler, console_handler]
    )
    
    # Suppress verbose output from third-party libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('github').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)


class PRMigrationOrchestrator:
    """Orchestrates the PR migration process"""
    
    def __init__(self, config_file: str = "config.yaml", dry_run: bool = False, test_mode: bool = False, pr_numbers: Optional[List[int]] = None):
        """
        Initialize the migration orchestrator
        
        Args:
            config_file: Path to configuration YAML file
            dry_run: If True, no changes will be made to GitHub
            test_mode: If True, use test repository from config
            pr_numbers: Optional list of specific PR numbers to migrate
        """
        self.logger = logging.getLogger(__name__)
        self.config = self._load_config(config_file)
        self.dry_run = dry_run
        self.test_mode = test_mode
        self.pr_numbers = pr_numbers
        
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
        bitbucket_token: Optional[str] = None
        if 'oauth_key' in self.config['bitbucket'] and 'oauth_secret' in self.config['bitbucket']:
            self.bitbucket_client = BitbucketClient(
                workspace=self.config['bitbucket']['workspace'],
                repository=self.config['bitbucket']['repository'],
                oauth_key=self.config['bitbucket']['oauth_key'],
                oauth_secret=self.config['bitbucket']['oauth_secret']
            )
            # Get OAuth access token for image migration
            bitbucket_token = self.bitbucket_client.access_token
        else:
            self.bitbucket_client = BitbucketClient(
                workspace=self.config['bitbucket']['workspace'],
                repository=self.config['bitbucket']['repository'],
                token=self.config['bitbucket']['token']
            )
            bitbucket_token = self.config['bitbucket']['token']
        
        # Get migration options (with defaults)
        migration_options = self.config.get('migration_options', {})
        skip_commit_verification = migration_options.get('skip_commit_verification', False)
        skip_prs_with_missing_branches = migration_options.get('skip_prs_with_missing_branches', False)
        self.create_closed_issues_enabled = migration_options.get('create_closed_issues', True)  # Default: True
        
        self.github_client = GitHubClient(
            token=self.config['github']['token'],
            owner=self.config['github']['owner'],
            repository=self.config['github']['repository'],
            bitbucket_workspace=self.config['bitbucket']['workspace'],
            bitbucket_repo=self.config['bitbucket']['repository'],
            bitbucket_token=bitbucket_token,
            skip_commit_verification=skip_commit_verification,
            skip_prs_with_missing_branches=skip_prs_with_missing_branches
        )
        
        # Migration statistics
        self.stats = {
            'total_prs': 0,
            'open_prs': 0,
            'closed_prs': 0,
            'migrated_successfully': 0,
            'migration_failed': 0,
            'closed_issues_created': 0,
            'closed_issues_failed': 0
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
            # Config doesn't exist - this should be handled by main() before creating orchestrator
            self.logger.error(f"Configuration file not found: {config_file}")
            self.logger.error("Please run the tool to create configuration interactively.")
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
    
    def _validate_credentials(self) -> bool:
        """
        Validate API credentials for both Bitbucket and GitHub
        
        Returns:
            True if all credentials are valid, False otherwise
        """
        import requests
        from github import GithubException
        
        # Validate Bitbucket credentials
        try:
            print("   • Testing Bitbucket connection...")
            
            # Support both OAuth 2.0 and Bearer token
            headers = {'Accept': 'application/json'}
            bb_workspace = self.config['bitbucket']['workspace']
            bb_repo = self.config['bitbucket']['repository']
            
            if 'oauth_key' in self.config['bitbucket'] and 'oauth_secret' in self.config['bitbucket']:
                # Use OAuth 2.0 client credentials flow
                oauth_key = self.config['bitbucket']['oauth_key']
                oauth_secret = self.config['bitbucket']['oauth_secret']
                
                # Get access token
                token_response = requests.post(
                    "https://bitbucket.org/site/oauth2/access_token",
                    auth=(oauth_key, oauth_secret),
                    data={'grant_type': 'client_credentials'},
                    timeout=10
                )
                
                if token_response.status_code != 200:
                    print(f"     ❌ Bitbucket OAuth authentication failed")
                    print(f"     Check OAuth consumer credentials at:")
                    print(f"     https://bitbucket.org/{bb_workspace}/workspace/settings/api")
                    return False
                
                token_data = token_response.json()
                access_token = token_data['access_token']
                headers['Authorization'] = f'Bearer {access_token}'
            else:
                # Use Bearer token directly
                bb_token = self.config['bitbucket']['token']
                headers['Authorization'] = f'Bearer {bb_token}'
            
            # Test API call to verify authentication
            test_url = f"https://api.bitbucket.org/2.0/repositories/{bb_workspace}/{bb_repo}"
            response = requests.get(test_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                print(f"     ✓ Bitbucket: Connected to {bb_workspace}/{bb_repo}")
            elif response.status_code == 401:
                print(f"     ❌ Bitbucket: Authentication failed (401 Unauthorized)")
                print(f"     Token is invalid or lacks permissions")
                return False
            elif response.status_code == 404:
                print(f"     ❌ Bitbucket: Repository not found")
                print(f"     Workspace: {bb_workspace}, Repository: {bb_repo}")
                return False
            else:
                print(f"     ❌ Bitbucket: Unexpected error (HTTP {response.status_code})")
                return False
                
        except requests.exceptions.Timeout:
            print(f"     ❌ Bitbucket: Connection timeout")
            return False
        except requests.exceptions.ConnectionError:
            print(f"     ❌ Bitbucket: Connection error. Check your internet connection")
            return False
        except Exception as e:
            print(f"     ❌ Bitbucket: {str(e)}")
            return False
        
        # Validate GitHub credentials
        gh_token = self.config['github']['token']
        gh_owner = self.config['github']['owner']
        gh_repo = self.config['github']['repository']
        
        try:
            print("   • Testing GitHub connection...")
            
            from github import Auth
            auth = Auth.Token(gh_token)
            github = Github(auth=auth, timeout=10)
            repo = github.get_repo(f"{gh_owner}/{gh_repo}")
            
            print(f"     ✓ GitHub: Connected to {gh_owner}/{gh_repo}")
            
        except GithubException as e:
            if e.status == 401:
                print(f"     ❌ GitHub: Authentication failed (401 Unauthorized)")
                print(f"     Token is invalid or expired")
                print(f"     Generate new token: https://github.com/settings/tokens")
            elif e.status == 404:
                print(f"     ❌ GitHub: Repository not found")
                print(f"     Owner: {gh_owner}, Repository: {gh_repo}")
            else:
                error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') and e.data else str(e)
                print(f"     ❌ GitHub: {error_msg}")
            return False
        except Exception as e:
            print(f"     ❌ GitHub: {str(e)}")
            return False
        
        return True
    
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
    
    def fetch_specific_prs(self, pr_numbers: List[int]) -> List[PullRequest]:
        """
        Fetch specific pull requests by their numbers
        
        Args:
            pr_numbers: List of PR numbers to fetch
            
        Returns:
            List of PullRequest objects
        """
        prs = []
        for pr_num in pr_numbers:
            try:
                pr = self.bitbucket_client.get_pull_request(pr_num)
                if pr:
                    prs.append(pr)
                    self.logger.info(f"  ✓ Fetched PR #{pr_num}: {pr.title}")
                else:
                    self.logger.warning(f"  ✗ PR #{pr_num} not found")
            except Exception as e:
                self.logger.error(f"  ✗ Failed to fetch PR #{pr_num}: {e}")
        
        self.stats['total_prs'] = len(prs)
        
        # Categorize PRs
        open_prs = [pr for pr in prs if pr.is_open()]
        closed_prs = [pr for pr in prs if pr.is_closed()]
        
        self.stats['open_prs'] = len(open_prs)
        self.stats['closed_prs'] = len(closed_prs)
        
        return prs
    
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
        Log all closed PRs to JSON
        
        Args:
            closed_prs: List of closed pull requests
        """
        for pr in closed_prs:
            self.pr_logger.log_closed_pr(pr)
    
    def create_closed_issues(self, closed_prs: List[PullRequest]):
        """
        Create closed issues in GitHub for closed Bitbucket PRs
        
        Args:
            closed_prs: List of closed pull requests
        """
        if not closed_prs:
            return
        
        # Check if feature is enabled
        if not self.create_closed_issues_enabled:
            print(f"\n⏭️  Skipping closed issues (disabled in config)")
            print(f"   {len(closed_prs)} closed PRs logged to: {self.config['logging']['closed_pr_archive']}")
            return
        
        print(f"\n📝 Creating GitHub issues for {len(closed_prs)} closed PRs...")
        
        # Progress bar for closed issues
        with tqdm(total=len(closed_prs), desc="Creating issues", unit="issue", ncols=100, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]') as pbar:
            for pr in closed_prs:
                # Update description with current PR
                pbar.set_postfix_str(f"PR #{pr.id}: {pr.title[:40]}..." if len(pr.title) > 40 else f"PR #{pr.id}: {pr.title}")
                
                if self.dry_run:
                    self.stats['closed_issues_created'] += 1
                    pbar.update(1)
                    continue
                
                success, error_message = self.github_client.create_closed_issue(pr)
                
                if success:
                    self.stats['closed_issues_created'] += 1
                else:
                    self.stats['closed_issues_failed'] += 1
                    tqdm.write(f"   ⚠️  Failed: PR #{pr.id} - {error_message}")
                    self.pr_logger.log_failed_pr(
                        pr,
                        reason=f"Failed to create closed issue: {error_message}",
                        error_details=f"State: {pr.state}"
                    )
                
                pbar.update(1)
        
        print(f"   ✓ Created {self.stats['closed_issues_created']} issues")
        if self.stats['closed_issues_failed'] > 0:
            print(f"   ⚠️  Failed: {self.stats['closed_issues_failed']} issues")

    
    def migrate_open_prs(self, open_prs: List[PullRequest]):
        """
        Migrate all open PRs to GitHub
        
        Args:
            open_prs: List of open pull requests
        """
        if not open_prs:
            return
        
        print(f"\n🔄 Migrating {len(open_prs)} open PRs...")
        
        # Progress bar for open PRs migration
        with tqdm(total=len(open_prs), desc="Migrating PRs", unit="PR", ncols=100, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]') as pbar:
            for pr in open_prs:
                # Update description with current PR
                pbar.set_postfix_str(f"PR #{pr.id}: {pr.title[:40]}..." if len(pr.title) > 40 else f"PR #{pr.id}: {pr.title}")
                
                if self.dry_run:
                    # Simulate migration without making changes
                    self.stats['migrated_successfully'] += 1
                    pbar.update(1)
                    continue
                
                success, error_message = self.github_client.migrate_pull_request(pr)
                
                if success:
                    self.stats['migrated_successfully'] += 1
                else:
                    self.stats['migration_failed'] += 1
                    tqdm.write(f"   ⚠️  Failed: PR #{pr.id} - {error_message}")
                    self.pr_logger.log_failed_pr(
                        pr,
                        reason=error_message or "Migration failed",
                        error_details=f"Source: {pr.source_branch} -> Destination: {pr.destination_branch}"
                    )
                
                pbar.update(1)
        
        print(f"   ✓ Migrated {self.stats['migrated_successfully']} PRs successfully")
        if self.stats['migration_failed'] > 0:
            print(f"   ⚠️  Failed: {self.stats['migration_failed']} PRs")
    
    def print_summary(self):
        """Print final migration summary"""
        summary = self.pr_logger.get_summary()
        
        print("\n" + "=" * 70)
        print("                        MIGRATION SUMMARY")
        print("=" * 70)
        print(f"\n📊 Total PRs Processed: {self.stats['total_prs']}")
        
        print(f"\n📂 OPEN PRs ({self.stats['open_prs']} total)")
        print(f"   ✅ Successfully migrated: {self.stats['migrated_successfully']}")
        if self.stats['migration_failed'] > 0:
            print(f"   ❌ Failed: {self.stats['migration_failed']}")
        
        print(f"\n📂 CLOSED PRs ({self.stats['closed_prs']} total)")
        print(f"   ✔️  Merged: {summary['merged_prs_count']}")
        print(f"   ✖️  Declined: {summary['declined_prs_count']}")
        if summary['superseded_prs_count'] > 0:
            print(f"   🔄 Superseded: {summary['superseded_prs_count']}")
        
        if self.create_closed_issues_enabled:
            print(f"\n   📝 GitHub Issues Created: {self.stats['closed_issues_created']}")
            if self.stats['closed_issues_failed'] > 0:
                print(f"   ⚠️  Issues Failed: {self.stats['closed_issues_failed']}")
        
        print(f"\n📄 Detailed Logs:")
        print(f"   • Full log: {self.config['logging']['migration_summary']}")
        print(f"   • Closed PRs: {self.config['logging']['closed_pr_archive']}")
        
        if self.stats['migration_failed'] > 0 or self.stats['closed_issues_failed'] > 0:
            print(f"   • Failed migrations: {self.config['logging']['failed_prs']}")
        
        print("\n" + "=" * 70)
    
    def run(self):
        """Execute the full migration process"""
        try:
            print("\n" + "=" * 70)
            print("          BITBUCKET TO GITHUB PR MIGRATION TOOL")
            print("=" * 70)
            
            # Configuration already validated in __init__
            
            # Validate credentials before proceeding
            print("\n🔐 Validating credentials...")
            if not self._validate_credentials():
                print("\n❌ Credential validation failed. Please check your configuration.")
                print("=" * 70 + "\n")
                sys.exit(1)
            print("   ✓ All credentials validated successfully\n")
            
            # Fetch PRs (all or specific numbers)
            if self.pr_numbers:
                print(f"\n🔍 Fetching specific PRs: {', '.join(map(str, self.pr_numbers))}")
                all_prs = self.fetch_specific_prs(self.pr_numbers)
            else:
                print(f"\n🔍 Fetching pull requests from Bitbucket...")
                print(f"   Repository: {self.bitbucket_client.workspace}/{self.bitbucket_client.repository}")
                all_prs = self.fetch_all_prs()
            
            if not all_prs:
                print("\n⚠️  No pull requests found to migrate")
                return
            
            print(f"   ✓ Found {len(all_prs)} PRs")
            
            # Separate open and closed PRs
            categorized_prs = self.separate_prs(all_prs)
            
            open_count = len(categorized_prs['open'])
            closed_count = len(categorized_prs['closed'])
            
            print(f"\n📊 PR Breakdown:")
            print(f"   • Open PRs: {open_count}")
            print(f"   • Closed PRs: {closed_count}")
            
            # Log closed PRs (always keep this for record-keeping)
            if categorized_prs['closed']:
                print(f"\n📋 Archiving {closed_count} closed PRs...")
                self.log_closed_prs(categorized_prs['closed'])
                print(f"   ✓ Saved to: {self.config['logging']['closed_pr_archive']}")
            
            # Create closed issues in GitHub
            if categorized_prs['closed']:
                self.create_closed_issues(categorized_prs['closed'])
            
            # Migrate open PRs
            if categorized_prs['open']:
                self.migrate_open_prs(categorized_prs['open'])
            else:
                print("\n✓ No open PRs to migrate")
            
            # Print summary
            self.print_summary()
            
            print(f"\n✓ Migration completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("=" * 70 + "\n")
        
        except KeyboardInterrupt:
            print("\n\n⚠️  Migration interrupted by user")
            sys.exit(1)
        except Exception as e:
            print(f"\n❌ Unexpected error during migration: {e}")
            self.logger.error(f"Unexpected error during migration: {e}", exc_info=True)
            print(f"\nCheck logs for details: {self.config['logging']['migration_summary']}")
            sys.exit(1)


def main():
    """Main entry point"""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Migrate pull requests from Bitbucket to GitHub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Test credentials (quick validation)
  python main.py --test-connection
  
  # Migrate specific PR
  python main.py --pr-numbers 13
  
  # Migrate multiple specific PRs
  python main.py --pr-numbers 13,14,15
  
  # Dry-run for specific PR
  python main.py --pr-numbers 13 --dry-run
  
  # Normal migration (all PRs)
  python main.py
  
  # Dry-run mode (no changes made)
  python main.py --dry-run
  
  # Test mode (use test repository)
  python main.py --test-mode
  
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
    
    parser.add_argument(
        '--pr-numbers',
        type=str,
        help='Comma-separated list of PR numbers to migrate (e.g., "13" or "13,14,15")'
    )
    
    args = parser.parse_args()
    
    # Check if config exists - if not, create it interactively
    if not os.path.exists(args.config):
        create_config_interactive()
    
    # Setup logging (verbose mode for debugging)
    verbose = os.getenv('VERBOSE', '').lower() in ('true', '1', 'yes')
    setup_logging(verbose=verbose)
    
    # Show mode indicators
    if args.test_connection:
        print("\n" + "=" * 70)
        print("          CONNECTION TEST MODE")
        print("=" * 70)
    elif args.dry_run:
        print("\n" + "=" * 70)
        print("          DRY-RUN MODE (No changes will be made)")
        print("=" * 70)
    elif args.test_mode:
        print("\n" + "=" * 70)
        print("          TEST MODE (Using test repository)")
        print("=" * 70)
    
    # Quick connection test mode
    if args.test_connection:
        test_credentials(args.config)
        return
    
    # Parse PR numbers if provided
    pr_numbers = None
    if args.pr_numbers:
        try:
            pr_numbers = [int(num.strip()) for num in args.pr_numbers.split(',')]
        except ValueError:
            logger = logging.getLogger(__name__)
            logger.error(f"Invalid PR numbers format: {args.pr_numbers}")
            logger.error("Expected format: --pr-numbers 13 or --pr-numbers 13,14,15")
            return
    
    orchestrator = PRMigrationOrchestrator(
        config_file=args.config,
        dry_run=args.dry_run,
        test_mode=args.test_mode,
        pr_numbers=pr_numbers
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
