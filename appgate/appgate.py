import asyncio
import sys
from asyncio import Queue
from copy import deepcopy
from typing import Optional, Dict

from kubernetes.client import CustomObjectsApi

from appgate.openapi import openapi
from appgate.types import (
    AppgateOperatorContext,
    AppgateEventError,
    EntityClient,
    OperatorMode,
    get_operator_mode,
)
from appgate.logger import log
from appgate.client import (
    AppgateClient,
    K8SConfigMapClient,
    K8sEntityClient,
    AppgateEntityClient,
)
from appgate.openapi.types import (
    AppgateException,
    APISpec,
)
from appgate.openapi.types import (
    K8S_APPGATE_VERSION,
)
from appgate.state import (
    AppgateState,
    create_appgate_plan,
    appgate_plan_apply,
    EntitiesSet,
    entities_conflict_summary,
    resolve_appgate_state,
    exclude_appgate_entity,
    appgate_state_empty,
)
from appgate.types import AppgateEvent, EntityWrapper


__all__ = [
    "appgate_operator",
    "get_current_appgate_state",
    "get_crds",
]


crds: Optional[CustomObjectsApi] = None


def get_crds() -> CustomObjectsApi:
    global crds
    if not crds:
        crds = CustomObjectsApi()
    return crds


async def get_current_appgate_state(
    ctx: AppgateOperatorContext, appgate_client: AppgateClient
) -> AppgateState:
    """
    Gets the current AppgateState for controller
    """
    api_spec = ctx.api_spec
    log.info(
        "[appgate-operator/%s] Updating current state from controller", ctx.namespace
    )
    if ctx.no_verify:
        log.warning("[appgate-operator/%s] Ignoring SSL certificates!", ctx.namespace)
    if ctx.device_id is None:
        raise AppgateException("No device id specified")
    if not appgate_client.authenticated:
        log.error(
            "[appgate-operator/%s] Unable to authenticate with controller",
            ctx.namespace,
        )
        raise AppgateException("Error authenticating")

    entity_clients = openapi.generate_api_spec_clients(
        api_spec=api_spec, appgate_client=appgate_client
    )
    entities_set = {}
    for entity, client in entity_clients.items():
        assert isinstance(client, AppgateEntityClient)
        entities = await client.get()
        if entities is not None:
            entities_set[entity] = EntitiesSet({EntityWrapper(e) for e in entities})
    if len(entities_set) < len(entity_clients):
        log.error(
            "[appgate-operator/%s] Unable to get entities from controller",
            ctx.namespace,
        )
        raise AppgateException("Error reading current state")
    appgate_state = AppgateState(entities_set=entities_set)

    return appgate_state


def generate_k8s_clients(
    api_spec: APISpec, namespace: str, k8s_api: CustomObjectsApi
) -> Dict[str, EntityClient | None]:
    return {
        k: K8sEntityClient(
            k8s_api=k8s_api,
            api_spec=api_spec,
            crd_version=K8S_APPGATE_VERSION,
            namespace=namespace,
            kind=k,
        )
        for k in api_spec.api_entities.keys()
    }


async def appgate_operator(
    queue: Queue,
    ctx: AppgateOperatorContext,
    k8s_configmap_client: K8SConfigMapClient,
    appgate_client: AppgateClient,
) -> None:
    namespace = ctx.namespace
    operator_name: OperatorMode = get_operator_mode(ctx.reverse_mode)
    log.info("[%s/%s] Main loop started:", operator_name, namespace)
    log.info("[%s/%s]   + namespace: %s", operator_name, namespace, namespace)
    log.info("[%s/%s]   + host: %s", operator_name, namespace, ctx.controller)
    log.info("[%s/%s]   + reverse mode: %s", operator_name, namespace, ctx.reverse_mode)
    log.info("[%s/%s]   + log-level: %s", operator_name, namespace, log.level)
    log.info("[%s/%s]   + timeout: %s", operator_name, namespace, ctx.timeout)
    log.info("[%s/%s]   + dry-run: %s", operator_name, namespace, ctx.dry_run_mode)
    log.info("[%s/%s]   + cleanup: %s", operator_name, namespace, ctx.cleanup_mode)
    log.info("[%s/%s]   + two-way-sync: %s", operator_name, namespace, ctx.two_way_sync)
    log.info(
        "[%s/%s]   + entities-included: %s",
        operator_name,
        namespace,
        ",".join(ctx.api_spec.entities_to_include or frozenset()),
    )
    log.info(
        "[%s/%s]   + entities-excluded: %s",
        operator_name,
        namespace,
        ",".join(ctx.api_spec.entities_to_exclude or frozenset()),
    )
    log.info(
        "[%s/%s]   + builtin tags: %s",
        operator_name,
        namespace,
        ",".join(ctx.builtin_tags),
    )
    log.info(
        "[%s/%s]   + target tags: %s",
        operator_name,
        namespace,
        ",".join(ctx.target_tags) if ctx.target_tags else "None",
    )
    log.info(
        "[%s/%s]   + exclude tags: %s",
        operator_name,
        namespace,
        ",".join(ctx.exclude_tags) if ctx.exclude_tags else "None",
    )
    log.info("[%s/%s] Getting current state from controller", operator_name, namespace)

    # Get current and total state
    if ctx.reverse_mode:
        current_appgate_state = appgate_state_empty(ctx.api_spec)
        expected_appgate_state = await get_current_appgate_state(
            ctx=ctx, appgate_client=appgate_client
        )
        total_appgate_state = deepcopy(expected_appgate_state)
        if ctx.target_tags:
            expected_appgate_state = AppgateState(
                {
                    k: v.entities_with_tags(ctx.target_tags)
                    for k, v in expected_appgate_state.entities_set.items()
                }
            )
        if ctx.cleanup_mode:
            log.error("Reverse operator can not run in clean-up mode!")
            exit(1)
    else:
        current_appgate_state = await get_current_appgate_state(
            ctx=ctx, appgate_client=appgate_client
        )
        total_appgate_state = deepcopy(current_appgate_state)
        if ctx.target_tags:
            expected_appgate_state = AppgateState(
                {
                    k: v.entities_with_tags(ctx.target_tags)
                    for k, v in current_appgate_state.entities_set.items()
                }
            )
        else:
            expected_appgate_state = deepcopy(current_appgate_state)
        if ctx.cleanup_mode:
            tags_in_cleanup = ctx.builtin_tags.union(ctx.exclude_tags or frozenset())
            expected_appgate_state = AppgateState(
                {
                    k: v.entities_with_tags(tags_in_cleanup)
                    for k, v in current_appgate_state.entities_set.items()
                }
            )
    log.info(
        "[%sr/%s] Ready to get new events and compute a new plan",
        operator_name,
        namespace,
    )
    event_errors = []
    while True:
        try:
            log.info("[%s/%s] Waiting for event", operator_name, namespace)
            event: AppgateEvent = await asyncio.wait_for(
                queue.get(), timeout=ctx.timeout
            )
            if isinstance(event, AppgateEventError):
                event_errors.append(event)
            else:
                log.info(
                    "[%s/%s] Event: %s %s with name %s",
                    operator_name,
                    namespace,
                    event.op,
                    event.entity.__class__.__qualname__,
                    event.entity.name,
                )
                if ctx.reverse_mode:
                    current_appgate_state.with_entity(
                        EntityWrapper(event.entity), event.op, expected_appgate_state
                    )
                else:
                    expected_appgate_state.with_entity(
                        EntityWrapper(event.entity), event.op, current_appgate_state
                    )
        except asyncio.exceptions.TimeoutError:
            if event_errors:
                log.error(
                    "[%s/%s] Found events with errors, dying now!",
                    operator_name,
                    namespace,
                )
                for event_error in event_errors:
                    log.error(
                        "[%s/%s] - Entity of type %s with name %s : %s",
                        operator_name,
                        namespace,
                        event_error.name,
                        event_error.kind,
                        event_error.error,
                    )
                sys.exit(1)
            # Log all expected entities
            any_expected = False
            for entity_type, xs in expected_appgate_state.entities_set.items():
                expected_entities = {
                    n: e
                    for n, e in xs.entities_by_name.items()
                    if exclude_appgate_entity(e, ctx.target_tags, ctx.exclude_tags)
                }
                for entity_name, e in expected_entities.items():
                    if not any_expected:
                        log.info("[%s/%s] Expected entities:", operator_name, namespace)
                        any_expected = True
                    log.info(
                        "[%s/%s] %s: %s: %s",
                        operator_name,
                        namespace,
                        entity_type,
                        entity_name,
                        e.id,
                    )
            if not any_expected:
                log.warning("[%s/%s] Not expected any entity", operator_name, namespace)

            # Resolve entities now, in order
            # this will be the Topological sort
            total_conflicts = resolve_appgate_state(
                expected_state=expected_appgate_state,
                total_appgate_state=total_appgate_state,
                reverse=False,
                api_spec=ctx.api_spec,
            )
            if total_conflicts:
                log.error(
                    "[%s/%s] Found errors in expected state and plan can"
                    " not be applied.",
                    operator_name,
                    namespace,
                )
                entities_conflict_summary(
                    conflicts=total_conflicts, namespace=namespace
                )
                log.info(
                    "[%s/%s] Waiting for more events that can fix the state.",
                    operator_name,
                    namespace,
                )
                continue

            if not ctx.reverse_mode and ctx.two_way_sync:
                # use current appgate state from controller instead of from memory
                current_appgate_state = await get_current_appgate_state(
                    ctx=ctx, appgate_client=appgate_client
                )
                total_appgate_state = deepcopy(current_appgate_state)

            # Create a plan
            # Need to copy?
            # Now we use dicts so resolving update the contents of the keys
            log.info(
                "[%s/%s] No more events for a while, creating a plan",
                operator_name,
                namespace,
            )
            plan = create_appgate_plan(
                current_appgate_state,
                expected_appgate_state,
                ctx.builtin_tags,
                ctx.target_tags,
                ctx.exclude_tags,
            )
            if plan.needs_apply:
                log.info(
                    "[%s/%s] New plan contains changes, applying it.",
                    operator_name,
                    namespace,
                )
                entity_clients = None
                if not ctx.dry_run_mode and not ctx.reverse_mode:
                    entity_clients = openapi.generate_api_spec_clients(
                        api_spec=ctx.api_spec, appgate_client=appgate_client
                    )
                if not ctx.dry_run_mode and ctx.reverse_mode:
                    entity_clients = generate_k8s_clients(
                        api_spec=ctx.api_spec,
                        namespace=ctx.namespace,
                        k8s_api=get_crds(),
                    )

                new_plan, entity_clients = await appgate_plan_apply(
                    appgate_plan=plan,
                    namespace=namespace,
                    operator_name=operator_name,
                    entity_clients=entity_clients,
                    k8s_configmap_client=k8s_configmap_client,
                    api_spec=ctx.api_spec,
                )

                if len(new_plan.errors) > 0:
                    log.error(
                        "[%s/%s] Found errors when applying plan:",
                        operator_name,
                        namespace,
                    )
                    for err in new_plan.errors:
                        log.error("[%s/%s] Error %s:", operator_name, namespace, err)
                    sys.exit(1)

                if not ctx.dry_run_mode and not ctx.reverse_mode:
                    current_appgate_state = new_plan.appgate_state
                    expected_appgate_state = expected_appgate_state.sync_generations()
                elif not ctx.dry_run_mode and ctx.reverse_mode:
                    current_appgate_state = new_plan.appgate_state
            else:
                log.info(
                    "[%s/%s] Nothing changed! Keeping watching!",
                    operator_name,
                    namespace,
                )
                if ctx.reverse_mode:
                    expected_appgate_state = await get_current_appgate_state(
                        ctx=ctx, appgate_client=appgate_client
                    )
                    if ctx.target_tags:
                        expected_appgate_state = AppgateState(
                            {
                                k: v.entities_with_tags(ctx.target_tags)
                                for k, v in expected_appgate_state.entities_set.items()
                            }
                        )


async def main_loop(
    queue: Queue, ctx: AppgateOperatorContext, k8s_configmap_client: K8SConfigMapClient
) -> None:
    if ctx.device_id is None:
        raise AppgateException("No device id specified")

    async with AppgateClient(
        controller=ctx.controller,
        user=ctx.user,
        password=ctx.password,
        provider=ctx.provider,
        device_id=ctx.device_id,
        version=ctx.api_spec.api_version,
        no_verify=ctx.no_verify,
        cafile=ctx.cafile,
        expiration_time_delta=ctx.timeout,
        dry_run=ctx.dry_run_mode,
    ) as appgate_client:
        await appgate_operator(queue, ctx, k8s_configmap_client, appgate_client)
