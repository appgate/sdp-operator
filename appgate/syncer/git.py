import functools
from typing import Tuple, List

import yaml
from git import Repo, GitCommandError
from github import Github
from pathlib import Path
import shutil

from attr import attrib, attrs, evolve

from appgate.attrs import K8S_LOADER
from appgate.logger import log
from appgate.openapi.types import AppgateException, APISpec, Entity_T
from appgate.state import AppgateState
from appgate.types import (
    ensure_env,
    GITHUB_TOKEN_ENV,
    GitOperatorContext,
    GIT_DUMP_DIR,
    GITHUB_DEPLOYMENT_KEY_PATH,
    dump_entity,
    EntityWrapper,
    EntitiesSet,
    EntityClient,
    GitCommitState,
)


class EnvironmentVariableNotFoundException(Exception):
    pass


def git_dump(entity: Entity_T, api_version: str, dest: Path) -> Path:
    entity_type = entity.__class__.__qualname__
    entity_file = dest / f"{entity.name.lower().replace(' ', '-')}.yaml"
    log.info("Dumping entity %s: %s", entity.name, entity_file)
    dumped_entity = dump_entity(EntityWrapper(entity), entity_type, f"v{api_version}")
    with entity_file.open("w") as f:
        f.write(yaml.safe_dump(dumped_entity, default_flow_style=False, sort_keys=True))
    return entity_file


def git_load(file: Path, entity_type: type) -> Entity_T:
    with file.open("r") as f:
        data = yaml.safe_load(f)
        return K8S_LOADER.load(data["spec"], None, entity_type)


def get_current_branch_state(api_spec: APISpec, repository_path: Path) -> AppgateState:
    entities_set = {}
    for e, v in api_spec.api_entities.items():
        dest = repository_path / e.lower()
        if not dest.is_dir():
            log.debug("Directory for entities %s not found, ignoring", dest)
            entities_set[e] = EntitiesSet()
            continue
        entities_set[e] = EntitiesSet(
            {EntityWrapper(git_load(f, entity_type=v.cls)) for f in dest.glob("*.yaml")}
        )

    return AppgateState(entities_set=entities_set)


@attrs(slots=True, frozen=True)
class GitRepo:
    repository: str = attrib()
    repository_path: Path = attrib()
    repo: Repo = attrib()
    base_branch: str = attrib()
    vendor: str = attrib()
    dry_run: bool = attrib()
    repository_fork: str | None = attrib()

    @functools.cache
    def user_fork(self) -> str | None:
        return self.repository_fork.split("/")[0] if self.repository_fork else None

    def checkout_branch(self, branch: str) -> None:
        # Checkout the fork if we are using a forked repository
        log.info(
            f"[git-operator] Checking out new branch {self.repo.remote().name}/{branch}"
        )
        if self.dry_run:
            return
        self.repo.git.branch(branch)
        self.repo.git.checkout(branch)

    def needs_pull_request(self) -> bool:
        self.repo.index.add([f"{self.repository_path}/*"])
        return self.repo.is_dirty()

    def commit_change(self, branch: str) -> None:
        log.info(
            f"[git-operator] Committing changes to {self.repo.remote().name}:{branch}"
        )
        if not self.dry_run:
            self.repo.index.commit(branch)

    def push_change(self, branch: str) -> None:
        log.info(
            f"[git-operator] Pushing changes to {self.repo.remote().name}:{branch}"
        )
        if not self.dry_run:
            self.repo.git.push("--set-upstream", self.repo.remote().name, branch)

    def create_pull_request(self, branch: str) -> None:
        pass


def github_repo(ctx: GitOperatorContext, repository_path: Path) -> GitRepo:
    token = ensure_env(GITHUB_TOKEN_ENV)
    repository = ctx.git_repository_fork or ctx.git_repository
    log.info("[git-operator] Initializing the git repository by cloning %s", repository)
    if repository_path.exists():
        shutil.rmtree(repository_path)
    if not GITHUB_DEPLOYMENT_KEY_PATH.exists():
        raise AppgateException(
            f"Unable to find deployment key {GITHUB_DEPLOYMENT_KEY_PATH}"
        )
    try:
        git_repo = Repo.clone_from(
            f"git@github.com:{repository}",
            repository_path,
            env={
                "GIT_SSH_COMMAND": f"ssh -i {GITHUB_DEPLOYMENT_KEY_PATH} -o IdentitiesOnly=yes"
            },
        )
    except GitCommandError as e:
        log.error("Error cloning repository %s: %s", repository, e.stderr)
        raise AppgateException(f"Unable to clone repository {repository}")

    log.info(f"[git-operator] Repository %s cloned", repository)
    return GitHubRepo(
        token=token,
        repository=repository,
        repository_fork=ctx.git_repository_fork,
        repo=git_repo,
        base_branch=ctx.git_base_branch,
        vendor=ctx.git_vendor,
        repository_path=repository_path,
        dry_run=ctx.dry_run,
    )


@attrs(slots=True, frozen=True)
class GitHubRepo(GitRepo):
    token: str = attrib()

    def create_pull_request(self, branch: str) -> None:
        title = f"Merge changes from {branch}"
        head_branch = branch
        if self.user_fork():
            head_branch = f"{self.user_fork()}:{branch}"
        log.info(
            f"[git-operator] Creating pull request in GitHub from '%s' to '%s' into repo '%s' with title '%s",
            head_branch,
            self.base_branch,
            self.repository,
            title,
        )
        if self.dry_run:
            return
        gh = Github(self.token)
        gh_repo = gh.get_repo(self.repository)

        gh_repo.create_pull(
            title=title, body=branch, head=head_branch, base=self.base_branch
        )


def get_git_repository(ctx: GitOperatorContext) -> GitRepo:
    if ctx.git_vendor.lower() == "github":
        log.info("[git-operator] Detected GitHub as git vendor type")
        return github_repo(ctx, GIT_DUMP_DIR)
    else:
        raise Exception(f"Unknown git vendor type {ctx.git_vendor}")


@functools.cache
def entity_path(repository_path: Path, kind: str) -> Path:
    return repository_path / kind.lower()


@attrs()
class GitEntityClient(EntityClient):
    version: str = attrib()
    kind: str = attrib()
    repository_path: Path = attrib()
    git_repo: GitRepo = attrib()
    branch: str = attrib()
    commits: List[Tuple[Path, GitCommitState]] = attrib()

    def with_commit(self, state: GitCommitState, file: Path) -> "GitEntityClient":
        self.commits.append((file, state))
        return evolve(self, commits=self.commits)

    async def init(self) -> EntityClient:
        self.commits = []
        return self

    async def create(self, e: Entity_T) -> EntityClient:
        p = entity_path(self.repository_path, self.kind)
        log.info("Creating file %s for entity %s", p, e.name)
        p.mkdir(exist_ok=True)
        file = git_dump(e, self.version, p)
        self.commits.append((file, "ADD"))
        return self

    async def delete(self, name: str) -> EntityClient:
        p: Path = entity_path(self.repository_path, self.kind) / f"{name}.yaml"
        self.commits.append((p, "REMOVE"))
        log.info("Removing file %s for entity %s", p, name)
        if p.exists():
            p.unlink()
        else:
            log.warning("File %s should be deleted but it's not present")
        return self

    async def modify(self, e: Entity_T) -> EntityClient:
        await self.delete(e.name)
        await self.create(e)
        return self

    async def commit(self) -> EntityClient:
        if not self.commits:
            return self
        log.info("Committing changes for entities %s:", self.kind)
        for p, o in self.commits:
            if o == "ADD":
                log.info(" - New commit: [%s] %s", o, p)
                self.git_repo.repo.index.add([str(p)])
            elif o == "REMOVE":
                log.info(" + New commit: [%s] %s", o, p)
                self.git_repo.repo.index.remove([str(p)])
        self.git_repo.repo.index.commit(self.branch)
        return self
