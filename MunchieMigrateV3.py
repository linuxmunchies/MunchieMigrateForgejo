#!/usr/bin/env python3
"""
Munchie Migrate - GitHub to Forgejo Repository Migration Tool
A robust tool for migrating repositories from GitHub to Forgejo with metadata preservation.
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================================
# Constants and Configuration
# ============================================================================

class Color:
    """ANSI color codes for terminal output."""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    RESET = '\033[0m'


class OwnerType(Enum):
    """GitHub owner type enumeration."""
    USER = "user"
    ORG = "org"


@dataclass
class MigrationConfig:
    """Configuration for repository migration."""
    forgejo_url: str
    forgejo_token: str
    forgejo_owner: str
    github_owner: str
    github_owner_type: OwnerType
    github_token: str
    mirror: bool = True
    migrate_metadata: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for JSON serialization."""
        data = asdict(self)
        data['github_owner_type'] = self.github_owner_type.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MigrationConfig':
        """Create config from dictionary."""
        data['github_owner_type'] = OwnerType(data['github_owner_type'])
        return cls(**data)


# ============================================================================
# UI Components
# ============================================================================

class UI:
    """Handles all user interface interactions."""

    @staticmethod
    def print_header():
        """Print application header."""
        print(f"{Color.BLUE}╔════════════════════════════════════════╗{Color.RESET}")
        print(f"{Color.BLUE}║{Color.RESET} Munchie Migrate - Repository Tool {Color.BLUE}║{Color.RESET}")
        print(f"{Color.BLUE}╚════════════════════════════════════════╝{Color.RESET}\n")

    @staticmethod
    def print_section(text: str):
        """Print a section header."""
        print(f"{Color.BLUE}➜{Color.RESET} {text}")

    @staticmethod
    def print_success(text: str):
        """Print a success message."""
        print(f"{Color.GREEN}✓{Color.RESET} {text}")

    @staticmethod
    def print_error(text: str):
        """Print an error message."""
        print(f"{Color.RED}✗{Color.RESET} {text}")

    @staticmethod
    def print_warning(text: str):
        """Print a warning message."""
        print(f"{Color.YELLOW}⚠{Color.RESET} {text}")

    @staticmethod
    def print_info(text: str):
        """Print an info message."""
        print(f"{Color.BLUE}ℹ{Color.RESET} {text}")

    @staticmethod
    def prompt_input(prompt: str, default: str = "") -> str:
        """Prompt user for input with optional default."""
        if default:
            result = input(f"{Color.BLUE}?{Color.RESET} {prompt} [{default}]: ").strip()
            return result if result else default
        return input(f"{Color.BLUE}?{Color.RESET} {prompt}: ").strip()

    @staticmethod
    def prompt_password(prompt: str) -> str:
        """Prompt user for password (hidden input)."""
        import getpass
        return getpass.getpass(f"{Color.BLUE}?{Color.RESET} {prompt}: ")

    @staticmethod
    def prompt_confirm(prompt: str, default: bool = False) -> bool:
        """Prompt user for yes/no confirmation."""
        choices = "(Y/n)" if default else "(y/N)"
        response = input(f"{Color.BLUE}?{Color.RESET} {prompt} {choices}: ").strip().lower()
        
        if not response:
            return default
        return response in ('y', 'yes')

    @staticmethod
    def prompt_choice(prompt: str, options: List[str]) -> str:
        """Prompt user to choose from a list of options."""
        print(f"{Color.BLUE}?{Color.RESET} {prompt}")
        for i, option in enumerate(options, 1):
            print(f"  {i}) {option}")
        
        while True:
            try:
                choice = int(input(f"{Color.BLUE}?{Color.RESET} Enter choice (1-{len(options)}): ").strip())
                if 1 <= choice <= len(options):
                    return options[choice - 1]
                UI.print_error("Invalid choice")
            except (ValueError, KeyboardInterrupt):
                UI.print_error("Invalid input")


# ============================================================================
# API Clients
# ============================================================================

class APIClient:
    """Base API client with retry logic and error handling."""

    def __init__(self, base_url: str, token: str, token_prefix: str = "token"):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.token_prefix = token_prefix
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session

    def _get_headers(self) -> Dict[str, str]:
        """Get default headers for API requests."""
        return {
            "Authorization": f"{self.token_prefix} {self.token}",
            "Content-Type": "application/json"
        }

    def get(self, endpoint: str, **kwargs) -> requests.Response:
        """Make a GET request."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        response = self.session.get(url, headers=self._get_headers(), **kwargs)
        response.raise_for_status()
        return response

    def post(self, endpoint: str, data: Dict[str, Any], **kwargs) -> requests.Response:
        """Make a POST request."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        response = self.session.post(
            url,
            headers=self._get_headers(),
            json=data,
            **kwargs
        )
        return response


class GitHubClient(APIClient):
    """GitHub API client."""

    def __init__(self, token: str):
        super().__init__("https://api.github.com", token, "Bearer")

    def _get_headers(self) -> Dict[str, str]:
        """Get headers with GitHub-specific accept header."""
        headers = super()._get_headers()
        headers["Accept"] = "application/vnd.github.v3+json"
        return headers

    def test_connection(self) -> tuple[bool, Optional[str]]:
        """Test GitHub API connection."""
        try:
            response = self.get("/user")
            username = response.json().get('login')
            return True, username
        except Exception as e:
            return False, str(e)

    def get_repositories(self, owner: str, owner_type: OwnerType) -> List[Dict[str, Any]]:
        """Fetch all repositories for a user or organization."""
        repos = []
        page = 1
        path = "users" if owner_type == OwnerType.USER else "orgs"
        
        while True:
            try:
                response = self.get(
                    f"/{path}/{owner}/repos",
                    params={"per_page": 100, "type": "all", "page": page}
                )
                page_repos = response.json()
                
                if not page_repos:
                    break
                
                repos.extend(page_repos)
                page += 1
                
            except Exception as e:
                logging.error(f"Error fetching repos on page {page}: {e}")
                break
        
        return repos


class ForgejoClient(APIClient):
    """Forgejo API client."""

    def __init__(self, url: str, token: str):
        super().__init__(url, token, "token")

    def test_connection(self) -> tuple[bool, Optional[str]]:
        """Test Forgejo API connection."""
        try:
            response = self.get("/api/v1/user")
            username = response.json().get('login')
            return True, username
        except Exception as e:
            return False, str(e)

    def get_existing_repos(self, owner: str) -> List[str]:
        """Get list of existing repository names."""
        try:
            response = self.get(f"/api/v1/users/{owner}/repos", params={"limit": 1000})
            return [repo['name'] for repo in response.json()]
        except Exception as e:
            logging.error(f"Error fetching existing repos: {e}")
            return []

    def migrate_repository(
        self,
        repo_data: Dict[str, Any],
        config: MigrationConfig
    ) -> tuple[bool, int, Optional[str]]:
        """
        Migrate a repository to Forgejo.
        
        Returns:
            (success, http_code, error_message)
        """
        name = repo_data['name']
        is_private = repo_data['private']
        clone_url = repo_data['clone_url']
        
        if not config.migrate_metadata:
            # Embed GitHub token in clone URL only for git service
            clone_url = clone_url.replace(
                "https://",
                f"https://x-access-token:{config.github_token}@"
            )
        
        # Build migration payload
        payload = {
            "clone_addr": clone_url,
            "repo_name": name,
            "repo_owner": config.forgejo_owner,
            "private": is_private,
            "mirror": config.mirror,
        }
        
        if config.migrate_metadata:
            payload.update({
                "service": "github",
                "auth_token": config.github_token,
                "wiki": True,
                "issues": True,
                "labels": True,
                "milestones": True,
                "pull_requests": True,
                "releases": True
            })
        else:
            payload["service"] = "git"
        
        try:
            response = self.post("/api/v1/repos/migrate", payload)
            
            if response.status_code in (201, 202):
                return True, response.status_code, None
            else:
                error_msg = response.text
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', error_msg)
                except:
                    pass
                return False, response.status_code, error_msg
                
        except Exception as e:
            return False, 0, str(e)


# ============================================================================
# Configuration Management
# ============================================================================

class ConfigManager:
    """Manages configuration persistence."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path.home() / ".config" / "munchie-migrate" / "config.json"
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Optional[MigrationConfig]:
        """Load configuration from file."""
        if not self.config_path.exists():
            return None
        
        try:
            with open(self.config_path, 'r') as f:
                data = json.load(f)
            return MigrationConfig.from_dict(data)
        except Exception as e:
            logging.error(f"Error loading config: {e}")
            return None

    def save(self, config: MigrationConfig) -> bool:
        """Save configuration to file."""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(config.to_dict(), f, indent=2)
            self.config_path.chmod(0o600)  # Secure permissions
            return True
        except Exception as e:
            logging.error(f"Error saving config: {e}")
            return False


# ============================================================================
# Validation
# ============================================================================

class Validator:
    """Input validation utilities."""

    @staticmethod
    def validate_url(url: str) -> bool:
        """Validate URL format."""
        try:
            result = urlparse(url)
            return all([result.scheme in ('http', 'https'), result.netloc])
        except:
            return False

    @staticmethod
    def validate_required(value: str, name: str) -> bool:
        """Validate that a required value is not empty."""
        if not value or not value.strip():
            UI.print_error(f"{name} cannot be empty")
            return False
        return True


# ============================================================================
# Interactive Setup
# ============================================================================

class InteractiveSetup:
    """Handles interactive configuration setup."""

    @staticmethod
    def run() -> Optional[MigrationConfig]:
        """Run interactive setup and return configuration."""
        UI.print_header()
        UI.print_section("Configuration Setup")
        print()

        # Forgejo configuration
        print(f"{Color.YELLOW}═══ FORGEJO (Destination) ═══{Color.RESET}")
        print("This is where your repositories will be migrated to.\n")

        while True:
            forgejo_url = UI.prompt_input("Forgejo URL", "https://forgejo.example.com")
            if Validator.validate_url(forgejo_url):
                break
            UI.print_error("Invalid URL. Must start with http:// or https://")

        print("\nTo generate a Forgejo API token:")
        UI.print_info(f"1. Log into your Forgejo instance at {forgejo_url}")
        UI.print_info("2. Go to Settings → Applications → Personal access tokens")
        UI.print_info("3. Create a new token with 'repo' and 'admin:org_hook' scopes")
        print()

        forgejo_token = UI.prompt_password("Forgejo API Token")
        if not Validator.validate_required(forgejo_token, "Forgejo token"):
            return None

        print()
        forgejo_owner = UI.prompt_input(
            "Forgejo Owner (your username or organization name)",
            "myusername"
        )
        if not Validator.validate_required(forgejo_owner, "Forgejo owner"):
            return None

        # GitHub configuration
        print(f"\n{Color.YELLOW}═══ GITHUB (Source) ═══{Color.RESET}")
        print("This is where your repositories will be migrated from.\n")

        github_owner = UI.prompt_input(
            "GitHub Owner (your username or organization name)",
            "myusername"
        )
        if not Validator.validate_required(github_owner, "GitHub owner"):
            return None

        print()
        owner_type_str = UI.prompt_choice(
            "Is this a GitHub user or organization?",
            ["user", "org"]
        )
        github_owner_type = OwnerType(owner_type_str)

        print("\nTo generate a GitHub Personal Access Token:")
        UI.print_info("1. Go to https://github.com/settings/tokens")
        UI.print_info("2. Create a new token (classic) with 'repo' scope")
        UI.print_info("3. Copy the token immediately (you can't view it again)")
        print()

        github_token = UI.prompt_password("GitHub Personal Access Token")
        if not Validator.validate_required(github_token, "GitHub token"):
            return None

        # Migration options
        print(f"\n{Color.YELLOW}═══ Migration Options ═══{Color.RESET}\n")

        mirror = UI.prompt_confirm("Create mirror repositories?", True)
        if mirror:
            UI.print_info("Repositories will be kept in sync with the source")
        else:
            UI.print_info("Repositories will be independent after migration")

        print()
        migrate_metadata = UI.prompt_confirm(
            "Migrate metadata (issues, PRs, labels, milestones, etc.)?",
            True
        )
        if migrate_metadata:
            UI.print_info("All metadata will be migrated (slower, more comprehensive)")
        else:
            UI.print_info("Only code will be migrated (faster)")

        # Create config object
        config = MigrationConfig(
            forgejo_url=forgejo_url,
            forgejo_token=forgejo_token,
            forgejo_owner=forgejo_owner,
            github_owner=github_owner,
            github_owner_type=github_owner_type,
            github_token=github_token,
            mirror=mirror,
            migrate_metadata=migrate_metadata
        )

        # Test connections
        print()
        UI.print_section("Testing Connections")

        forgejo_client = ForgejoClient(config.forgejo_url, config.forgejo_token)
        success, username = forgejo_client.test_connection()
        if success:
            UI.print_success(f"Forgejo connection successful (logged in as: {username})")
        else:
            UI.print_error(f"Failed to connect to Forgejo: {username}")
            return None

        github_client = GitHubClient(config.github_token)
        success, username = github_client.test_connection()
        if success:
            UI.print_success(f"GitHub connection successful (logged in as: {username})")
        else:
            UI.print_error(f"Failed to connect to GitHub: {username}")
            return None

        return config


# ============================================================================
# Migration Engine
# ============================================================================

@dataclass
class MigrationStats:
    """Statistics for migration operation."""
    migrated: int = 0
    skipped: int = 0
    failed: int = 0

    def print_summary(self):
        """Print migration summary."""
        print()
        UI.print_section("Migration Summary")
        UI.print_success(f"Migrated: {self.migrated}")
        UI.print_warning(f"Skipped: {self.skipped}")
        UI.print_error(f"Failed: {self.failed}")


class MigrationEngine:
    """Main migration engine."""

    def __init__(self, config: MigrationConfig):
        self.config = config
        self.github_client = GitHubClient(config.github_token)
        self.forgejo_client = ForgejoClient(config.forgejo_url, config.forgejo_token)
        self.stats = MigrationStats()

    def run(self):
        """Execute the migration process."""
        UI.print_header()
        UI.print_section("Starting Repository Migration")
        print()

        # Fetch existing repos
        UI.print_section("Fetching existing repos from Forgejo...")
        existing_repos = set(self.forgejo_client.get_existing_repos(self.config.forgejo_owner))
        UI.print_success(f"Found {len(existing_repos)} existing repos on Forgejo")
        print()

        # Fetch GitHub repos
        UI.print_section("Fetching repositories from GitHub...")
        github_repos = self.github_client.get_repositories(
            self.config.github_owner,
            self.config.github_owner_type
        )
        UI.print_success(f"Found {len(github_repos)} repos on GitHub")
        print()

        # Migrate each repository
        processed = set()
        for repo in github_repos:
            name = repo['name']
            
            # Skip if already exists or processed
            if name in existing_repos or name in processed:
                UI.print_warning(f"Skipping (existing/processed): {name}")
                self.stats.skipped += 1
                continue

            processed.add(name)
            
            # Migrate repository
            UI.print_section(f"Migrating: {self.config.github_owner}/{name} → {self.config.forgejo_owner}/{name}")
            
            success, http_code, error = self.forgejo_client.migrate_repository(repo, self.config)
            
            if success:
                UI.print_success(f"Migration queued (HTTP {http_code})")
                self.stats.migrated += 1
                logging.info(f"Migrated: {self.config.github_owner}/{name}")
            else:
                UI.print_error(f"Migration failed (HTTP {http_code})")
                if error:
                    print(f"  Error: {error}")
                self.stats.failed += 1
                logging.error(f"Failed: {self.config.github_owner}/{name} - {error}")

        # Print summary
        self.stats.print_summary()
        logging.info(f"Migration completed - Migrated: {self.stats.migrated}, Skipped: {self.stats.skipped}, Failed: {self.stats.failed}")


# ============================================================================
# CLI Menu
# ============================================================================

class Menu:
    """Interactive menu system."""

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.config: Optional[MigrationConfig] = None

    def show(self) -> Optional[str]:
        """Show menu and return user choice."""
        print(f"\n{Color.BLUE}Main Menu{Color.RESET}")
        print("  1) Start migration")
        print("  2) Reconfigure settings")
        print("  3) Test connections")
        print("  4) View logs")
        print("  5) Exit")
        
        return input(f"\n{Color.BLUE}?{Color.RESET} Select option (1-5): ").strip()

    def test_connections(self):
        """Test API connections."""
        if not self.config:
            UI.print_error("No configuration loaded")
            return

        UI.print_section("Testing Connections")
        
        forgejo_client = ForgejoClient(self.config.forgejo_url, self.config.forgejo_token)
        success, username = forgejo_client.test_connection()
        if success:
            UI.print_success(f"Forgejo connection successful (logged in as: {username})")
        else:
            UI.print_error(f"Failed to connect to Forgejo: {username}")

        github_client = GitHubClient(self.config.github_token)
        success, username = github_client.test_connection()
        if success:
            UI.print_success(f"GitHub connection successful (logged in as: {username})")
        else:
            UI.print_error(f"Failed to connect to GitHub: {username}")

    def view_logs(self):
        """View recent log entries."""
        log_file = Path("munchie-migrate.log")
        if not log_file.exists():
            UI.print_warning("No logs yet")
            return

        print()
        UI.print_section("Recent logs (last 30 lines)")
        print("─" * 60)
        with open(log_file, 'r') as f:
            lines = f.readlines()
            for line in lines[-30:]:
                print(line.rstrip())
        print("─" * 60)

    def run(self):
        """Run interactive menu loop."""
        logging.info("========== Munchie Migrate Started ==========")

        # Load or create config
        self.config = self.config_manager.load()
        if self.config:
            UI.print_success(f"Loaded configuration from {self.config_manager.config_path}")
        else:
            UI.print_info("No configuration found. Running setup...")
            self.config = InteractiveSetup.run()
            if not self.config:
                UI.print_error("Setup failed")
                return
            
            if UI.prompt_confirm("Save configuration for future use?"):
                if self.config_manager.save(self.config):
                    UI.print_success(f"Configuration saved to {self.config_manager.config_path}")

        # Menu loop
        while True:
            choice = self.show()

            if choice == '1':
                engine = MigrationEngine(self.config)
                engine.run()
            elif choice == '2':
                new_config = InteractiveSetup.run()
                if new_config:
                    self.config = new_config
                    if UI.prompt_confirm("Save configuration?"):
                        self.config_manager.save(self.config)
            elif choice == '3':
                self.test_connections()
            elif choice == '4':
                self.view_logs()
            elif choice == '5':
                UI.print_success("Goodbye!")
                break
            else:
                UI.print_error("Invalid choice")

        logging.info("========== Munchie Migrate Ended ==========")


# ============================================================================
# Main Entry Point
# ============================================================================

def setup_logging():
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler('munchie-migrate.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Munchie Migrate - GitHub to Forgejo Repository Migration Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Interactive mode
  %(prog)s --config           # Reconfigure settings
  %(prog)s --migrate          # Run migration with existing config
  %(prog)s --logs             # View migration logs
        """
    )
    
    parser.add_argument('--config', action='store_true', help='Reconfigure settings')
    parser.add_argument('--migrate', action='store_true', help='Run migration with existing config')
    parser.add_argument('--logs', action='store_true', help='View migration logs')
    parser.add_argument('--config-path', type=Path, help='Custom config file path')
    
    args = parser.parse_args()

    setup_logging()
    config_manager = ConfigManager(args.config_path)

    if args.logs:
        Menu(config_manager).view_logs()
    elif args.config:
        config = InteractiveSetup.run()
        if config and UI.prompt_confirm("Save configuration?"):
            config_manager.save(config)
    elif args.migrate:
        logging.info("========== Munchie Migrate (CLI mode) ==========")
        config = config_manager.load()
        if not config:
            UI.print_error("No configuration found. Run --config first.")
            sys.exit(1)
        engine = MigrationEngine(config)
        engine.run()
        logging.info("========== Munchie Migrate (CLI mode) Ended ==========")
    else:
        # Interactive mode
        menu = Menu(config_manager)
        menu.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Color.YELLOW}⚠{Color.RESET} Operation cancelled by user")
        sys.exit(0)
    except Exception as e:
        logging.exception("Unexpected error")
        print(f"{Color.RED}✗{Color.RESET} Fatal error: {e}")
        sys.exit(1)
