from git import Repo
from github import Github
from pathlib import Path
import os
import shutil
import datetime
import time

from appgate.logger import log


class EnvironmentVariableNotFoundException(Exception):
    pass


class GitRepo:
    repository: Repo
    repository_dir: Path
    branch: str

    def check_env_vars(self) -> None:
        envs = [
            "GIT_REPOSITORY_URL",
            "GIT_USERNAME",
            "GIT_TOKEN",
            "GIT_BASE_BRANCH",
        ]
        for env in envs:
            if not os.getenv(env):
                raise EnvironmentVariableNotFoundException(env)

    def clone_repository(self, dir: Path) -> None:
        url = os.getenv("GIT_REPOSITORY_URL")
        username = os.getenv("GIT_USERNAME")
        password = os.getenv("GIT_TOKEN")
        repo_url = f"https://{username}:{password}@{url}"

        self.repository_dir = dir
        if self.repository_dir.exists():
            shutil.rmtree(self.repository_dir)

        log.info(f"[git-sync] Initializing the git repository by cloning {url}")
        self.repository = Repo.clone_from(repo_url, self.repository_dir)

    def checkout_branch(self) -> None:
        self.branch = f'{str(datetime.date.today())}.{time.strftime("%H-%M-%S")}'
        log.info(
            f"[git-syncer] Checking out new branch {self.repository.remote().name}/{self.branch}"
        )
        self.repository.git.branch(self.branch)
        self.repository.git.checkout(self.branch)

    def needs_pull_request(self) -> bool:
        self.repository.index.add([f"{self.repository_dir}/*"])
        return self.repository.is_dirty()

    def commit_change(self) -> None:
        log.info(
            f"[git-syncer] Committing changes to {self.repository.remote().name}:{self.branch}"
        )
        self.repository.index.commit(self.branch)

    def push_change(self) -> None:
        log.info(
            f"[git-syncer] Pushing changes to {self.repository.remote().name}:{self.branch}"
        )
        self.repository.git.push(
            "--set-upstream", self.repository.remote().name, self.branch
        )

    def create_pull_request(self) -> None:
        pass


class GitHubRepo(GitRepo):
    def check_env_vars(self) -> None:
        super().check_env_vars()
        envs = ["GITHUB_REPOSITORY"]
        for env in envs:
            if not os.getenv(env):
                raise EnvironmentVariableNotFoundException(env)

    def create_pull_request(self) -> None:
        token = os.getenv("GIT_TOKEN")
        base_branch = os.getenv("GIT_BASE_BRANCH", "master")
        repo = os.getenv("GITHUB_REPOSITORY")
        title = f"Merge changes from {self.branch}"

        log.info(
            f"[git-syncer] Creating pull request in GitHub from '{self.branch}' to '{base_branch}'"
        )
        gh = Github(f"{token}")
        gh_repo = gh.get_repo(f"{repo}")
        gh_repo.create_pull(
            title=title, body=self.branch, head=self.branch, base=base_branch
        )


def get_git_repository() -> GitRepo:
    vendor_type = os.getenv("GIT_VENDOR")
    if not vendor_type:
        raise EnvironmentVariableNotFoundException("GIT_VENDOR")

    if vendor_type.lower() == "github":
        log.info("[git-syncer] Detected GitHub as git vendor type")
        return GitHubRepo()
    else:
        raise Exception(f"Unknown git vendor type {vendor_type}")
