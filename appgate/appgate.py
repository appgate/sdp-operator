import asyncio
import logging
import os
import sys
from asyncio import Queue
from copy import deepcopy
from pathlib import Path
from typing import Optional, Type

from attr import attrib, attrs
from kubernetes.client.rest import ApiException
from typedload import load
from typedload.exceptions import TypedloadTypeError
from kubernetes.config import load_kube_config, list_kube_config_contexts, load_incluster_config
from kubernetes.client import CustomObjectsApi
from kubernetes.watch import Watch

from appgate.client import AppgateClient
from appgate.openapi import K8S_APPGATE_VERSION, K8S_APPGATE_DOMAIN, APISpec, SPEC_DIR, Entity_T
from appgate.state import AppgateState, create_appgate_plan, \
    appgate_plan_apply, EntitiesSet, entities_conflict_summary, resolve_appgate_state
from appgate.types import K8SEvent, AppgateEvent, generate_api_spec_clients, \
    generate_api_spec

__all__ = [
    'init_kubernetes',
    'main_loop',
    'get_context',
    'get_current_appgate_state',
    'start_event_loop',
    'Context',
    'log',
]


USER_ENV = 'APPGATE_OPERATOR_USER'
PASSWORD_ENV = 'APPGATE_OPERATOR_PASSWORD'
TIMEOUT_ENV = 'APPGATE_OPERATOR_TIMEOUT'
HOST_ENV = 'APPGATE_OPERATOR_HOST'
DRY_RUN_ENV = 'APPGATE_OPERATOR_DRY_RUN'
CLEANUP_ENV = 'APPGATE_OPERATOR_CLEANUP'
NAMESPACE_ENV = 'APPGATE_OPERATOR_NAMESPACE'
TWO_WAY_SYNC_ENV = 'APPGATE_OPERATOR_TWO_WAY_SYNC'
SPEC_DIR_ENV = 'APPGATE_OPERATOR_SPEC_DIRECTORY'


crds: Optional[CustomObjectsApi] = None
log = logging.getLogger('appgate-operator')
log.setLevel(logging.INFO)


def get_crds() -> CustomObjectsApi:
    global crds
    if not crds:
        crds = CustomObjectsApi()
    return crds


@attrs()
class Context:
    namespace: str = attrib()
    user: str = attrib()
    password: str = attrib()
    controller: str = attrib()
    two_way_sync: bool = attrib()
    timeout: int = attrib()
    dry_run_mode: bool = attrib()
    cleanup_mode: bool = attrib()
    api_spec: APISpec = attrib()


def get_context(namespace: str, spec_directory: Optional[str]) -> Context:
    user = os.getenv(USER_ENV)
    password = os.getenv(PASSWORD_ENV)
    controller = os.getenv(HOST_ENV)
    timeout = os.getenv(TIMEOUT_ENV)
    two_way_sync = os.getenv(TWO_WAY_SYNC_ENV) or '1'
    dry_run_mode = os.getenv(DRY_RUN_ENV) or '1'
    cleanup_mode = os.getenv(CLEANUP_ENV) or '1'
    spec_directory = os.getenv(SPEC_DIR_ENV) or spec_directory or SPEC_DIR
    if not user or not password or not controller:
        missing_envs = ','.join([x[0]
                                 for x in [(USER_ENV, user),
                                           (PASSWORD_ENV, password),
                                           (HOST_ENV, controller)]
                                 if x[1] is None])
        raise Exception(f'Unable to create appgate-controller context, missing: {missing_envs}')
    api_spec = generate_api_spec(spec_directory=Path(spec_directory) if spec_directory else None)
    return Context(namespace=namespace, user=user, password=password,
                   controller=controller, timeout=int(timeout) if timeout else 30,
                   dry_run_mode=dry_run_mode == '1',
                   cleanup_mode=cleanup_mode == '1',
                   two_way_sync=two_way_sync == '1',
                   api_spec=api_spec)


def init_kubernetes(namespace: Optional[str] = None, spec_directory: Optional[str] = None) -> Context:
    if 'KUBERNETES_PORT' in os.environ:
        load_incluster_config()
        # TODO: Discover it somehow
        # https://github.com/kubernetes-client/python/issues/363
        namespace = namespace or os.getenv(NAMESPACE_ENV)
    else:
        load_kube_config()
        namespace = namespace or list_kube_config_contexts()[1]['context'].get('namespace')

    if not namespace:
        raise Exception('Unable to discover namespace, please provide it.')
    return get_context(namespace, spec_directory)


async def get_current_appgate_state(ctx: Context) -> AppgateState:
    """
    Gets the current AppgateState for controller
    """
    api_spec = ctx.api_spec
    appgate_client = AppgateClient(controller=ctx.controller, user=ctx.user,
                                   password=ctx.password,
                                   version=api_spec.api_version)
    log.info('[appgate-operator/%s] Updating current state from controller',
             ctx.namespace)

    await appgate_client.login()
    if not appgate_client.authenticated:
        log.error('[appgate-operator/%s] Unable to authenticate with controller',
                  ctx.namespace)
        await appgate_client.close()
        raise Exception('Error authenticating')

    entity_clients = generate_api_spec_clients(api_spec=api_spec,
                                               appgate_client=appgate_client)
    entities_set = {}
    for entity, client in entity_clients.items():
        entities = await client.get()
        if entities is not None:
            entities_set[entity] = EntitiesSet(set(entities))
    if len(entities_set) < len(entity_clients):
        log.error('[appgate-operator/%s] Unable to get entities from controller',
                  ctx.namespace)
        await appgate_client.close()
        raise Exception('Error reading current state')

    appgate_state = AppgateState(entities_set=entities_set)
    await appgate_client.close()
    return appgate_state


def run_event_loop(namespace: str, crd: str, entity_type: Type[Entity_T],
                   loop: asyncio.AbstractEventLoop, queue: Queue[AppgateEvent]):
    log.info(f'[{crd}/{namespace}] Loop for {crd}/{namespace} started')
    watcher = Watch().stream(get_crds().list_namespaced_custom_object, K8S_APPGATE_DOMAIN,
                             K8S_APPGATE_VERSION, namespace, crd)
    while True:
        try:
            event = next(watcher)
            if event:
                ev = K8SEvent(event)
                try:
                    entity = load(ev.object.spec, entity_type)
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


async def start_event_loop(namespace: str, crd: str, entity_type: Type[Entity_T],
                           queue: Queue[AppgateEvent]) -> None:
    log.debug('[%s/%s] Starting loop event for entities on path: %s', crd, namespace,
              crd)

    def run(loop: asyncio.AbstractEventLoop) -> None:
        import threading
        t = threading.Thread(target=run_event_loop,
                             args=(namespace, crd, entity_type, loop, queue),
                             daemon=False)
        t.start()

    await asyncio.to_thread(run, asyncio.get_event_loop())


async def main_loop(queue: Queue, ctx: Context) -> None:
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
            {k: v.builtin_entities() for k, v in current_appgate_state.entities_set.items()})
    else:
        expected_appgate_state = deepcopy(current_appgate_state)

    log.info('[appgate-operator/%s] Ready to get new events and compute a new plan',
             namespace)
    while True:
        try:
            event: AppgateEvent = await asyncio.wait_for(queue.get(), timeout=ctx.timeout)
            log.info('[appgate-operator/%s}] Event op: %s %s with name %s', namespace,
                     event.op, str(type(event.entity)), event.entity.name)
            expected_appgate_state.with_entity(event.entity, event.op, current_appgate_state)
        except asyncio.exceptions.TimeoutError:
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
            plan = create_appgate_plan(current_appgate_state, expected_appgate_state)
            if plan.needs_apply:
                log.info('[appgate-operator/%s] No more events for a while, creating a plan',
                         namespace)
                appgate_client = None
                if not ctx.dry_run_mode:
                    appgate_client = AppgateClient(controller=ctx.controller,
                                                   user=ctx.user, password=ctx.password,
                                                   version=ctx.api_spec.api_version)
                    await appgate_client.login()
                else:
                    log.warning('[appgate-operator/%s] Running in dry-mode, nothing will be created',
                                namespace)
                new_plan = await appgate_plan_apply(appgate_plan=plan, namespace=namespace,
                                                    entity_clients=generate_api_spec_clients(
                                                        api_spec=ctx.api_spec,
                                                        appgate_client=appgate_client)
                                                    if appgate_client else {})

                if appgate_client:
                    current_appgate_state = new_plan.appgate_state
                    await appgate_client.close()
            else:
                log.info('[appgate-operator/%s] Nothing changed! Keeping watching!', namespace)
