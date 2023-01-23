import asyncio
from asyncio import Queue
import os
from pathlib import Path
import sys
from typing import List, Optional, Callable, Dict, Tuple

from kubernetes.config import ConfigException

from appgate.logger import log
from appgate.openapi.openapi import SPEC_DIR, generate_api_spec
from appgate.operator import init_kubernetes, run_k8s
from appgate.secrets import k8s_get_secret
from appgate.types import (
    AppgateEvent,
    AppgateEventError,
    EntityWrapper,
    GitOperatorContext,
    GitOperatorArguments,
    NAMESPACE_ENV,
    SPEC_DIR_ENV,
    APPGATE_SECRETS_KEY,
    TIMEOUT_ENV,
    get_tags,
    APPGATE_TARGET_TAGS_ENV,
    get_dry_run,
    ensure_env,
    GIT_REPOSITORY_ENV,
    GIT_VENDOR_ENV,
    GIT_BASE_BRANCH_ENV,
    GIT_DUMP_DIR,
    APPGATE_LOG_LEVEL,
    GIT_REPOSITORY_FORK_ENV,
    BUILTIN_TAGS,
    EntityClient,
    is_target,
    GitCommitState,
    GIT_REPOSITORY_MAIN_BRANCH_ENV,
    GIT_REPOSITORY_MAIN_BRANCH,
)
from appgate.openapi.types import (
    AppgateException,
    APISpec,
    MissingFieldDependencies,
)
from appgate.state import (
    appgate_state_empty,
    create_appgate_plan,
    appgate_plan_apply,
    resolve_appgate_state,
    entities_conflict_summary,
)
from appgate.syncer.git import (
    get_git_repository,
    GitRepo,
    get_current_branch_state,
    GitEntityClient,
)


def git_operator_context(
    args: GitOperatorArguments,
    k8s_get_secret: Optional[Callable[[str, str], str]] = None,
    namespace: str | None = None,
) -> GitOperatorContext:
    namespace = namespace or args.namespace or os.getenv(NAMESPACE_ENV)
    spec_directory = os.getenv(SPEC_DIR_ENV) or args.spec_directory or SPEC_DIR
    secrets_key = os.getenv(APPGATE_SECRETS_KEY)
    api_spec = generate_api_spec(
        spec_directory=Path(spec_directory) if spec_directory else None,
        secrets_key=secrets_key,
        k8s_get_secret=k8s_get_secret,
        operator_mode="git-operator",
    )
    if not namespace:
        raise AppgateException(
            "Namespace must be defined in order to run the git-operator"
        )
    dry_run_mode = get_dry_run(args.no_dry_run)
    return GitOperatorContext(
        namespace=namespace,
        api_spec=api_spec,
        timeout=int(os.getenv(TIMEOUT_ENV) or args.timeout),
        target_tags=get_tags(args.target_tags, os.getenv(APPGATE_TARGET_TAGS_ENV)),
        dry_run=dry_run_mode,
        git_vendor=ensure_env(GIT_VENDOR_ENV),
        git_repository=ensure_env(GIT_REPOSITORY_ENV),
        git_base_branch=ensure_env(GIT_BASE_BRANCH_ENV),
        log_level=os.environ.get(APPGATE_LOG_LEVEL, "info"),
        git_repository_fork=os.environ.get(GIT_REPOSITORY_FORK_ENV),
        main_branch=os.environ.get(
            GIT_REPOSITORY_MAIN_BRANCH_ENV, GIT_REPOSITORY_MAIN_BRANCH
        ),
    )


async def run_git_operator(args: GitOperatorArguments) -> None:
    try:
        ns = init_kubernetes(args.namespace)
    except ConfigException as e:
        raise AppgateException(f"Unable to load kube config: {e}")
    ctx = git_operator_context(
        args=args,
        k8s_get_secret=lambda secret, key: k8s_get_secret(
            namespace=ns, key=key, secret=secret
        ),
        namespace=ns,
    )
    events_queue: Queue[AppgateEvent] = asyncio.Queue()
    operator = git_operator(queue=events_queue, ctx=ctx)
    await run_k8s(
        queue=events_queue,
        namespace=ctx.namespace,
        api_spec=ctx.api_spec,
        k8s_configmap_client=None,
        operator=operator,
    )


def print_configuration(ctx: GitOperatorContext):
    log.info(
        "[git-operator] Starting Git Syncer loop with the following configuration: "
    )
    log.info(
        "[git-operator]     Target tags: %s",
        ",".join(ctx.target_tags) if ctx.target_tags else "None",
    )
    log.info("[git-operator]     Log level: %s", ctx.log_level)
    log.info("[git-operator]     Timeout: %s", ctx.timeout)
    log.info(
        "[git-operator]     Git repository: %s",
        ctx.git_repository,
    )
    log.info(
        "[git-operator]     Git repository fork: %s", ctx.git_repository_fork or "None"
    )
    log.info("[git-operator]     Git vendor: %s", ctx.git_vendor)
    log.info("[git-operator]     Git base branch: %s", ctx.git_base_branch)
    log.info("[git-operator]     Dry-run mode: %s", ctx.dry_run)


def generate_git_entity_clients(
    api_spec: APISpec,
    repository_path: Path,
    branch: str,
    git: GitRepo,
    resolution_conflicts: Dict[str, List[MissingFieldDependencies]],
) -> Dict[str, EntityClient | None]:
    return {
        k: GitEntityClient(
            api_spec=api_spec,
            kind=k,
            repository_path=repository_path,
            branch=branch,
            git_repo=git,
            commits=[],
            resolution_conflicts=resolution_conflicts,
        )
        for k in api_spec.api_entities.keys()
    }


async def git_operator(queue: Queue, ctx: GitOperatorContext) -> None:
    error_events: List[AppgateEventError] = []
    git: GitRepo = get_git_repository(ctx)
    log.info("[git-operator] Loading current state")
    # Checkout to existing branch or create a new one if needed and get current state
    branch, pull_request = git.checkout_branch(previous_branch=None, previous_pr=None)
    current_state = get_current_branch_state(ctx.api_spec, GIT_DUMP_DIR)
    expected_state = appgate_state_empty(ctx.api_spec)
    print_configuration(ctx)
    git_entity_clients = None
    while True:
        try:
            event: AppgateEvent = await asyncio.wait_for(
                queue.get(), timeout=ctx.timeout
            )

            if isinstance(event, AppgateEventError):
                error_events.append(event)
                continue

            log.info(
                '[git-operator] Event: %s entity of type %s "%s"',
                event.op,
                event.entity.__class__.__qualname__,
                event.entity.name,
            )
            if ctx.target_tags and is_target(
                EntityWrapper(event.entity), ctx.target_tags
            ):
                expected_state.with_entity(
                    EntityWrapper(event.entity),
                    event.op,
                    current_appgate_state=expected_state,
                )
            else:
                log.info(
                    '[git-operator] Ignoring event: %s entity of type %s "%s"',
                    event.op,
                    event.entity.__class__.__qualname__,
                    event.entity.name,
                )
        except asyncio.exceptions.TimeoutError:
            if error_events:
                for event_error in error_events:
                    log.error(
                        "[git-operator] Entity of type %s %s: %s",
                        event_error.name,
                        event_error.kind,
                        event_error.error,
                    )
                sys.exit(1)
            total_conflicts = resolve_appgate_state(
                expected_state,
                expected_state.copy(expected_state.entities_set),
                ctx.api_spec,
                reverse=True,
            )
            if total_conflicts:
                log.warning(
                    "[git-operator/%s] Found errors when resolving dependencies in entities."
                    " Some reference ids in entities won't be resolved to their respective names.",
                    ctx.namespace,
                )
                entities_conflict_summary(
                    conflicts=total_conflicts, namespace=ctx.namespace
                )
            plan = create_appgate_plan(
                current_state=current_state,
                expected_state=expected_state,
                builtin_tags=BUILTIN_TAGS,
                target_tags=ctx.target_tags,
                excluded_tags=None,
            )
            commits: Dict[str, List[Tuple[str, GitCommitState]]] = {}
            if plan.needs_apply:
                log.info("[git-operator] Applying plan")
                if not git_entity_clients:
                    git_entity_clients = generate_git_entity_clients(
                        api_spec=ctx.api_spec,
                        repository_path=GIT_DUMP_DIR,
                        branch=branch,
                        git=git,
                        resolution_conflicts=total_conflicts,
                    )
                new_plan, git_entity_clients = await appgate_plan_apply(
                    appgate_plan=plan,
                    namespace="git-operator",
                    operator_name="git-operator",
                    entity_clients=git_entity_clients,
                    api_spec=ctx.api_spec,
                )
                if len(new_plan.errors) > 0:
                    log.error("[git-operator] Found errors when applying plan:")
                    for err in new_plan.errors:
                        log.error("[git-operator] Error %s:", err)
                    sys.exit(1)

                # This creates a commit for each plan application
                # TODO: Implement the option of doing commits per entity or per entity_type
                for e, c in git_entity_clients.items():
                    if c:
                        _, cs = await c.commit()
                        commits[e] = cs
            if len(commits) > 0:
                git.push_change(branch)
                log.info("[git-operator] New commits it git repository")
                git.create_or_update_pull_request(branch, pull_request, commits)
            else:
                log.info(
                    "[git-operator] No changes in the git repository. Sleeping %s seconds",
                    ctx.timeout,
                )
            log.info("[git-operator] Loading current state")
            current_state = get_current_branch_state(ctx.api_spec, GIT_DUMP_DIR)
            branch, pull_request = git.checkout_branch(
                previous_branch=branch, previous_pr=pull_request
            )


def main_git_operator(args: GitOperatorArguments) -> None:
    try:
        asyncio.run(run_git_operator(args))
    except AppgateException as e:
        log.error("[git-operator] Fatal error: %s", e)
