import enum
import functools
import os
import shlex
import time
from datetime import date
from typing import Tuple, List, Type, Dict, Iterable, Protocol
from urllib.parse import urlparse

import yaml
from git import Repo, GitCommandError
from github import Github
from github.Label import Label
from github.PullRequest import PullRequest
from github.Repository import Repository
from pathlib import Path
import shutil

from attr import attrib, attrs, evolve
from gitlab import Gitlab
from gitlab.v4.objects import Project, ProjectLabel, ProjectMergeRequest

from appgate.attrs import GIT_DUMPER, GIT_LOADER
from appgate.logger import log
from appgate.openapi.types import (
    AppgateException,
    APISpec,
    Entity_T,
    MissingFieldDependencies,
)
from appgate.state import AppgateState
from appgate.types import (
    ensure_env,
    GITHUB_TOKEN_ENV,
    GitOperatorContext,
    EntityWrapper,
    EntitiesSet,
    EntityClient,
    GitCommitState,
    APPGATE_OPERATOR_PR_LABEL_NAME,
    APPGATE_OPERATOR_PR_LABEL_COLOR,
    APPGATE_OPERATOR_PR_LABEL_DESC,
    GITLAB_TOKEN_ENV,
    GitVendor,
    GIT_SSH_KNOWN_HOSTS_FILE,
)


# GitHub SSH fingerprints
# see: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
GITHUB_SSH_FINGERPRINT = """github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl
github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=
github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk=
"""
GITLAB_SSH_FINGERPRINT = """gitlab.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCsj2bNKTBSpIYDEGk9KxsGh3mySTRgMtXL583qmBpzeQ+jqCMRgBqB98u3z++J1sKlXHWfM9dyhSevkMwSbhoR8XIq/U0tCNyokEi/ueaBMCvbcTHhO7FcwzY92WK4Yt0aGROY5qX2UKSeOvuP4D6TPqKF1onrSzH9bx9XUf2lEdWT/ia1NEKjunUqu1xOB/StKDHMoX4/OKyIzuS0q/T1zOATthvasJFoPrAjkohTyaDUz2LN5JoH839hViyEG82yB+MjcFV5MU3N1l1QL3cVUCh93xSaua1N85qivl+siMkPGbO5xR/En4iEY6K2XPASUEMaieWVNTRCtJ4S8H+9
gitlab.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBFSMqzJeV9rUzU4kWitGjeR4PWSa29SPqJ1fVkhtj3Hw9xjLVXVYrU9QlYWrOLXBpQ6KWjbjTDTdDkoohFzgbEY=
gitlab.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAfuCHKVTjquxvt6CM6tdG4SLp1Btn/nOeHHE5UOzRdf
"""


class EnvironmentVariableNotFoundException(Exception):
    pass


def entity_file_name(entity_name: str) -> str:
    return f"{entity_name.lower().replace(' ', '-')}.yaml"


def git_dump(
    entity: Entity_T,
    api_spec: APISpec,
    dest: Path,
    resolution_conflicts: Dict[str, List[MissingFieldDependencies]] | None,
) -> Path:
    entity_file = dest / entity_file_name(entity.name)
    log.info("Dumping entity %s: %s", entity.name, entity_file)
    dumped_entity = GIT_DUMPER(api_spec).dump(entity, True, resolution_conflicts)
    with entity_file.open("w") as f:
        f.write(yaml.safe_dump(dumped_entity, default_flow_style=False, sort_keys=True))
    return entity_file


def git_load(file: Path, entity_type: Type[Entity_T]) -> Entity_T:
    with file.open("r") as f:
        data = yaml.safe_load(f)
        mt = data.get("metadata")
        return GIT_LOADER.load(data["spec"], mt, entity_type)


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


def generate_branch_name() -> str:
    return f'sdp-operator/{str(date.today())}.{time.strftime("%H-%M-%S")}'


class BranchOp(enum.Enum):
    CREATE_AND_CHECKOUT = enum.auto()
    CHECKOUT = enum.auto()
    NOP = enum.auto()


class PullRequestLike(Protocol):
    @property
    def title(self) -> str: ...

    @property
    def number(self) -> int: ...

    @property
    def source(self) -> str: ...


@attrs(frozen=True)
class GitHubPullRequest:
    pr: PullRequest = attrib()

    @property
    def title(self) -> str:
        return self.pr.title

    @property
    def number(self) -> int:
        return self.pr.number

    @property
    def source(self) -> str:
        return self.pr.head.ref


@attrs(frozen=True)
class GitLabPullRequest:
    mr: ProjectMergeRequest = attrib()

    @property
    def title(self) -> str:
        return self.mr.title

    @property
    def number(self) -> int:
        return self.mr.iid

    @property
    def source(self) -> str:
        return self.mr.source_branch


@attrs(slots=True, frozen=True)
class GitRepo:
    repository: str = attrib()
    repository_path: Path = attrib()
    git_repo: Repo = attrib()
    base_branch: str = attrib()
    vendor: GitVendor = attrib()
    dry_run: bool = attrib()
    repository_fork: str | None = attrib()
    main_branch: str = attrib()

    @functools.cache
    def user_fork(self) -> str | None:
        return self.repository_fork.split("/")[0] if self.repository_fork else None

    def checkout_branch(
        self,
        previous_branch: str | None,
        previous_pr: PullRequestLike | None,
    ) -> Tuple[str, PullRequestLike | None]:
        raise NotImplementedError()

    def needs_pull_request(self) -> bool:
        return self.git_repo.is_dirty()

    def push_change(self, branch: str) -> None:
        log.info(
            f"[git-operator] Pushing changes to {self.git_repo.remote().name}:{branch}"
        )
        if not self.dry_run:
            self.git_repo.git.push(
                "--set-upstream", self.git_repo.remote().name, branch
            )

    def create_or_update_pull_request(
        self,
        branch: str,
        pull_request: PullRequestLike | None,
        commits: Dict[str, List[Tuple[str, GitCommitState]]],
    ) -> PullRequestLike | None:
        raise NotImplementedError()


def clone_repo(ctx: GitOperatorContext) -> Repo:
    repository = ctx.git_repository_fork or ctx.git_repository
    log.info("[git-operator] Initializing the git repository by cloning %s", repository)
    if ctx.git_dump_path.exists():
        shutil.rmtree(ctx.git_dump_path)
    if not ctx.git_ssh_key_path.exists():
        raise AppgateException(f"Unable to find SSH key {ctx.git_ssh_key_path}")
    url = (
        f"git@{urlparse(ctx.git_hostname).hostname}:{repository}"
        if ctx.git_hostname
        else f"git@{ctx.git_vendor}.com:{repository}"
    )
    try:
        git_ssh_command = [
            "ssh",
            "-i",
            str(ctx.git_ssh_key_path),
            "-o",
            "IdentitiesOnly=yes",
        ]
        if not ctx.git_strict_host_key_checking:
            git_ssh_command.extend(["-o", "StrictHostKeyChecking=no"])
        if ctx.git_ssh_port:
            git_ssh_command.extend(["-p", str(ctx.git_ssh_port)])
        if ctx.git_ssh_known_hosts_file != Path(GIT_SSH_KNOWN_HOSTS_FILE):
            git_ssh_command.extend(
                ["-o", f"UserKnownHostsFile={ctx.git_ssh_known_hosts_file}"]
            )

        git_repo = Repo.clone_from(
            url,
            ctx.git_dump_path,
            env={"GIT_SSH_COMMAND": shlex.join(git_ssh_command)},
        )
    except GitCommandError as e:
        log.error("Error cloning repository %s: %s", repository, e.stderr)
        raise AppgateException(f"Unable to clone repository {repository}")

    log.info(f"[git-operator] Repository %s cloned", repository)
    return git_repo


def gitlab_repo(ctx: GitOperatorContext) -> GitRepo:
    token = ensure_env(GITLAB_TOKEN_ENV)
    git_repo = clone_repo(ctx)
    repository = ctx.git_repository_fork or ctx.git_repository
    gl = Gitlab(url=ctx.git_hostname, private_token=token)
    gl_project = gl.projects.get(repository)
    return GitLabRepo(
        gl=gl,
        gl_project=gl_project,
        repository=repository,
        repository_fork=ctx.git_repository_fork,
        git_repo=git_repo,
        base_branch=ctx.git_base_branch,
        vendor=ctx.git_vendor,
        repository_path=ctx.git_dump_path,
        dry_run=ctx.dry_run,
        main_branch=ctx.main_branch,
    )


def github_repo(ctx: GitOperatorContext) -> GitRepo:
    token = ensure_env(GITHUB_TOKEN_ENV)
    git_repo = clone_repo(ctx)
    repository = ctx.git_repository_fork or ctx.git_repository
    gh = Github(token)
    gh_repo = gh.get_repo(repository)
    return GitHubRepo(
        gh=gh,
        gh_repo=gh_repo,
        repository=repository,
        repository_fork=ctx.git_repository_fork,
        git_repo=git_repo,
        base_branch=ctx.git_base_branch,
        vendor=ctx.git_vendor,
        repository_path=ctx.git_dump_path,
        dry_run=ctx.dry_run,
        main_branch=ctx.main_branch,
    )


@functools.cache
def get_sdp_gl_label(gl_project: Project) -> ProjectLabel:
    labels = gl_project.labels.list()
    label = next(
        filter(lambda l: l.name == APPGATE_OPERATOR_PR_LABEL_NAME, labels), None
    )
    if not label:
        gl_project.labels.create(
            {
                "name": APPGATE_OPERATOR_PR_LABEL_NAME,
                "color": f"#{APPGATE_OPERATOR_PR_LABEL_COLOR}",
                "description": APPGATE_OPERATOR_PR_LABEL_DESC,
            }
        )
    label = gl_project.labels.get(APPGATE_OPERATOR_PR_LABEL_NAME)
    return label


def get_sdp_gl_merge_request(
    gl_project: Project, number: int | None = None
) -> GitLabPullRequest | None:
    sdp_label = get_sdp_gl_label(gl_project)
    if number:
        return GitLabPullRequest(gl_project.mergerequests.get(number))

    mrs = gl_project.mergerequests.list(
        state="opened", order_by="created_at", sort="desc"
    )
    for m in mrs:
        if sdp_label.name in m.labels:
            return GitLabPullRequest(gl_project.mergerequests.get(m.iid))

    return None


@functools.cache
def get_sdp_gh_label(gh_repo: Repository) -> Label:
    labels = gh_repo.get_labels()
    label = next(
        filter(lambda l: l.name == APPGATE_OPERATOR_PR_LABEL_NAME, labels), None
    )
    if not label:
        label = gh_repo.create_label(
            name=APPGATE_OPERATOR_PR_LABEL_NAME,
            color=APPGATE_OPERATOR_PR_LABEL_COLOR,
            description=APPGATE_OPERATOR_PR_LABEL_DESC,
        )
    return label


def get_sdp_pull_request(
    gh_repo: Repository, number: int | None = None
) -> GitHubPullRequest | None:
    sdp_label = get_sdp_gh_label(gh_repo)

    if number:
        pr: PullRequest | None = gh_repo.get_pull(number)
    else:
        prs: Iterable[PullRequest] = gh_repo.get_pulls(
            state="open", sort="created", direction="desc"
        )
        p = next(
            filter(lambda p: sdp_label.name in map(lambda l: l.name, p.labels), prs),
            None,
        )
        pr = p
    return GitHubPullRequest(pr) if pr else None


def get_pull_request_body(
    commits: Dict[str, List[Tuple[str, GitCommitState]]], body: str | None
) -> str:
    if len(commits) == 0:
        return body or ""
    body = (
        body
        or f"""# sdp-operator entities updates
Pull request created automatically by sdp-operator

"""
    )
    body += f"\n## Changes on {str(date.today())} at {time.strftime('%H:%M')}"
    for k, cs in commits.items():
        if not cs:
            continue
        body += f"\n  * {k}"
        for p, o in cs:
            body += f"\n    - {o.get_commit_message()}"
    return body


def github_checkout_branch(
    previous_branch: str | None,
    previous_pr: PullRequestLike | None,
    open_pull: PullRequestLike | None,
) -> Tuple[str, BranchOp]:
    if open_pull and previous_branch != open_pull.source:
        # We found an open pr, use it and checkout branch
        return open_pull.source, BranchOp.CHECKOUT
    elif open_pull:
        # We found an open pr, but we are currently using it
        return open_pull.source, BranchOp.NOP
    elif previous_branch and not previous_pr:
        # We have created a branch but still not pr, keep using it
        return previous_branch, BranchOp.NOP
    else:
        # In any other case create a new branch
        return generate_branch_name(), BranchOp.CREATE_AND_CHECKOUT


def gitlab_checkout_branch(
    previous_branch: str | None,
    previous_pr: PullRequestLike | None,
    open_merge: PullRequestLike | None,
) -> Tuple[str, BranchOp]:
    if open_merge and previous_branch != open_merge.source:
        # We found an open pr, use it and checkout branch
        return open_merge.source, BranchOp.CHECKOUT
    elif open_merge:
        # We found an open pr, but we are currently using it
        return open_merge.source, BranchOp.NOP
    elif previous_branch and not previous_pr:
        # We have created a branch but still not pr, keep using it
        return previous_branch, BranchOp.NOP
    else:
        # In any other case create a new branch
        return generate_branch_name(), BranchOp.CREATE_AND_CHECKOUT


@attrs(slots=True, frozen=True)
class GitLabRepo(GitRepo):
    gl: Gitlab = attrib()
    gl_project: Project = attrib()

    def checkout_branch(
        self, previous_branch: str | None, previous_pr: PullRequestLike | None
    ) -> Tuple[str, PullRequestLike | None]:
        open_pull = get_sdp_gl_merge_request(self.gl_project)
        pr_branch, branch_op = gitlab_checkout_branch(
            previous_branch, previous_pr, open_pull
        )
        if branch_op == BranchOp.CHECKOUT and open_pull:
            log.info(
                "[git-operator] Found opened Pull Request %s [%s]. Using it",
                open_pull.title,
                open_pull.number,
            )
            log.info(
                "[git-operator] Fetching and checking out existing branch %s/%s",
                self.git_repo.remote().name,
                pr_branch,
            )
            if not self.dry_run:
                self.git_repo.git.fetch("origin", pr_branch)
                self.git_repo.git.checkout(pr_branch)
            return pr_branch, open_pull
        elif branch_op == BranchOp.CREATE_AND_CHECKOUT:
            log.info(
                f"[git-operator] Checking out new branch {self.git_repo.remote().name}/{pr_branch}"
            )
            if not self.dry_run:
                self.git_repo.git.checkout(self.base_branch)
                self.git_repo.git.pull("origin", self.base_branch)
                self.git_repo.head.reset(index=True, working_tree=True)
                self.git_repo.git.branch(pr_branch)
                self.git_repo.git.checkout(pr_branch)
            return pr_branch, None
        elif branch_op == BranchOp.NOP and pr_branch:
            return pr_branch, open_pull
        else:
            raise AppgateException(
                f"Unknown BranchOp operation: {branch_op} | {pr_branch}"
            )

    def create_or_update_pull_request(
        self,
        branch: str,
        pull_request: PullRequestLike | None,
        commits: Dict[str, List[Tuple[str, GitCommitState]]],
    ) -> PullRequestLike | None:
        # Try to sync with the opened pull request again here
        # It could be that someone has merged a PR that was opened before we entered the loop
        latest_opened_pull = get_sdp_gl_merge_request(self.gl_project)
        current_opened_pull = (
            get_sdp_gl_merge_request(self.gl_project, pull_request.number)
            if pull_request
            else None
        )
        pull_request_to_use = current_opened_pull
        if (
            latest_opened_pull
            and current_opened_pull
            and latest_opened_pull.number != current_opened_pull.number
        ):
            log.warning(
                "[git-operator] There is a more recent merge request for sdp-operator with id %s. Using it",
                latest_opened_pull.number,
            )
            return None
        elif not current_opened_pull and latest_opened_pull:
            log.warning(
                "[git-operator] The previous opened merge request has been closed."
                " Waiting for the next event loop to create the merge request"
            )
            return None
        if pull_request_to_use:
            # The pull request we were keeping track did not change, we can use it
            log.info(
                "[git-operator] New commits added to merge request %s",
                pull_request_to_use.title,
            )
            if not self.dry_run:
                pull_request_to_use.mr.description = get_pull_request_body(
                    commits=commits, body=pull_request_to_use.mr.description
                )
                pull_request_to_use.mr.save()
        else:
            # We need to create a new merge request for these changes
            title = f"[sdp-operator] ({time.strftime('%H:%M:%S')}) Merge changes from {branch}"
            head_branch = branch
            if self.user_fork():
                head_branch = f"{self.user_fork()}:{branch}"
            log.info("[git-operator] Creating merge request in GitLab")
            log.info("[git-operator] title: %s", title)
            log.info("[git-operator] source_branch: %s", head_branch)
            log.info("[git-operator] target_branch: %s", self.base_branch)
            log.info("[git-operator] repository: %s", self.repository)
            if self.dry_run:
                return None
            pull_request_details = {
                "source_branch": head_branch,
                "target_branch": self.base_branch,
                "title": title,
                "description": get_pull_request_body(commits=commits, body=None),
                "labels": [APPGATE_OPERATOR_PR_LABEL_NAME],
            }
            pr = self.gl_project.mergerequests.create(pull_request_details)
            if isinstance(pr, ProjectMergeRequest):
                pull_request_to_use = GitLabPullRequest(pr)

        return pull_request_to_use


@attrs(slots=True, frozen=True)
class GitHubRepo(GitRepo):
    gh: Github = attrib()
    gh_repo: Repository = attrib()

    def needs_pull_request(self) -> bool:
        return self.git_repo.is_dirty()

    def checkout_branch(
        self, previous_branch: str | None, previous_pr: PullRequestLike | None
    ) -> Tuple[str, PullRequestLike | None]:
        """
        Checkout an existing branch for a PullRequest already opened or creates a new branch
        Return the name of the branch and if it needs to create PullRequest: if the branch is
        from an already opened PullRequest this will be False
        """
        open_pull = get_sdp_pull_request(self.gh_repo)
        pr_branch, branch_op = github_checkout_branch(
            previous_branch, previous_pr, open_pull
        )
        if branch_op == BranchOp.CHECKOUT and open_pull:
            log.info(
                "[git-operator] Found opened Pull Request %s [%s]. Using it",
                open_pull.title,
                open_pull.number,
            )
            log.info(
                "[git-operator] Fetching and checking out existing branch %s/%s",
                self.git_repo.remote().name,
                pr_branch,
            )
            if not self.dry_run:
                self.git_repo.git.fetch("origin", pr_branch)
                self.git_repo.git.checkout(pr_branch)
            return pr_branch, open_pull
        elif branch_op == BranchOp.CREATE_AND_CHECKOUT:
            log.info(
                f"[git-operator] Checking out new branch {self.git_repo.remote().name}/{pr_branch}"
            )
            if not self.dry_run:
                self.git_repo.git.checkout(self.base_branch)
                self.git_repo.git.pull("origin", self.base_branch)
                self.git_repo.head.reset(index=True, working_tree=True)
                self.git_repo.git.branch(pr_branch)
                self.git_repo.git.checkout(pr_branch)
            return pr_branch, None
        elif branch_op == BranchOp.NOP and pr_branch:
            return pr_branch, open_pull
        else:
            raise AppgateException(
                f"Unknown BranchOp operation: {branch_op} | {pr_branch}"
            )

    def create_or_update_pull_request(
        self,
        branch: str,
        pull_request: PullRequestLike | None,
        commits: Dict[str, List[Tuple[str, GitCommitState]]],
    ) -> PullRequestLike | None:
        # Try to sync with the opened pull request again here
        # It could be that someone has merged a PR that was opened before we entered the loop
        latest_opened_pull = get_sdp_pull_request(self.gh_repo)
        current_opened_pull = (
            get_sdp_pull_request(self.gh_repo, pull_request.number)
            if pull_request
            else None
        )
        pull_request_to_use = current_opened_pull
        if (
            latest_opened_pull
            and current_opened_pull
            and latest_opened_pull.number != current_opened_pull.number
        ):
            log.warning(
                "[git-operator] There is a more recent pr for sdp-operator with number %s. Using it",
                latest_opened_pull.number,
            )
            return None
        elif not current_opened_pull and latest_opened_pull:
            log.warning(
                "[git-operator] The previous opened pull request has been closed."
                " Waiting for the next event loop to create the pull request"
            )
            return None
        if pull_request_to_use:
            # The pull request we were keeping track did not change, we can use it
            log.info(
                "[git-operator] New commits added to pull request %s",
                pull_request_to_use.title,
            )
            body = pull_request_to_use.pr.body
            if not self.dry_run:
                pull_request_to_use.pr.edit(
                    body=get_pull_request_body(commits=commits, body=body)
                )
        else:
            # We need to create a new pull request for these changes
            title = f"[sdp-operator] ({time.strftime('%H:%M:%S')}) Merge changes from {branch}"
            head_branch = branch
            if self.user_fork():
                head_branch = f"{self.user_fork()}:{branch}"
            log.info("[git-operator] Creating pull request in GitHub")
            log.info("[git-operator] title: %s", title)
            log.info("[git-operator] head: %s", head_branch)
            log.info("[git-operator] base: %s", self.base_branch)
            log.info("[git-operator] repository: %s", self.repository)
            if self.dry_run:
                return None
            pull_request_to_use = GitHubPullRequest(
                self.gh_repo.create_pull(
                    title=title,
                    body=get_pull_request_body(commits=commits, body=None),
                    head=head_branch,
                    base=self.base_branch,
                )
            )
            pull_request_to_use.pr.add_to_labels(get_sdp_gh_label(self.gh_repo))
        return pull_request_to_use


def create_ssh_fingerprint(known_host_file: Path, fingerprint: str) -> None:
    known_host_file.parent.mkdir(exist_ok=True)
    log.info(
        "[git-operator] Creating file with known SSH fingerprints to %s",
        known_host_file,
    )
    with known_host_file.open("w") as f:
        print(fingerprint, file=f)


def get_git_repository(ctx: GitOperatorContext) -> GitRepo:
    match ctx.git_vendor:
        case "github":
            log.info("[git-operator] Detected GitHub as git vendor type")
            create_ssh_fingerprint(ctx.git_ssh_known_hosts_file, GITHUB_SSH_FINGERPRINT)
            return github_repo(ctx)

        case "gitlab":
            log.info("[git-operator] Detected GitLab as git vendor type")
            if ctx.git_hostname and ctx.git_strict_host_key_checking:
                with open(ctx.git_ssh_host_key_fingerprint_path) as fingerprint:
                    create_ssh_fingerprint(
                        ctx.git_ssh_known_hosts_file, fingerprint.read()
                    )
            else:
                create_ssh_fingerprint(
                    ctx.git_ssh_known_hosts_file, GITLAB_SSH_FINGERPRINT
                )
            return gitlab_repo(ctx)

        case _:
            raise Exception(f"Unknown git vendor type: {ctx.git_vendor}")


@functools.cache
def entity_path(repository_path: Path, kind: str) -> Path:
    return repository_path / kind.lower()


@attrs()
class GitEntityClient(EntityClient):
    api_spec: APISpec = attrib()
    kind: str = attrib()
    repository_path: Path = attrib()
    git_repo: GitRepo = attrib()
    branch: str = attrib()
    commits: List[Tuple[Path, GitCommitState]] = attrib()
    resolution_conflicts: Dict[str, List[MissingFieldDependencies]] | None = attrib()

    def with_commit(self, state: GitCommitState, file: Path) -> "GitEntityClient":
        self.commits.append((file, state))
        return evolve(self, commits=self.commits)

    async def init(self) -> EntityClient:
        self.commits = []
        return self

    async def _create(self, e: Entity_T, register_commit: bool = True) -> EntityClient:
        p = entity_path(self.repository_path, self.kind)
        log.info(
            "[git-entity-client/%s] Creating file %s for entity %s",
            self.kind,
            p,
            e.name,
        )
        p.mkdir(exist_ok=True)
        file = git_dump(e, self.api_spec, p, self.resolution_conflicts)
        if register_commit:
            self.commits.append(
                (p, GitCommitState(entity=e, path=file, operation="ADD"))
            )
        return self

    async def create(self, e: Entity_T) -> EntityClient:
        return await self._create(e, register_commit=True)

    async def _delete(self, e: Entity_T, register_commit: bool = True) -> EntityClient:
        p: Path = entity_path(self.repository_path, self.kind) / entity_file_name(
            e.name
        )
        if register_commit:
            self.commits.append(
                (p, GitCommitState(entity=e, path=p, operation="DELETE"))
            )
        log.info(
            "[git-entity-client/%s] Removing file %s for entity %s",
            self.kind,
            p,
            e.name,
        )
        if p.exists():
            p.unlink()
        else:
            log.warning(
                "[git-entity-client/%s] File %s for entity %s should be deleted but it's not present",
                self.kind,
                p,
                e.name,
            )
        return self

    async def delete(self, e: Entity_T) -> EntityClient:
        return await self._delete(e, register_commit=True)

    async def modify(self, e: Entity_T) -> EntityClient:
        p: Path = entity_path(self.repository_path, self.kind) / entity_file_name(
            e.name
        )
        self.commits.append((p, GitCommitState(entity=e, path=p, operation="MODIFY")))
        await self._delete(e, register_commit=False)
        await self._create(e, register_commit=False)
        return self

    async def commit(self) -> Tuple[EntityClient, List[Tuple[str, GitCommitState]]]:
        if not self.commits:
            return self, []
        log.info("[git-entity-client/%s] Committing changes for entities", self.kind)
        commit_message = f"[{self.branch}] {self.kind} changes\n\nChanges:"
        for p, o in self.commits:
            match o.operation:
                case "ADD":
                    log.info(
                        "[git-entity-client/%s] + New commit: Added file  %s",
                        self.kind,
                        p,
                    )
                    self.git_repo.git_repo.index.add([str(p)])
                case "DELETE":
                    log.info(
                        "[git-entity-client/%s] - New commit: Deleted file %s",
                        self.kind,
                        p,
                    )
                    self.git_repo.git_repo.index.remove([str(p)])
                case "MODIFY":
                    log.info(
                        "[git-entity-client/%s] * New commit: Modified file %s",
                        self.kind,
                        p,
                    )
                    self.git_repo.git_repo.index.add([str(p)])
            commit_message += f"\n  - {o.get_commit_message()}"
        self.git_repo.git_repo.index.commit(message=commit_message)
        cs = [(str(k), v) for (k, v) in self.commits]
        self.commits = []
        return self, cs
