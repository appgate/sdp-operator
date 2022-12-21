import asyncio
import time
from asyncio import Queue
import os
import datetime
from pathlib import Path
import sys
import yaml
from typing import List, Optional, Callable

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
    GIT_BASE_BRANCH_ENV, GIT_DUMP_DIR, GITHUB_USERNAME_ENV, APPGATE_LOG_LEVEL,
)
from appgate.openapi.types import (
    APPGATE_METADATA_ATTRIB_NAME,
    APPGATE_METADATA_PASSWORD_FIELDS_FIELD,
    Entity_T,
    AppgateException,
)
from appgate.state import dump_entity
from appgate.syncer.git import get_git_repository, GitRepo


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
        target_tags=get_tags(args.target_tags, APPGATE_TARGET_TAGS_ENV),
        dry_run=dry_run_mode,
        git_username=os.environ.get(GITHUB_USERNAME_ENV),
        git_vendor=ensure_env(GIT_VENDOR_ENV),
        git_repository=ensure_env(GIT_REPOSITORY_ENV),
        git_base_branch=ensure_env(GIT_BASE_BRANCH_ENV),
        log_level=os.environ.get(APPGATE_LOG_LEVEL, "info"),
    )


async def run_git_operator(args: GitOperatorArguments) -> None:
    try:
        ns = init_kubernetes(args.namespace)
    except ConfigException as e:
        raise AppgateException(f"Unable to find kube config file: {e}")
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


def dump(ctx: GitOperatorContext, entity: Entity_T):
    dumped_entities: List[str] = []
    entity_type = entity.__class__.__qualname__

    entity_dir = GIT_DUMP_DIR / f"{entity_type.lower()}-v{ctx.api_spec.api_version}"
    entity_dir.mkdir(exist_ok=True)
    entity_file = entity_dir / f"{entity.name.lower().replace(' ', '-')}.yaml"
    dumped_entity = dump_entity(
        EntityWrapper(entity), entity_type, f"v{ctx.api_spec.api_version}"
    )

    appgate_metadata = dumped_entity["spec"].get(APPGATE_METADATA_ATTRIB_NAME)
    if appgate_metadata:
        entity_passwords = appgate_metadata.get(APPGATE_METADATA_PASSWORD_FIELDS_FIELD)
    dumped_entities.append(
        yaml.safe_dump(dumped_entity, default_flow_style=False, sort_keys=True)
    )
    with entity_file.open("w") as f:
        for i, de in enumerate(dumped_entities):
            if i > 0:
                f.write("---\n")
            f.write(de)


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
    log.info("[git-operator]     Git vendor: %s", ctx.git_vendor)
    log.info("[git-operator]     Git username: %s", ctx.git_username)
    log.info("[git-operator]     Git base branch: %s", ctx.git_base_branch)


async def git_operator(queue: Queue, ctx: GitOperatorContext) -> None:
    entities: List[Entity_T] = []
    error_events: List[AppgateEventError] = []

    git: GitRepo = get_git_repository(ctx)
    print_configuration(ctx)

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
            entities.append(event.entity)

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

            branch = f'{str(datetime.date.today())}.{time.strftime("%H-%M-%S")}'
            git.checkout_branch(branch)

            for entity in entities:
                dump(ctx, entity)

            if git.needs_pull_request():
                log.info("[git-operator] Found changes in the git repository")
                git.commit_change(branch)
                git.push_change(branch)
                git.create_pull_request(branch)
            else:
                log.info(
                    f"[git-operator] No changes in the git repository. Sleeping {ctx.timeout} seconds"
                )


def main_git_operator(args: GitOperatorArguments) -> None:
    try:
        asyncio.run(run_git_operator(args))
    except AppgateException as e:
        log.error("[git-operator] Fatal error: %s", e)
