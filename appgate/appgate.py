import asyncio
import sys
from asyncio import Queue
from contextlib import AsyncExitStack
from copy import deepcopy
from typing import Optional, Type, Dict, Callable, Any
import threading

from kubernetes.client.rest import ApiException
from kubernetes.client import CustomObjectsApi
from kubernetes.watch import Watch

from appgate.types import Context, AppgateEventSuccess, AppgateEventError
from appgate.logger import log
from appgate.attrs import K8S_LOADER, dump_datetime
from appgate.client import (
    AppgateClient,
    K8SConfigMapClient,
    entity_unique_id,
    K8sEntityClient,
)
from appgate.openapi.types import AppgateException, AppgateTypedloadException
from appgate.openapi.openapi import generate_api_spec_clients
from appgate.openapi.types import (
    Entity_T,
    K8S_APPGATE_VERSION,
    K8S_APPGATE_DOMAIN,
    APPGATE_METADATA_LATEST_GENERATION_FIELD,
    APPGATE_METADATA_MODIFICATION_FIELD,
)
from appgate.state import (
    AppgateState,
    create_appgate_plan,
    appgate_plan_apply,
    EntitiesSet,
    entities_conflict_summary,
    resolve_appgate_state,
    exclude_appgate_entity,
)
from appgate.types import K8SEvent, AppgateEvent, EntityWrapper, EventObject


__all__ = [
    "operator",
    "get_current_appgate_state",
    "start_entity_loop",
    "get_operator_name",
]


crds: Optional[CustomObjectsApi] = None


def get_crds() -> CustomObjectsApi:
    global crds
    if not crds:
        crds = CustomObjectsApi()
    return crds


def get_operator_name(reverse_mode: bool) -> str:
    operator_name = "appgate-operator"
    if reverse_mode:
        operator_name = "appgate-reverse-operator"
    return operator_name


async def get_current_appgate_state(ctx: Context) -> AppgateState:
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
    async with AppgateClient(
        controller=ctx.controller,
        user=ctx.user,
        password=ctx.password,
        provider=ctx.provider,
        device_id=ctx.device_id,
        version=api_spec.api_version,
        no_verify=ctx.no_verify,
        cafile=ctx.cafile,
    ) as appgate_client:
        if not appgate_client.authenticated:
            log.error(
                "[appgate-operator/%s] Unable to authenticate with controller",
                ctx.namespace,
            )
            raise AppgateException("Error authenticating")

        entity_clients = generate_api_spec_clients(
            api_spec=api_spec, appgate_client=appgate_client
        )
        entities_set = {}
        for entity, client in entity_clients.items():
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


def run_entity_loop(
    ctx: Context,
    crd: str,
    loop: asyncio.AbstractEventLoop,
    queue: Queue[AppgateEvent],
    load: Callable[[Dict[str, Any], Optional[Dict[str, Any]], type], Entity_T],
    entity_type: type,
    singleton: bool,
    k8s_configmap_client: K8SConfigMapClient,
):
    namespace = ctx.namespace
    log.info(f"[{crd}/{namespace}] Loop for {crd}/{namespace} started")
    watcher = Watch().stream(
        get_crds().list_namespaced_custom_object,
        K8S_APPGATE_DOMAIN,
        K8S_APPGATE_VERSION,
        namespace,
        crd,
    )
    while True:
        try:
            data = next(watcher)
            data_obj = data["object"]
            data_mt = data_obj["metadata"]
            kind = data_obj["kind"]
            spec = data_obj["spec"]
            event = EventObject(metadata=data_mt, spec=spec, kind=kind)
            if singleton:
                name = "singleton"
            else:
                name = event.spec["name"]
            if event:
                assert data["type"] in ("ADDED", "DELETED", "MODIFIED")
                ev = K8SEvent(data["type"], event)
                try:
                    # names are not unique between entities, so we need to come up with a unique name now
                    mt = ev.object.metadata
                    latest_entity_generation = (
                        k8s_configmap_client.read_entity_generation(
                            entity_unique_id(kind, name)
                        )
                    )
                    if latest_entity_generation:
                        mt[
                            APPGATE_METADATA_LATEST_GENERATION_FIELD
                        ] = latest_entity_generation.generation
                        mt[APPGATE_METADATA_MODIFICATION_FIELD] = dump_datetime(
                            latest_entity_generation.modified
                        )
                    entity = load(ev.object.spec, ev.object.metadata, entity_type)
                    log.debug(
                        "[%s/%s] K8SEvent type: %s: %s", crd, namespace, ev.type, entity
                    )
                    appgate_event: AppgateEvent = AppgateEventSuccess(
                        op=ev.type, entity=entity
                    )
                except AppgateTypedloadException as e:
                    log.error(
                        "[%s/%s] Unable to parse event with name %s of type %s",
                        crd,
                        namespace,
                        event.spec["name"],
                        event.kind,
                    )
                    log.error(
                        "[%s/%s]%s!!! Error message: %s",
                        crd,
                        namespace,
                        " " * 4,
                        e.message,
                    )
                    log.error(
                        "[%s/%s]%s!!! Error when loading from: %s",
                        crd,
                        namespace,
                        " " * 4,
                        e.platform_type,
                    )
                    log.error(
                        "[%s/%s]%s!!! Error when loading type: %s",
                        crd,
                        namespace,
                        " " * 4,
                        e.type_.__qualname__ if e.type_ else "Unknown",
                    )
                    log.error(
                        "[%s/%s]%s!!! Error when loading value: %s",
                        crd,
                        namespace,
                        " " * 4,
                        e.value,
                    )
                    appgate_event = AppgateEventError(
                        name=event.spec["name"], kind=event.kind, error=str(e)
                    )

                asyncio.run_coroutine_threadsafe(queue.put(appgate_event), loop)
        except ApiException:
            log.exception(
                "[appgate-operator/%s] Error when subscribing events in k8s for %s",
                namespace,
                crd,
            )
            sys.exit(1)
        except StopIteration:
            log.debug(
                "[appgate-operator/%s] Event loop stopped, re-initializing watchers",
                namespace,
            )
            watcher = Watch().stream(
                get_crds().list_namespaced_custom_object,
                K8S_APPGATE_DOMAIN,
                K8S_APPGATE_VERSION,
                namespace,
                crd,
            )
        except Exception:
            log.exception(
                "[appgate-operator/%s] Unhandled error for %s", namespace, crd
            )
            sys.exit(1)


async def start_entity_loop(
    ctx: Context,
    crd: str,
    entity_type: Type[Entity_T],
    singleton: bool,
    queue: Queue[AppgateEvent],
    k8s_configmap_client: K8SConfigMapClient,
) -> None:
    log.debug(
        "[%s/%s] Starting loop event for entities on path: %s", crd, ctx.namespace, crd
    )

    def run(loop: asyncio.AbstractEventLoop) -> None:
        t = threading.Thread(
            target=run_entity_loop,
            args=(
                ctx,
                crd,
                loop,
                queue,
                K8S_LOADER.load,
                entity_type,
                singleton,
                k8s_configmap_client,
            ),
            daemon=True,
        )
        t.start()

    await asyncio.to_thread(run, asyncio.get_event_loop())


def generate_k8s_clients(api_spec: APISpec, namespace: str, k8s_api: CustomObjectsApi) ->  Dict[str, K8sEntityClient]:
    return {k: K8sEntityClient(
            api=k8s_api,
            domain=K8S_APPGATE_DOMAIN,
            version=K8S_APPGATE_VERSION,
            namespace=namespace,
            kind=f"{k}-v{api_spec.api_version}",
        ) for k in api_spec.entities.keys()}


async def appgate_operator(
    queue: Queue, ctx: AppgateOperatorContext, k8s_configmap_client: K8SConfigMapClient
) -> None:
    namespace = ctx.namespace
    operator_name = get_operator_name(ctx.reverse_mode)
    log.info("[%s/%s] Main loop started:", operator_name, namespace)
    log.info("[%s/%s]   + namespace: %s", operator_name, namespace, namespace)
    log.info("[%s/%s]   + host: %s", operator_name, namespace, ctx.controller)
    log.info("[%s/%s]   + log-level: %s", operator_name, namespace, log.level)
    log.info("[%s/%s]   + timeout: %s", operator_name, namespace, ctx.timeout)
    log.info("[%s/%s]   + dry-run: %s", operator_name, namespace, ctx.dry_run_mode)
    log.info("[%s/%s]   + cleanup: %s", operator_name, namespace, ctx.cleanup_mode)
    log.info("[%s/%s]   + two-way-sync: %s", operator_name, namespace, ctx.two_way_sync)
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
        current_appgate_state = AppgateState()
        expected_appgate_state = await get_current_appgate_state(ctx=ctx)
        total_appgate_state = deepcopy(expected_appgate_state)
    else:
        current_appgate_state = await get_current_appgate_state(ctx=ctx)
        total_appgate_state = deepcopy(current_appgate_state)
    if ctx.cleanup_mode and ctx.reverse_mode:
        log.error("Reverse operator can not run in clean-up mode!")
        exit(1)
    if ctx.cleanup_mode:
        tags_in_cleanup = ctx.builtin_tags.union(ctx.exclude_tags or frozenset())
        expected_appgate_state = AppgateState(
            {
                k: v.entities_with_tags(tags_in_cleanup)
                for k, v in current_appgate_state.entities_set.items()
            }
        )
    elif ctx.target_tags:
        new_state = AppgateState(
            {
                k: v.entities_with_tags(ctx.target_tags)
                for k, v in current_appgate_state.entities_set.items()
            }
        )
        if ctx.reverse_mode:
            current_appgate_state = new_state
        else:
            expected_appgate_state = new_state
    elif not ctx.reverse_mode:
        expected_appgate_state = deepcopy(current_appgate_state)
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
                    "[%s/%s}] Event: %s %s with name %s",
                    operator_name,
                    namespace,
                    event.op,
                    event.entity.__class__.__qualname__,
                    event.entity.name,
                )
                expected_appgate_state.with_entity(
                    EntityWrapper(event.entity), event.op, current_appgate_state
                )
        except asyncio.exceptions.TimeoutError:
            if event_errors:
                log.error(
                    "[%s/%s}] Found events with errors, dying now!",
                    operator_name,
                    namespace,
                )
                for event_error in event_errors:
                    log.error(
                        "[%s/%s}] - Entity of type %s with name %s : %s",
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

            if ctx.two_way_sync:
                # use current appgate state from controller instead of from memory
                current_appgate_state = await get_current_appgate_state(ctx=ctx)
                total_appgate_state = deepcopy(current_appgate_state)

            # Create a plan
            # Need to copy?
            # Now we use dicts so resolving update the contents of the keys
            plan = create_appgate_plan(
                current_appgate_state,
                expected_appgate_state,
                ctx.builtin_tags,
                ctx.target_tags,
                ctx.exclude_tags,
            )
            if plan.needs_apply:
                log.info(
                    "[%s/%s] No more events for a while, creating a plan",
                    operator_name,
                    namespace,
                )
                async with AsyncExitStack() as exit_stack:
                    appgate_client = None
                    k8s_api = None
                    if not ctx.dry_run_mode and not ctx.reverse_mode:
                        if ctx.device_id is None:
                            raise AppgateException("No device id specified")
                        appgate_client = await exit_stack.enter_async_context(
                            AppgateClient(
                                controller=ctx.controller,
                                user=ctx.user,
                                password=ctx.password,
                                provider=ctx.provider,
                                device_id=ctx.device_id,
                                version=ctx.api_spec.api_version,
                                no_verify=ctx.no_verify,
                                cafile=ctx.cafile,
                            )
                        )
                    elif not ctx.dry_run_mode and ctx.reverse_mode:
                        k8s_api = CustomObjectsApi()
                    else:
                        log.warning(
                            "[%s/%s] Running in dry-mode, nothing will be created",
                            operator_name,
                            namespace,
                        )
                    new_plan = await appgate_plan_apply(
                        appgate_plan=plan,
                        namespace=namespace,
                        operator_name=operator_name,
                        appgate_entity_clients=generate_api_spec_clients(
                            api_spec=ctx.api_spec, appgate_client=appgate_client
                        )
                        if appgate_client
                        else {},
                        k8s_entity_clients=generate_k8s_clients(
                            api_spec=ctx.api_spec, namespace=ctx.namespace, k8s_api=k8s_api,
                        )
                        if k8s_api else {},
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
                            log.error(
                                "[%s/%s] Error %s:", operator_name, namespace, err
                            )
                        sys.exit(1)

                    if appgate_client:
                        current_appgate_state = new_plan.appgate_state
                        expected_appgate_state = (
                            expected_appgate_state.sync_generations()
                        )
                    elif k8s_api:
                        current_appgate_state = new_plan.appgate_state
                        expected_appgate_state = await get_current_appgate_state(
                            ctx=ctx
                        )
            else:
                log.info(
                    "[%s/%s] Nothing changed! Keeping watching!",
                    operator_name,
                    namespace,
                )
