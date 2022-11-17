import asyncio
from asyncio import Queue
import os
from pathlib import Path
import sys
import yaml
from typing import List

from appgate.logger import log, set_level
from appgate.types import (
    OperatorArguments,
    Context,
    AppgateEvent,
    AppgateEventError,
    EntityWrapper,
)
from appgate.__main__ import init_kubernetes, APPGATE_LOG_LEVEL
from appgate.client import K8SConfigMapClient
from appgate.appgate import start_entity_loop
from appgate.openapi.openapi import entity_names
from appgate.openapi.types import (
    APPGATE_METADATA_ATTRIB_NAME,
    APPGATE_METADATA_PASSWORD_FIELDS_FIELD,
    Entity_T,
)
from appgate.state import dump_entity
from appgate.syncer.git import get_git_repository, GitRepo


DUMP_DIR: Path = Path("/entities")


async def run_git_syncer(args: OperatorArguments):
    ctx = init_kubernetes(args)
    events_queue: Queue[AppgateEvent] = asyncio.Queue()
    k8s_configmap_client = K8SConfigMapClient(
        namespace=ctx.namespace, name=ctx.metadata_configmap
    )
    await k8s_configmap_client.init()

    tasks = [
        start_entity_loop(
            ctx=ctx,
            queue=events_queue,
            crd=entity_names(e.cls, {}, f"v{ctx.api_spec.api_version}")[2],
            singleton=e.singleton,
            entity_type=e.cls,
            k8s_configmap_client=k8s_configmap_client,
        )
        for e in ctx.api_spec.entities.values()
        if e.api_path
    ] + [main_loop(events_queue, ctx)]

    await asyncio.gather(*tasks)


def dump(ctx: Context, entity: Entity_T):
    dumped_entities: List[str] = []
    entity_type = entity.__class__.__qualname__.lower()

    entity_dir = DUMP_DIR / f"{entity_type}-{ctx.api_spec.api_version}"
    entity_dir.mkdir(exist_ok=True)
    entity_file = entity_dir / f"{entity.name.lower().replace(' ', '-')}.yaml"
    dumped_entity = dump_entity(
        EntityWrapper(entity), entity_type, str(ctx.api_spec.api_version)
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


def print_configuration(ctx: Context):
    log.info("[git-syncer] Starting Git Syncer loop with the following configuration: ")
    log.info(
        "[git-syncer]     Target tags: %s",
        ",".join(ctx.target_tags) if ctx.target_tags else "None",
    )
    log.info("[git-syncer]     Log level: %s", os.getenv(APPGATE_LOG_LEVEL, "info"))
    log.info("[git-syncer]     Timeout: %s", ctx.timeout)
    log.info("[git-syncer]     Git repository: %s", os.getenv("GIT_REPOSITORY_URL", ""))
    log.info("[git-syncer]     Git vendor: %s", os.getenv("GIT_VENDOR", ""))
    log.info("[git-syncer]     Git username: %s", os.getenv("GIT_USERNAME", ""))
    log.info("[git-syncer]     Git base branch: %s", os.getenv("GIT_BASE_BRANCH", ""))


async def main_loop(queue: Queue, ctx: Context) -> None:
    entities: List[Entity_T] = []
    error_events: List[AppgateEventError] = []

    git: GitRepo = get_git_repository()
    git.check_env_vars()
    git.clone_repository(DUMP_DIR)

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
                '[git-syncer] Event: %s entity of type %s "%s"',
                event.op,
                event.entity.__class__.__qualname__,
                event.entity.name,
            )
            entities.append(event.entity)

        except asyncio.exceptions.TimeoutError:
            if error_events:
                for event_error in error_events:
                    log.error(
                        "[git-syncer] Entity of type %s %s: %s",
                        event_error.name,
                        event_error.kind,
                        event_error.error,
                    )
                sys.exit(1)

            git.checkout_branch()

            for entity in entities:
                dump(ctx, entity)

            if git.needs_pull_request():
                log.info("[git-syncer] Found changes in the git repository")
                git.commit_change()
                git.push_change()
                git.create_pull_request()
            else:
                log.info(
                    f"[git-syncer] No changes in the git repository. Sleeping {ctx.timeout} seconds"
                )


if __name__ == "__main__":
    try:
        set_level(log_level=os.getenv(APPGATE_LOG_LEVEL, "info"))
        asyncio.run(run_git_syncer(OperatorArguments()))
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(1)
