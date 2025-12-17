# Bitbucket to GitHub PR Migration Tool

A powerful tool to migrate Pull Requests (PRs) from Bitbucket to GitHub, preserving comments, reviews, tasks, and commit history.

## 🚀 Features

- **Audit Mode**: Comprehensive PR analysis with detailed statistics before migration
- **Complete PR Migration**: Migrates open PRs with full content preservation
- **Comment Preservation**: Maintains all PR comments, including nested replies
- **Review History**: Preserves reviewer information and approval status
- **Task Migration**: Migrates inline tasks and their status
- **Commit Verification**: Validates that all commits exist in target repository
- **Closed PR Handling**: Creates GitHub issues for closed/merged PRs for historical reference
- **User Mapping**: Maps Bitbucket users to GitHub users
- **Image Migration**: Automatically uploads and migrates embedded images
- **Credential Validation**: Tests API credentials before starting migration
- **Progress Tracking**: Real-time progress bars and detailed logging
- **Flexible Authentication**: Supports both OAuth 2.0 and Bearer token for Bitbucket

## 📋 Prerequisites

- Python 3.8 or higher
- Bitbucket API credentials (OAuth Consumer or App Password)
- GitHub Personal Access Token with `repo` scope
- Both repositories must exist and be accessible

## 🔧 Installation

### Option 1: Using the Standalone Executable (Recommended for Non-Developers)

1. Download the latest release from the [Releases](https://github.com/ADKWDHQWQHDQI/Bit-to-Hub/releases) page
2. Extract the zip file
3. Run `PRMigrationTool.exe`
4. Follow the interactive setup to enter your credentials

### Option 2: From Source

1. Clone the repository:

```bash
git clone https://github.com/ADKWDHQWQHDQI/Bit-to-Hub.git
cd Bit-to-Hub
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create configuration files:

```bash
cp config.template.yaml config.yaml
cp user_mapping.template.yaml user_mapping.yaml
```

4. Edit `config.yaml` with your credentials and repository details

## ⚙️ Configuration

### Bitbucket Setup

**Option 1: OAuth 2.0 (Recommended)**

1. Go to your Bitbucket workspace settings
2. Navigate to OAuth consumers: `https://bitbucket.org/{workspace}/workspace/settings/api`
3. Create a new consumer with `Read` permissions for repositories and pull requests
4. Copy the Key and Secret to `config.yaml`

**Option 2: App Password**

1. Go to Bitbucket account settings: `https://bitbucket.org/account/settings/api-tokens/`
2. Create an App Password with `Pull requests: Read` permission
3. Copy the token to `config.yaml`

### GitHub Setup

1. Go to GitHub settings: `https://github.com/settings/tokens`
2. Generate a Personal Access Token (classic) with `repo` scope
3. Copy the token to `config.yaml`

### User Mapping (Optional)

Map Bitbucket users to GitHub users in `user_mapping.yaml`:

```yaml
bitbucket_user1: github_user1
bitbucket_user2: github_user2
```

## 🎯 Usage

### Audit Mode (Recommended First Step)

```bash
# Analyze PRs and show comprehensive statistics
python main.py --audit
```

This mode will:

- ✅ Validate your credentials
- 📊 Show detailed PR statistics (count, types, comments, images, participants)
- 📈 Analyze migration complexity
- 💡 Provide recommendations
- ⚡ No changes made to any repository

### Basic Migration

```bash
# Test credentials first
python main.py --test-connection

# Dry run (no changes made)
python main.py --dry-run

# Full migration
python main.py
```

### Migrate Specific PRs

```bash
# Migrate a single PR
python main.py --pr-numbers 13

# Migrate multiple PRs
python main.py --pr-numbers 13,14,15
```

### Test Mode

```bash
# Use test repository (configured in config.yaml)
python main.py --test-mode
```

## 📊 Migration Process

1. **Credential Validation**: Tests Bitbucket and GitHub API access
2. **PR Fetching**: Retrieves all PRs from Bitbucket
3. **Closed PRs**: Archives closed PRs and creates GitHub issues (optional)
4. **Open PRs**: Migrates open PRs with full content
   - Creates PR with title and description
   - Migrates all comments (including nested replies)
   - Adds reviewer information
   - Migrates inline tasks
   - Verifies commit history

## 📝 Configuration Options

```yaml
migration_options:
  skip_commit_verification: false # Skip checking if commits exist
  skip_prs_with_missing_branches: true # Skip PRs with missing source branches
  create_closed_issues: true # Create issues for closed PRs
```

## 🔨 Building Standalone Executable

```bash
# Install build dependencies
pip install -r build_requirements.txt

# Build executable
python build_exe.py
```

The executable will be created in `client_distribution/PRMigrationTool.exe`

## 📂 Project Structure

```
bitbucket-github-pr-migration/
├── clients/                  # API clients
│   ├── bitbucket_client.py  # Bitbucket API wrapper
│   └── github_client.py     # GitHub API wrapper
├── models/                   # Data models
│   └── pr_model.py          # PR, Comment, Review models
├── utils/                    # Utility modules
│   ├── user_mapper.py       # User mapping logic
│   ├── pr_logger.py         # Logging utilities
│   ├── markdown_converter.py # Markdown conversion
│   └── image_migrator.py    # Image migration
├── main.py                   # Main application
├── config.template.yaml      # Config template
├── user_mapping.template.yaml # User mapping template
└── requirements.txt          # Dependencies
```

## 🐛 Troubleshooting

### Common Issues

**"No commit found for SHA"**

- The repository may have been rebased/squashed during migration
- Solution: Set `skip_commit_verification: true` in config.yaml

**"Source branch does not exist"**

- The branch was deleted in GitHub
- Solution: Already handled by default with `skip_prs_with_missing_branches: true`

**"PR already exists"**

- A PR with the same head and base branch already exists
- Solution: Close or rename the existing PR

**"No mapping found for Bitbucket user"**

- User not found in user_mapping.yaml
- Solution: Add the mapping or the tool will use the Bitbucket username

## 📄 License

MIT License - See [LICENSE](LICENSE) file for details

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📞 Support

For issues and questions, please open an issue on GitHub.

## 📌 Version

**Current Version**: 1.0.0
**Release Date**: December 17, 2025

## ✨ Features in v1.0

- Initial release with full PR migration capabilities
- Credential validation before migration
- Support for OAuth 2.0 and Bearer token authentication
- Complete comment and review preservation
- Image migration support
- Progress tracking and detailed logging
