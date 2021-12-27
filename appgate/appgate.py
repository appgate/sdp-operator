import asyncio
import logging
import sys
from asyncio import Queue
from contextlib import AsyncExitStack
from copy import deepcopy
from typing import Optional, Type, Dict, Callable, Any, FrozenSet, List, Set
import threading

from kubernetes.client.rest import ApiException
from typedload.exceptions import TypedloadTypeError
from kubernetes.client import CustomObjectsApi
from kubernetes.watch import Watch

from appgate.types import Context
from appgate.attrs import K8S_LOADER, dump_datetime
from appgate.client import AppgateClient, K8SConfigMapClient, entity_unique_id
from appgate.openapi.types import AppgateException
from appgate.openapi.openapi import generate_api_spec_clients
from appgate.openapi.types import Entity_T, K8S_APPGATE_VERSION, K8S_APPGATE_DOMAIN, \
    APPGATE_METADATA_LATEST_GENERATION_FIELD, APPGATE_METADATA_MODIFICATION_FIELD
from appgate.state import AppgateState, create_appgate_plan, \
    appgate_plan_apply, EntitiesSet, entities_conflict_summary, resolve_appgate_state
from appgate.types import K8SEvent, AppgateEvent, EntityWrapper, EventObject, is_target, has_tag

__all__ = [
    'main_loop',
    'get_current_appgate_state',
    'start_entity_loop',
    'log',
    'exclude_appgate_entities',
    'is_debug',
]


crds: Optional[CustomObjectsApi] = None
log = logging.getLogger('appgate-operator')
log.setLevel(logging.INFO)


def is_debug() -> bool:
    return log.level <= logging.DEBUG


def get_crds() -> CustomObjectsApi:
    global crds
    if not crds:
        crds = CustomObjectsApi()
    return crds


def exclude_appgate_entities(entities: List[Entity_T], target_tags: Optional[FrozenSet[str]],
                             exclude_tags: Optional[FrozenSet[str]]) -> Set[EntityWrapper]:
    """
    Filter out entities according to target_tags and exclude_rags
    Returns the entities that are member of target_tags (all entities if None)
    but not member of exclude_tags
    """
    return set(filter(lambda e: is_target(e, target_tags) and not has_tag(e, exclude_tags),
                      [EntityWrapper(e) for e in entities]))


async def get_current_appgate_state(ctx: Context) -> AppgateState:
    """
    Gets the current AppgateState for controller
    """
    api_spec = ctx.api_spec
    log.info('[appgate-operator/%s] Updating current state from controller',
             ctx.namespace)
    if ctx.no_verify:
        log.warning('[appgate-operator/%s] Ignoring SSL certificates!',
                    ctx.namespace)
    if ctx.device_id is None:
        raise AppgateException('No device id specified')
    async with AppgateClient(controller=ctx.controller, user=ctx.user,
                             password=ctx.password, provider=ctx.provider,
                             device_id=ctx.device_id,
                             version=api_spec.api_version,
                             no_verify=ctx.no_verify,
                             cafile=ctx.cafile) as appgate_client:
        if not appgate_client.authenticated:
            log.error('[appgate-operator/%s] Unable to authenticate with controller',
                      ctx.namespace)
            raise AppgateException('Error authenticating')

        entity_clients = generate_api_spec_clients(api_spec=api_spec,
                                                   appgate_client=appgate_client)
        entities_set = {}
        for entity, client in entity_clients.items():
            entities = await client.get()
            if entities is not None:
                entities_set[entity] = EntitiesSet(
                    exclude_appgate_entities(entities, ctx.target_tags, ctx.exclude_tags))
        if len(entities_set) < len(entity_clients):
            log.error('[appgate-operator/%s] Unable to get entities from controller',
                      ctx.namespace)
            raise AppgateException('Error reading current state')
        appgate_state = AppgateState(entities_set=entities_set)

    return appgate_state


def run_entity_loop(ctx: Context, crd: str, loop: asyncio.AbstractEventLoop,
                    queue: Queue[AppgateEvent],
                    load: Callable[[Dict[str, Any], Optional[Dict[str, Any]], type], Entity_T],
                    entity_type: type, singleton: bool, k8s_configmap_client: K8SConfigMapClient):
    namespace = ctx.namespace
    log.info(f'[{crd}/{namespace}] Loop for {crd}/{namespace} started')
    watcher = Watch().stream(get_crds().list_namespaced_custom_object, K8S_APPGATE_DOMAIN,
                             K8S_APPGATE_VERSION, namespace, crd)
    while True:
        try:
            data = next(watcher)
            data_obj = data['object']
            data_mt = data_obj['metadata']
            kind = data_obj['kind']
            spec = data_obj['spec']
            event = EventObject(metadata=data_mt, spec=spec, kind=kind)
            if singleton:
                name = 'singleton'
            else:
                name = event.spec['name']
            if event:
                ev = K8SEvent(data['type'], event)
                try:
                    # names are not unique between entities so we need to come up with a unique name
                    # now
                    mt = ev.object.metadata
                    latest_entity_generation = k8s_configmap_client.read_entity_generation(entity_unique_id(kind, name))
                    if latest_entity_generation:
                        mt[APPGATE_METADATA_LATEST_GENERATION_FIELD] = latest_entity_generation.generation
                        mt[APPGATE_METADATA_MODIFICATION_FIELD] = dump_datetime(latest_entity_generation.modified)
                    entity = load(ev.object.spec, ev.object.metadata, entity_type)
                except TypedloadTypeError:
                    log.exception('[%s/%s] Unable to parse event %s', crd, namespace, event)
                    continue
                log.debug('[%s/%s] K8SEvent type: %s: %s', crd, namespace, ev.type, entity)
                asyncio.run_coroutine_threadsafe(queue.put(AppgateEvent(op=ev.type, entity=entity)),
                                                 loop)
        except ApiException:
            log.exception('[appgate-operator/%s] Error when subscribing events in k8s for %s',
                          namespace, crd)
            sys.exit(1)
        except Exception:
            log.exception('[appgate-operator/%s] Unhandled error for %s', namespace, crd)
            sys.exit(1)


async def start_entity_loop(ctx: Context, crd: str, entity_type: Type[Entity_T],
                            singleton: bool, queue: Queue[AppgateEvent],
                            k8s_configmap_client: K8SConfigMapClient) -> None:
    log.debug('[%s/%s] Starting loop event for entities on path: %s', crd, ctx.namespace,
              crd)

    def run(loop: asyncio.AbstractEventLoop) -> None:
        t = threading.Thread(target=run_entity_loop,
                             args=(ctx, crd, loop, queue, K8S_LOADER.load, entity_type, singleton,
                                   k8s_configmap_client),
                             daemon=True)
        t.start()

    await asyncio.to_thread(run, asyncio.get_event_loop())  # type: ignore


async def main_loop(queue: Queue, ctx: Context, k8s_configmap_client: K8SConfigMapClient) -> None:
    namespace = ctx.namespace
    log.info('[appgate-operator/%s] Main loop started:', namespace)
    log.info('[appgate-operator/%s]   + namespace: %s', namespace, namespace)
    log.info('[appgate-operator/%s]   + host: %s', namespace, ctx.controller)
    log.info('[appgate-operator/%s]   + timeout: %s', namespace, ctx.timeout)
    log.info('[appgate-operator/%s]   + dry-run: %s', namespace, ctx.dry_run_mode)
    log.info('[appgate-operator/%s]   + cleanup: %s', namespace, ctx.cleanup_mode)
    log.info('[appgate-operator/%s]   + two-way-sync: %s', namespace, ctx.two_way_sync)
    log.info('[appgate-operator/%s] Getting current state from controller',
             namespace)
    current_appgate_state = await get_current_appgate_state(ctx=ctx)
    if ctx.cleanup_mode:
        expected_appgate_state = AppgateState(
            {k: v.entities_with_tags(ctx.builtin_tags) for k, v in current_appgate_state.entities_set.items()})
    else:
        expected_appgate_state = deepcopy(current_appgate_state)
    log.info('[appgate-operator/%s] Ready to get new events and compute a new plan',
             namespace)
    while True:
        try:
            event: AppgateEvent = await asyncio.wait_for(queue.get(), timeout=ctx.timeout)
            log.info('[appgate-operator/%s}] Event op: %s %s with name %s', namespace,
                     event.op, str(type(event.entity)), event.entity.name)
            expected_appgate_state.with_entity(EntityWrapper(event.entity), event.op, current_appgate_state)
        except asyncio.exceptions.TimeoutError:
            # Log all entities in expected state
            log.info('[appgate-operator/%s] Expected entities:', namespace)
            for entity_type, xs in expected_appgate_state.entities_set.items():
                for entity_name, e in xs.entities_by_name.items():
                    log.info('[appgate-operator/%s] %s: %s: %s', namespace, entity_type, entity_name,
                             e.id)

            # Resolve entities now, in order
            # this will be the Topological sort
            total_conflicts = resolve_appgate_state(appgate_state=expected_appgate_state,
                                                    reverse=False,
                                                    api_spec=ctx.api_spec)
            if total_conflicts:
                log.error('[appgate-operator/%s] Found errors in expected state and plan can'
                          ' not be applied.', namespace)
                entities_conflict_summary(conflicts=total_conflicts, namespace=namespace)
                log.info('[appgate-operator/%s] Waiting for more events that can fix the state.',
                         namespace)
                continue
                
            if ctx.two_way_sync:
                # use current appgate state from controller instead of from memory
                current_appgate_state = await get_current_appgate_state(ctx=ctx)

            # Create a plan
            # Need to copy?
            # Now we use dicts so resolving update the contents of the keys
            plan = create_appgate_plan(current_appgate_state, expected_appgate_state,
                                       ctx.builtin_tags,)
            if plan.needs_apply:
                log.info('[appgate-operator/%s] No more events for a while, creating a plan',
                         namespace)
                async with AsyncExitStack() as exit_stack:
                    appgate_client = None
                    if not ctx.dry_run_mode:
                        if ctx.device_id is None:
                            raise AppgateException('No device id specified')
                        appgate_client = await exit_stack.enter_async_context(AppgateClient(
                            controller=ctx.controller,
                            user=ctx.user, password=ctx.password, provider=ctx.provider,
                            device_id=ctx.device_id,
                            version=ctx.api_spec.api_version, no_verify=ctx.no_verify,
                            cafile=ctx.cafile))
                    else:
                        log.warning('[appgate-operator/%s] Running in dry-mode, nothing will be created',
                                    namespace)
                    new_plan = await appgate_plan_apply(appgate_plan=plan, namespace=namespace,
                                                        entity_clients=generate_api_spec_clients(
                                                            api_spec=ctx.api_spec,
                                                            appgate_client=appgate_client)
                                                        if appgate_client else {},
                                                        k8s_configmap_client=k8s_configmap_client,
                                                        api_spec=ctx.api_spec)

                    if len(new_plan.errors) > 0:
                        log.error('[appgate-operator/%s] Found errors when applying plan:', namespace)
                        for err in new_plan.errors:
                            log.error('[appgate-operator/%s] Error %s:', namespace, err)
                        sys.exit(1)

                    if appgate_client:
                        current_appgate_state = new_plan.appgate_state
                        expected_appgate_state = expected_appgate_state.sync_generations()
            else:
                log.info('[appgate-operator/%s] Nothing changed! Keeping watching!', namespace)
