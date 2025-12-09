# Bitbucket to GitHub Pull Request Migration Tool

A Python console application for migrating pull requests from Bitbucket to GitHub, with comprehensive logging, user mapping, and advanced safety features.

## 🎯 Features

### Core Features

- ✅ **List all PRs** from Bitbucket with complete metadata
- ✅ **Migrate open PRs** to GitHub automatically
- ✅ **Separate logging** for closed PRs by type (merged, declined, superseded)
- ✅ **User mapping** from Bitbucket to GitHub usernames
- ✅ **Comment migration** with original author attribution
- ✅ **Reviewer assignment** with fallback for unmapped users
- ✅ **Error handling** with detailed failure logging

### Advanced Features (New!)

- 🆕 **Dry-run mode** - Test without making changes
- 🆕 **Test repository mode** - Migrate to test repo first
- 🆕 **Commit validation** - Verify commits exist before creating PRs
- 🆕 **Fork PR support** - Handle cross-repo PRs correctly
- 🆕 **Automatic retries** - Exponential backoff for rate limits
- 🆕 **CLI interface** - Flexible command-line options
- 🆕 **Package installation** - Install as system command

## 📋 Requirements

- Python 3.8+
- Bitbucket Cloud account with API Token
- GitHub account with Personal Access Token
- Repository and branches already migrated to GitHub

## 🚀 Quick Start

### 1. Installation

```bash
# Create virtual environment (recommended)
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Install the package
pip install -e .

# Or install dependencies only
pip install -r requirements.txt
```

### 2. Configuration

Edit `config.yaml` with your details:

```yaml
bitbucket:
  workspace: "your-workspace"
  repository: "your-repo"
  token: "your-bitbucket-api-token"

github:
  owner: "github-org-or-username"
  repository: "your-repo"
  token: "your-github-token"

logging:
  closed_pr_archive: "./logs/closed_pr_archive.json"
  failed_prs: "./logs/failed_prs.json"
  migration_summary: "./logs/migration_summary.log"

# Optional: Test mode
test_mode:
  enabled: false
  test_repo:
    owner: "your-test-org"
    repository: "test-repo"
```

### 3. User Mapping

Edit `user_mapping.yaml`:

```yaml
# Map Bitbucket users to GitHub users
bitbucket_user1: github_user1
john.doe@company.com: johndoe-github
```

### 4. Run Migration

```bash
# Recommended: Start with dry-run
python main.py --dry-run

# Test on test repository
python main.py --test-mode

# Production migration
python main.py
```

## 🔐 Authentication Setup

### Bitbucket API Token

1. Go to [Bitbucket API Tokens](https://bitbucket.org/account/settings/api-tokens/)
2. Click "Create API token"
3. Grant permissions:
   - ✅ Repositories: Read
   - ✅ Pull requests: Read
4. Copy the generated token

**Note:** As of September 2025, Bitbucket uses API tokens instead of app passwords.

### GitHub Personal Access Token

1. Go to [GitHub Token Settings](https://github.com/settings/tokens)
2. Click "Generate new token (classic)"
3. Grant scopes:
   - ✅ `repo` (Full control of private repositories)
4. Copy the generated token

## 📖 Usage

### Command-Line Interface

```bash
# View all options
python main.py --help

# Dry-run mode (recommended first step)
python main.py --dry-run

# Test mode (use test repository)
python main.py --test-mode

# Combine modes
python main.py --dry-run --test-mode

# Custom config file
python main.py --config custom_config.yaml

# Normal migration
python main.py
```

### What Each Mode Does

#### Dry-Run Mode (`--dry-run`)

- ✅ Fetches all PRs from Bitbucket
- ✅ Validates configuration
- ✅ Checks branches and commits
- ✅ Shows what would be migrated
- ❌ Does NOT create PRs on GitHub

**Perfect for:** First-time testing, validating configuration

#### Test Mode (`--test-mode`)

- ✅ Creates PRs in test repository (from config)
- ✅ Safe experimentation
- ✅ Full migration workflow

**Perfect for:** Training, testing entire process safely

#### Production Mode (no flags)

- ✅ Creates PRs in production repository
- ✅ Actual migration

**Perfect for:** Final migration after testing

### Recommended Workflow

```bash
# Step 1: Validate configuration
python main.py --dry-run

# Step 2: Test on test repository
python main.py --test-mode

# Step 3: Final validation
python main.py --dry-run

# Step 4: Execute production migration
python main.py
```

The tool will:

1. **Fetch all PRs** from Bitbucket
2. **Categorize** them as open or closed
3. **Log closed PRs** separately by type:
   - `logs/closed_pr_archive_merged.json`
   - `logs/closed_pr_archive_declined.json`
   - `logs/closed_pr_archive_superseded.json`
4. **Migrate open PRs** to GitHub with:
   - Original title and description
   - Author attribution
   - Comments with author prefixes
   - Reviewers (mapped users)
5. **Log failed migrations** to `logs/failed_prs.json`

## 📂 Output Structure

```
logs/
├── migration_summary.log           # Detailed console output
├── closed_pr_archive.json          # All closed PRs
├── closed_pr_archive_merged.json   # Merged PRs only
├── closed_pr_archive_declined.json # Declined PRs only
├── closed_pr_archive_superseded.json # Superseded PRs only
└── failed_prs.json                 # Failed open PR migrations
```

## 📊 Log File Format

### Closed PR Archive

```json
[
  {
    "id": 123,
    "title": "Add new feature",
    "state": "MERGED",
    "author": "john.doe",
    "source_branch": "feature/new-feature",
    "destination_branch": "main",
    "created_date": "2025-01-15T10:30:00",
    "closed_date": "2025-01-16T14:20:00",
    "merge_commit": "abc123def456",
    "comments": [...],
    "reviewers": [...],
    "commits": ["sha1", "sha2"],
    "logged_at": "2025-12-08T15:45:00",
    "reason_not_migrated": "PR is MERGED - Only OPEN PRs are migrated"
  }
]
```

### Failed PR Log

```json
[
  {
    "pr_id": 45,
    "title": "Update dependencies",
    "reason": "Source branch 'feature/update' does not exist in GitHub",
    "error_details": "Source: feature/update -> Destination: main",
    "source_branch": "feature/update",
    "destination_branch": "main",
    "author": "jane.smith",
    "created_date": "2025-02-01T09:00:00",
    "failed_at": "2025-12-08T15:50:00"
  }
]
```

## 🔧 Configuration Options

### config.yaml

| Section     | Field               | Description                    |
| ----------- | ------------------- | ------------------------------ |
| `bitbucket` | `workspace`         | Bitbucket workspace name       |
| `bitbucket` | `repository`        | Repository name                |
| `bitbucket` | `token`             | Bitbucket API token            |
| `github`    | `owner`             | GitHub org or username         |
| `github`    | `repository`        | Repository name                |
| `github`    | `token`             | GitHub personal access token   |
| `logging`   | `closed_pr_archive` | Path for closed PR logs        |
| `logging`   | `failed_prs`        | Path for failed migration logs |

### user_mapping.yaml

Map Bitbucket users to GitHub users:

```yaml
# Format: bitbucket_user: github_user
john.doe: johndoe-github
jane.smith@company.com: janesmith
bob123: bob-wilson
```

**Important Notes:**

- Unmapped PR authors are mentioned in PR body
- Unmapped reviewers are logged in a comment
- Unmapped comment authors are prefixed in comments

## ⚠️ Important Considerations

### What Gets Migrated

✅ **Open PRs:**

- Title and description
- Source and destination branches
- PR author (attributed in body)
- Comments with author attribution
- Reviewers (if mapped)

❌ **Not Migrated:**

- Closed PRs (merged, declined, superseded)
- Build/CI status checks
- Inline code review comments (converted to general comments)
- Approval status (reviewers added without approval)

### Limitations

1. **GitHub API Limitations:**

   - PRs must be created as "open"
   - Cannot impersonate users (all PRs created by token owner)
   - Cannot set PR creation date (uses current timestamp)

2. **Branch Requirements:**

   - Branches must exist in GitHub before migration
   - Branch names must match exactly

3. **User Mapping:**
   - Unmapped users mentioned by Bitbucket name
   - Manual assignment may be needed for unmapped reviewers

## 🐛 Troubleshooting

### Issue: "Branch does not exist in GitHub"

**Solution:** Ensure all branches from Bitbucket are pushed to GitHub before migration.

### Issue: "GitHub API error: 422"

**Solution:**

- Check if a PR already exists with same head/base
- Verify branch names are exact matches
- Ensure token has `repo` scope

### Issue: "No user mappings found"

**Solution:** Add mappings to `user_mapping.yaml` file.

### Issue: "Failed to add reviewers"

**Solution:**

- Verify GitHub usernames in mapping file
- Check that users have access to the repository
- Review unmapped reviewers in PR comments

## 📝 Project Structure

```
bitbucket-github-pr-migration/
├── main.py                 # Main orchestrator
├── config.yaml             # Configuration file
├── user_mapping.yaml       # User mapping file
├── requirements.txt        # Python dependencies
├── README.md              # This file
├── clients/
│   ├── bitbucket_client.py # Bitbucket API client
│   └── github_client.py    # GitHub API client
├── models/
│   └── pr_model.py        # PR data models
├── utils/
│   ├── pr_logger.py       # Logging utilities
│   └── user_mapper.py     # User mapping utilities
└── logs/                  # Generated log files
```

## 🤝 Contributing

This is a custom migration tool. Feel free to adapt it to your needs.

## 📄 License

This project is provided as-is for migration purposes.

## 🆘 Support

For issues:

1. Check logs in `logs/migration_summary.log`
2. Review failed PRs in `logs/failed_prs.json`
3. Verify configuration in `config.yaml`
4. Ensure branches exist in GitHub

---

**Created:** December 2025  
**Python Version:** 3.8+  
**API Versions:** Bitbucket REST API 2.0, GitHub REST API 2025
