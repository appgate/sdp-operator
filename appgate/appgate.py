import asyncio
import logging
import os
import sys
from asyncio import Queue
from contextlib import AsyncExitStack
from copy import deepcopy
from pathlib import Path
from typing import Optional, Type, Dict, Callable, Any, List, FrozenSet
import threading

from attr import attrib, attrs
from kubernetes.client.rest import ApiException
from typedload.exceptions import TypedloadTypeError
from kubernetes.config import load_kube_config, list_kube_config_contexts, load_incluster_config
from kubernetes.client import CustomObjectsApi
from kubernetes.watch import Watch

from appgate.attrs import K8S_LOADER, dump_datetime
from appgate.client import AppgateClient, K8SConfigMapClient, entity_unique_id
from appgate.openapi.openapi import generate_api_spec, generate_api_spec_clients, SPEC_DIR
from appgate.openapi.types import APISpec, Entity_T, K8S_APPGATE_VERSION, K8S_APPGATE_DOMAIN
from appgate.openapi.utils import is_target, APPGATE_TARGET_TAGS_ENV
from appgate.secrets import k8s_get_secret

from appgate.state import AppgateState, create_appgate_plan, \
    appgate_plan_apply, EntitiesSet, entities_conflict_summary, resolve_appgate_state
from appgate.types import K8SEvent, AppgateEvent, EntityWrapper, EventObject, OperatorArguments

__all__ = [
    'init_kubernetes',
    'main_loop',
    'get_context',
    'get_current_appgate_state',
    'start_entity_loop',
    'Context',
    'log',
]


USER_ENV = 'APPGATE_OPERATOR_USER'
PASSWORD_ENV = 'APPGATE_OPERATOR_PASSWORD'
TIMEOUT_ENV = 'APPGATE_OPERATOR_TIMEOUT'
HOST_ENV = 'APPGATE_OPERATOR_HOST'
DRY_RUN_ENV = 'APPGATE_OPERATOR_DRY_RUN'
CLEANUP_ENV = 'APPGATE_OPERATOR_CLEANUP'
DUMP_SECRETS_ENV = 'APPGATE_OPERATOR_DUMP_SECRETS'
NAMESPACE_ENV = 'APPGATE_OPERATOR_NAMESPACE'
TWO_WAY_SYNC_ENV = 'APPGATE_OPERATOR_TWO_WAY_SYNC'
SPEC_DIR_ENV = 'APPGATE_OPERATOR_SPEC_DIRECTORY'
APPGATE_SECRETS_KEY = 'APPGATE_OPERATOR_FERNET_KEY'
APPGATE_CONFIGMAP_ENV = 'APPGATE_OPERATOR_CONFIG_MAP'


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
    metadata_configmap: str = attrib()
    target_tags: Optional[FrozenSet[str]] = attrib(default=None)


def get_context(args: OperatorArguments,
                k8s_get_secret: Optional[Callable[[str, str], str]] = None) -> Context:
    if not args.namespace:
        raise Exception('Namespace must be defined in order to run the appgate-operator')
    user = os.getenv(USER_ENV) or args.user
    password = os.getenv(PASSWORD_ENV) or args.password
    controller = os.getenv(HOST_ENV) or args.host
    timeout = os.getenv(TIMEOUT_ENV) or args.timeout
    two_way_sync = os.getenv(TWO_WAY_SYNC_ENV) or ('1' if args.two_way_sync else '0')
    dry_run_mode = os.getenv(DRY_RUN_ENV) or ('1' if args.dry_run else '0')
    cleanup_mode = os.getenv(CLEANUP_ENV) or ('1' if args.cleanup else '0')
    spec_directory = os.getenv(SPEC_DIR_ENV) or args.spec_directory or SPEC_DIR
    secrets_key = os.getenv(APPGATE_SECRETS_KEY)
    target_tags_arg = frozenset(args.target_tags) if args.target_tags else frozenset()
    target_tags_env = target_tags_arg.union(
        frozenset(filter(None, os.getenv(APPGATE_TARGET_TAGS_ENV, '').split(','))))
    metadata_configmap = os.getenv(APPGATE_CONFIGMAP_ENV) or f'{args.namespace}-configmap'

    if not user or not password or not controller:
        missing_envs = ','.join([x[0]
                                 for x in [(USER_ENV, user),
                                           (PASSWORD_ENV, password),
                                           (HOST_ENV, controller)]
                                 if x[1] is None])
        raise Exception(f'Unable to create appgate-controller context, missing: {missing_envs}')
    api_spec = generate_api_spec(spec_directory=Path(spec_directory) if spec_directory else None,
                                 secrets_key=secrets_key,
                                 k8s_get_secret=k8s_get_secret)
    return Context(namespace=args.namespace, user=user, password=password,
                   controller=controller, timeout=int(timeout),
                   dry_run_mode=dry_run_mode == '1',
                   cleanup_mode=cleanup_mode == '1',
                   two_way_sync=two_way_sync == '1',
                   api_spec=api_spec,
                   target_tags=target_tags_env if target_tags_env else None,
                   metadata_configmap=metadata_configmap)


def init_kubernetes(args: OperatorArguments) -> Context:
    if 'KUBERNETES_PORT' in os.environ:
        load_incluster_config()
        # TODO: Discover it somehow
        # https://github.com/kubernetes-client/python/issues/363
        namespace = args.namespace or os.getenv(NAMESPACE_ENV)
    else:
        load_kube_config()
        namespace = args.namespace or list_kube_config_contexts()[1]['context'].get('namespace')

    if not namespace:
        raise Exception('Unable to discover namespace, please provide it.')
    ns: str = namespace  # lambda thinks it's an Optional
    return get_context(
        args=args,
        k8s_get_secret=lambda secret, key: k8s_get_secret(
            namespace=ns,
            key=key,
            secret=secret
        ))


async def get_current_appgate_state(ctx: Context) -> AppgateState:
    """
    Gets the current AppgateState for controller
    """
    api_spec = ctx.api_spec
    async with AppgateClient(controller=ctx.controller, user=ctx.user,
                             password=ctx.password,
                             version=api_spec.api_version) as appgate_client:
        log.info('[appgate-operator/%s] Updating current state from controller',
                 ctx.namespace)

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
                entities_set[entity] = EntitiesSet(set(map(EntityWrapper,
                                                           filter(lambda e: is_target(e, ctx.target_tags),
                                                                  entities))))
        if len(entities_set) < len(entity_clients):
            log.error('[appgate-operator/%s] Unable to get entities from controller',
                      ctx.namespace)
            await appgate_client.close()
            raise Exception('Error reading current state')

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
                    latest_entity_generation = k8s_configmap_client.read(entity_unique_id(kind, name))
                    if latest_entity_generation:
                        mt['latestGeneration'] = latest_entity_generation.generation
                        mt['modified'] = dump_datetime(latest_entity_generation.modified)
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
            expected_appgate_state.with_entity(EntityWrapper(event.entity), event.op, current_appgate_state)
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
                async with AsyncExitStack() as exit_stack:
                    appgate_client = None
                    if not ctx.dry_run_mode:
                        appgate_client = await exit_stack.enter_async_context(AppgateClient(
                            controller=ctx.controller,
                            user=ctx.user, password=ctx.password,
                            version=ctx.api_spec.api_version))
                    else:
                        log.warning('[appgate-operator/%s] Running in dry-mode, nothing will be created',
                                    namespace)
                    new_plan = await appgate_plan_apply(appgate_plan=plan, namespace=namespace,
                                                        entity_clients=generate_api_spec_clients(
                                                            api_spec=ctx.api_spec,
                                                            appgate_client=appgate_client)
                                                        if appgate_client else {},
                                                        k8s_configmap_client=k8s_configmap_client)

                    if appgate_client:
                        current_appgate_state = new_plan.appgate_state
            else:
                log.info('[appgate-operator/%s] Nothing changed! Keeping watching!', namespace)
