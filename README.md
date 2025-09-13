# GitHub to Forgejo Bulk Migration Script

A Bash script to bulk migrate all repositories from GitHub to Forgejo/Gitea using their respective APIs. Supports both one-time cloning and mirroring (continuous sync) modes, with full metadata migration including issues, pull requests, labels, milestones, releases, and wikis.

## Features

- **Bulk migration** of all repositories from a GitHub user or organization
- **Mirror mode** for continuous synchronization from GitHub to Forgejo
- **Metadata migration** including issues, PRs, labels, milestones, releases, and wikis
- **Duplicate detection** to avoid processing the same repository multiple times
- **Dry run mode** for testing without making actual changes
- **Error handling** with detailed HTTP response logging

## Prerequisites

### Required Tools
- `bash` (4.0+)
- `curl`
- `jq` - JSON processor

Install jq on Fedora/Nobara:
```bash
sudo dnf install -y jq
```

### Required Tokens

1. **GitHub Personal Access Token**
   - Go to GitHub Settings → Developer settings → Personal access tokens
   - Generate a token with `repo` scope (for private repos) or `public_repo` (for public only)
   - Add `workflow` scope if migrating GitHub Actions

2. **Forgejo Personal Access Token**
   - Log into your Forgejo instance
   - Go to Settings → Applications → Generate New Token
   - Grant sufficient permissions for repository creation

## Setup

### 1. Clone or Download
Save the script as `migrate-github-to-forgejo.sh` and make it executable:
```bash
chmod +x migrate-github-to-forgejo.sh
```

### 2. Configure Environment Variables
Export the following variables in your shell:

```bash
# Forgejo configuration
export FORGEJO_URL="http://your-forgejo-instance:port"  # e.g., "http://10.1.1.5:3040"
export FORGEJO_TOKEN="your_forgejo_personal_access_token"
export FORGEJO_OWNER="destination-user-or-org"          # Where repos will be created

# GitHub configuration
export GITHUB_OWNER="source-github-user-or-org"         # Source to migrate from
export GITHUB_OWNER_TYPE="user"                         # "user" or "org"
export GITHUB_TOKEN="ghp_your_github_token"

# Migration behavior
export MIRROR="true"                                     # "true" for mirror, "false" for one-time clone
export MIGRATE_METADATA="true"                          # "true" to migrate issues/PRs/etc
export DRY_RUN="1"                                       # "1" for preview, "0" for actual migration
```

## Usage

### 1. Test Run (Recommended)
First, run in dry-run mode to see what will be migrated:
```bash
DRY_RUN=1 ./migrate-github-to-forgejo.sh
```

This will output JSON payloads for each repository without making actual API calls to Forgejo.

### 2. Execute Migration
Once you're satisfied with the dry run output:
```bash
DRY_RUN=0 ./migrate-github-to-forgejo.sh
```

## Configuration Options

| Variable | Values | Description |
|----------|--------|-------------|
| `MIRROR` | `true`/`false` | `true`: Keep syncing from GitHub<br>`false`: One-time clone |
| `MIGRATE_METADATA` | `true`/`false` | `true`: Migrate issues, PRs, labels, etc.<br>`false`: Git history only |
| `DRY_RUN` | `1`/`0` | `1`: Preview mode (no actual migration)<br>`0`: Execute migration |
| `GITHUB_OWNER_TYPE` | `user`/`org` | Type of GitHub account to migrate from |

## Security Considerations

⚠️ **Important Security Notes:**

- **Never commit your tokens** to version control
- **Use environment variables** to pass sensitive information
- **Revoke tokens** immediately if exposed
- **Limit token permissions** to only what's needed
- **Run the script as a regular user** (avoid sudo unless necessary)

### If running with sudo:
```bash
sudo --preserve-env=FORGEJO_URL,FORGEJO_TOKEN,FORGEJO_OWNER,GITHUB_OWNER,GITHUB_OWNER_TYPE,GITHUB_TOKEN,MIRROR,MIGRATE_METADATA,DRY_RUN ./migrate-github-to-forgejo.sh
```

## Migration Types

### Mirror Mode (`MIRROR=true`)
- Creates a pull-mirror that periodically syncs from GitHub
- Keeps repositories up-to-date automatically
- Ideal for maintaining synchronized copies

### Clone Mode (`MIRROR=false`)
- One-time import of repository content
- No ongoing synchronization
- Full ownership transfer to Forgejo

### Metadata Migration (`MIGRATE_METADATA=true`)
- Imports issues, pull requests, labels, milestones
- Migrates releases and wiki content
- Uses GitHub's migration service for complete transfer
- May have author mapping limitations

## Troubleshooting

### Common Issues

**Environment variables not found when using sudo:**
- Use `--preserve-env` flag or run without sudo
- Verify variables are exported: `env | grep FORGEJO_URL`

**Duplicate repositories:**
- The script includes duplicate detection
- Previous versions may have caused duplicates
- Check Forgejo UI to verify actual repository count

**Authentication errors:**
- Verify token permissions and expiration
- Check Forgejo API access at `/api/swagger`
- Ensure GitHub token has required scopes

**Migration timeouts:**
- Large repositories may take time to process
- Check Forgejo logs for migration status
- Increase timeout settings in Forgejo configuration if needed

**LFS repositories:**
- Git LFS content may require additional attention
- Verify LFS files migrated correctly
- Manual intervention may be needed for some LFS repos

### Verify Migration Success

Check migrated repositories via Forgejo API:
```bash
curl -H "Authorization: token $FORGEJO_TOKEN" \
     "$FORGEJO_URL/api/v1/user/repos?limit=50" | jq '.[].name'
```

Or browse the Forgejo web interface to confirm repositories appear under the destination owner.

## Example Output

```
Fetching linuxmunchies repos page 1...
Queueing migration: linuxmunchies/.zshrc -> gitfox/.zshrc
Queueing migration: linuxmunchies/AHKScripts -> gitfox/AHKScripts
Migration queued for .zshrc (HTTP 201)
Migration queued for AHKScripts (HTTP 201)
...
```

## License

This script is provided as-is for educational and utility purposes. Use at your own risk and ensure you comply with GitHub's and Forgejo's terms of service when migrating repositories.

## Contributing

Feel free to submit issues, improvements, or feature requests. When reporting issues, please include:
- Your operating system and version
- Forgejo/Gitea version
- Error messages or unexpected behavior
- Steps to reproduce the issue
