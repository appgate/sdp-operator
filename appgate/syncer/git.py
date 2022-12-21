from git import Repo
from github import Github
from pathlib import Path
import shutil

from attr import attrib, attrs

from appgate.logger import log
from appgate.syncer.operator import DUMP_DIR
from appgate.types import ensure_env, GIT_TOKEN_ENV, GitOperatorContext


class EnvironmentVariableNotFoundException(Exception):
    pass


@attrs(slots=True, frozen=True)
class GitRepo:
    username: str = attrib()
    token: str = attrib()
    repository_name: str = attrib()
    repository_path: Path = attrib()
    git_repo: Repo = attrib()
    base_branch: str = attrib()
    vendor: str = attrib()

    def checkout_branch(self, branch: str) -> None:
        log.info(
            f"[git-operator] Checking out new branch {self.git_repo.remote().name}/{branch}"
        )
        self.git_repo.git.branch(branch)
        self.git_repo.git.checkout(branch)

    def needs_pull_request(self) -> bool:
        self.git_repo.index.add([f"{self.repository_path}/*"])
        return self.git_repo.is_dirty()

    def commit_change(self, branch: str) -> None:
        log.info(
            f"[git-operator] Committing changes to {self.git_repo.remote().name}:{branch}"
        )
        self.git_repo.index.commit(branch)

    def push_change(self, branch: str) -> None:
        log.info(
            f"[git-operator] Pushing changes to {self.git_repo.remote().name}:{branch}"
        )
        self.git_repo.git.push("--set-upstream", self.git_repo.remote().name, branch)

    def create_pull_request(self, branch: str) -> None:
        pass


def github_repo(ctx: GitOperatorContext, repository_path: Path) -> GitRepo:
    token = ensure_env(GIT_TOKEN_ENV)
    # Fine-grained token? make sure the user is oauth2
    if token.startswith("github_pat_"):
        username = "oauth2"
    else:
        username = ctx.git_username
    repository = f"github.com/{ctx.git_repository}"
    log.info(f"[git-operator] Initializing the git repository by cloning {repository}")
    if repository_path.exists():
        shutil.rmtree(repository_path)
    git_repo = Repo.clone_from(
        f"https://{username}:{token}@{repository}", repository_path
    )
    return GitRepo(
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
    def create_pull_request(self, branch: str) -> None:
        title = f"Merge changes from {branch}"
        log.info(
            f"[git-operator] Creating pull request in GitHub from '{branch}' to '{self.base_branch}'"
        )
        gh = Github(f"{self.token}")
        gh_repo = gh.get_repo(f"{self.repository_name}")
        gh_repo.create_pull(
            title=title, body=branch, head=branch, base=self.base_branch
        )


def get_git_repository(ctx: GitOperatorContext) -> GitRepo:
    if ctx.git_vendor.lower() == "github":
        log.info("[git-syncer] Detected GitHub as git vendor type")
        return github_repo(ctx, DUMP_DIR)
    else:
        raise Exception(f"Unknown git vendor type {ctx.git_vendor}")
