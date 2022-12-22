import os

from git import Repo
from github import Github
from pathlib import Path
import shutil

from attr import attrib, attrs

from appgate.logger import log
from appgate.openapi.types import AppgateException
from appgate.types import (
    ensure_env,
    GITHUB_TOKEN_ENV,
    GitOperatorContext,
    GIT_DUMP_DIR,
    GITHUB_DEPLOYMENT_KEY_PATH,
)


class EnvironmentVariableNotFoundException(Exception):
    pass


@attrs(slots=True, frozen=True)
class GitRepo:
    repository_name: str = attrib()
    repository_path: Path = attrib()
    git_repo: Repo = attrib()
    base_branch: str = attrib()
    vendor: str = attrib()

    def checkout_branch(self, branch: str, dry_run: bool) -> None:
        log.info(
            f"[git-operator] Checking out new branch {self.git_repo.remote().name}/{branch}"
        )
        if dry_run:
            return
        self.git_repo.git.branch(branch)
        self.git_repo.git.checkout(branch)

    def needs_pull_request(self) -> bool:
        self.git_repo.index.add([f"{self.repository_path}/*"])
        return self.git_repo.is_dirty()

    def commit_change(self, branch: str, dry_run) -> None:
        log.info(
            f"[git-operator] Committing changes to {self.git_repo.remote().name}:{branch}"
        )
        if not dry_run:
            self.git_repo.index.commit(branch)

    def push_change(self, branch: str, dry_run: bool) -> None:
        log.info(
            f"[git-operator] Pushing changes to {self.git_repo.remote().name}:{branch}"
        )
        if not dry_run:
            self.git_repo.git.push(
                "--set-upstream", self.git_repo.remote().name, branch
            )

    def create_pull_request(self, branch: str, dry_run: bool) -> None:
        pass


def github_repo(ctx: GitOperatorContext, repository_path: Path) -> GitRepo:
    token = ensure_env(GITHUB_TOKEN_ENV)
    # Fine-grained token? make sure the user is oauth2
    if token.startswith("github_pat_"):
        username = "oauth2"
    elif not ctx.git_username:
        raise AppgateException("Unable to find github username.")
    else:
        username = ctx.git_username
    repository = f"github.com:{ctx.git_repository}"
    log.info(f"[git-operator] Initializing the git repository by cloning {repository}")
    if repository_path.exists():
        shutil.rmtree(repository_path)
    if not GITHUB_DEPLOYMENT_KEY_PATH.exists():
        raise AppgateException(
            f"Unable to find deployment key {GITHUB_DEPLOYMENT_KEY_PATH}"
        )
    git_repo = Repo.clone_from(
        f"git@{repository}",
        repository_path,
        env={
            "GIT_SSH_COMMAND": f"ssh -i {GITHUB_DEPLOYMENT_KEY_PATH} -o IdentitiesOnly=yes"
        },
    )
    log.info(f"[git-operator] Repository {repository} cloned")
    return GitHubRepo(
        username=username,
        token=token,
        repository_name=repository,
        git_repo=git_repo,
        base_branch=ctx.git_base_branch,
        vendor=ctx.git_vendor,
        repository_path=repository_path,
    )


@attrs(slots=True, frozen=True)
class GitHubRepo(GitRepo):
    username: str = attrib()
    token: str = attrib()

    def create_pull_request(self, branch: str, dry_run: bool) -> None:
        title = f"Merge changes from {branch}"
        log.info(
            f"[git-operator] Creating pull request in GitHub from '{branch}' to '{self.base_branch}'"
        )
        if dry_run:
            return
        gh = Github(f"{self.token}")
        gh_repo = gh.get_repo(f"{self.repository_name}")
        gh_repo.create_pull(
            title=title, body=branch, head=branch, base=self.base_branch
        )


def get_git_repository(ctx: GitOperatorContext) -> GitRepo:
    if ctx.git_vendor.lower() == "github":
        log.info("[git-syncer] Detected GitHub as git vendor type")
        return github_repo(ctx, GIT_DUMP_DIR)
    else:
        raise Exception(f"Unknown git vendor type {ctx.git_vendor}")
