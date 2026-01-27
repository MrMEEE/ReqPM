"""
Git operations utilities
"""
import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple
import git
from git.exc import GitCommandError
import logging

logger = logging.getLogger(__name__)


class GitManager:
    """Manages Git operations for projects"""
    
    def __init__(self, cache_dir: str):
        """
        Initialize GitManager
        
        Args:
            cache_dir: Directory for caching Git repositories
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def clone_or_update(
        self,
        url: str,
        branch: Optional[str] = None,
        tag: Optional[str] = None,
        commit: Optional[str] = None,
        ssh_key: Optional[str] = None,
        api_token: Optional[str] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Clone or update a Git repository
        
        Args:
            url: Git repository URL
            branch: Branch to checkout
            tag: Tag to checkout
            commit: Commit hash to checkout
            ssh_key: SSH private key for authentication
            api_token: API token for authentication
        
        Returns:
            Tuple of (success, repo_path, error_message)
        """
        try:
            # Generate cache directory name from URL
            repo_name = self._get_repo_name(url)
            repo_path = self.cache_dir / repo_name
            
            # Set up authentication
            env = self._setup_auth(ssh_key, api_token)
            
            # Clone or update repository
            if repo_path.exists():
                logger.info(f"Updating repository: {url}")
                repo = git.Repo(repo_path)
                
                # Fetch latest changes
                with repo.git.custom_environment(**env):
                    repo.remotes.origin.fetch()
            else:
                logger.info(f"Cloning repository: {url}")
                with git.Git().custom_environment(**env):
                    repo = git.Repo.clone_from(url, repo_path)
            
            # Checkout specific ref
            ref = tag or commit or branch or 'main'
            try:
                repo.git.checkout(ref)
                logger.info(f"Checked out: {ref}")
            except GitCommandError as e:
                # Try alternative default branch names
                for default_branch in ['master', 'develop']:
                    try:
                        repo.git.checkout(default_branch)
                        logger.info(f"Checked out default branch: {default_branch}")
                        break
                    except GitCommandError:
                        continue
                else:
                    raise e
            
            return True, str(repo_path), None
        
        except Exception as e:
            logger.error(f"Git operation failed: {e}")
            return False, "", str(e)
    
    def get_branches_and_tags(
        self,
        repo_path: str
    ) -> Tuple[List[str], List[str]]:
        """
        Get list of branches and tags from repository
        
        Args:
            repo_path: Path to repository
        
        Returns:
            Tuple of (branches, tags)
        """
        try:
            repo = git.Repo(repo_path)
            
            branches = [ref.name for ref in repo.refs if not ref.name.startswith('origin/')]
            tags = [tag.name for tag in repo.tags]
            
            return branches, tags
        
        except Exception as e:
            logger.error(f"Error getting branches/tags: {e}")
            return [], []
    
    def get_remote_branches(
        self,
        url: str,
        ssh_key: Optional[str] = None,
        api_token: Optional[str] = None
    ) -> List[str]:
        """
        Get list of branches from remote repository without cloning
        
        Args:
            url: Git repository URL
            ssh_key: SSH private key for authentication
            api_token: API token for authentication
        
        Returns:
            List of branch names
        """
        try:
            # Use git ls-remote to get remote branches
            env = self._setup_auth(ssh_key, api_token)
            
            # Get remote refs
            result = git.cmd.Git().ls_remote('--heads', url, env=env)
            
            # Parse branch names from output
            branches = []
            for line in result.split('\n'):
                if line.strip():
                    # Format: <hash>\trefs/heads/<branch>
                    parts = line.split('\t')
                    if len(parts) == 2:
                        ref = parts[1]
                        if ref.startswith('refs/heads/'):
                            branch = ref.replace('refs/heads/', '')
                            branches.append(branch)
            
            return branches
        
        except Exception as e:
            logger.error(f"Error getting remote branches: {e}")
            return []
    
    def get_commit_hash(
        self,
        repo_path: str,
        ref: Optional[str] = None
    ) -> Optional[str]:
        """
        Get commit hash for a reference
        
        Args:
            repo_path: Path to repository
            ref: Branch, tag, or commit (None for HEAD)
        
        Returns:
            Commit hash or None
        """
        try:
            repo = git.Repo(repo_path)
            
            if ref:
                commit = repo.commit(ref)
            else:
                commit = repo.head.commit
            
            return commit.hexsha
        
        except Exception as e:
            logger.error(f"Error getting commit hash: {e}")
            return None
    
    def read_file(
        self,
        repo_path: str,
        file_path: str,
        ref: Optional[str] = None
    ) -> Optional[str]:
        """
        Read a file from repository
        
        Args:
            repo_path: Path to repository
            file_path: Path to file within repository
            ref: Branch, tag, or commit (None for current)
        
        Returns:
            File content or None
        """
        try:
            full_path = Path(repo_path) / file_path
            
            if ref:
                # Read from specific ref
                repo = git.Repo(repo_path)
                commit = repo.commit(ref)
                blob = commit.tree / file_path
                return blob.data_stream.read().decode('utf-8')
            else:
                # Read from working directory
                with open(full_path, 'r') as f:
                    return f.read()
        
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return None
    
    def _get_repo_name(self, url: str) -> str:
        """Extract repository name from URL"""
        # Remove .git suffix and get last part of URL
        name = url.rstrip('/').split('/')[-1]
        if name.endswith('.git'):
            name = name[:-4]
        return name
    
    def _setup_auth(
        self,
        ssh_key: Optional[str] = None,
        api_token: Optional[str] = None
    ) -> dict:
        """
        Set up authentication environment
        
        Args:
            ssh_key: SSH private key
            api_token: API token
        
        Returns:
            Environment dictionary
        """
        env = os.environ.copy()
        
        if ssh_key:
            # Write SSH key to temporary file
            ssh_key_file = self.cache_dir / '.ssh_key'
            ssh_key_file.write_text(ssh_key)
            ssh_key_file.chmod(0o600)
            
            env['GIT_SSH_COMMAND'] = f'ssh -i {ssh_key_file} -o StrictHostKeyChecking=no'
        
        # API token would typically be embedded in the URL for HTTPS
        # e.g., https://token@github.com/user/repo.git
        
        return env
    
    def find_requirements_files(self, repo_path: str) -> List[str]:
        """
        Find all requirements files in a repository
        
        Args:
            repo_path: Path to the repository
            
        Returns:
            List of relative paths to requirements files
        """
        requirements_files = []
        repo_path = Path(repo_path)
        
        if not repo_path.exists():
            return requirements_files
        
        # Common patterns for requirements files
        patterns = [
            '**/requirements.txt',
            '**/requirements*.txt',
            '**/*requirements.txt',
            '**/requirements/*.txt',
            '**/reqs.txt',
            '**/reqs/*.txt',
        ]
        
        seen = set()
        for pattern in patterns:
            for file_path in repo_path.glob(pattern):
                # Skip hidden directories and common exclusions
                if any(part.startswith('.') for part in file_path.parts):
                    continue
                if any(part in ['node_modules', 'venv', 'env', '__pycache__', 'build', 'dist'] 
                       for part in file_path.parts):
                    continue
                
                # Get relative path
                try:
                    rel_path = file_path.relative_to(repo_path)
                    rel_path_str = str(rel_path)
                    
                    # Avoid duplicates
                    if rel_path_str not in seen:
                        seen.add(rel_path_str)
                        requirements_files.append(rel_path_str)
                except ValueError:
                    continue
        
        # Sort for consistent ordering
        return sorted(requirements_files)
    
    def cleanup_cache(self, repo_name: Optional[str] = None):
        """
        Clean up cached repositories
        
        Args:
            repo_name: Specific repository to clean (None for all)
        """
        try:
            if repo_name:
                repo_path = self.cache_dir / repo_name
                if repo_path.exists():
                    shutil.rmtree(repo_path)
                    logger.info(f"Cleaned up repository: {repo_name}")
            else:
                for item in self.cache_dir.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item)
                logger.info("Cleaned up all cached repositories")
        
        except Exception as e:
            logger.error(f"Error cleaning up cache: {e}")
