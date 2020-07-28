import asyncio
import functools
import logging
import os
import sys
from asyncio import Queue
from copy import deepcopy
from typing import Optional, Dict, Any, List, cast

from attr import attrib, attrs
from kubernetes.client.rest import ApiException
from typedload.exceptions import TypedloadTypeError
from typing_extensions import AsyncIterable
from kubernetes.config import load_kube_config, list_kube_config_contexts, load_incluster_config
from kubernetes.client import CustomObjectsApi
from kubernetes.watch import Watch

from appgate.client import AppgateClient
from appgate.state import AppgateState, create_appgate_plan, appgate_plan_errors_summary, \
    appgate_plan_apply, EntitiesSet, resolve_entitlements, resolve_policies
from appgate.types import entitlement_load, K8SEvent, policy_load, condition_load, AppgateEvent, \
    Policy, Entitlement, Condition

DOMAIN = 'beta.appgate.com'
RESOURCE_VERSION = 'v1'
DRY_MODE = True
CLEANUP_ON_STARTUP = True

__all__ = [
    'policies_loop',
    'entitlements_loop',
    'conditions_loop',
    'init_kubernetes',
    'main_loop'
]


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
    namespace: Optional[str] = attrib()
    user: str = attrib()
    password: str = attrib()
    controller: str = attrib()


def init_kubernetes() -> Context:
    if 'KUBERNETES_PORT' in os.environ:
        load_incluster_config()
    else:
        load_kube_config()
    namespace = list_kube_config_contexts()[1]['context'].get('namespace')
    user = os.getenv("APPGATE_CONTROLLER_USER")
    password = os.getenv("APPGATE_CONTROLLER_PASSWORD")
    controller = os.getenv("APPGATE_CONTROLLER")
    if not user or not password or not controller:
        raise Exception('Unable to create appgate-controller context')
    return Context(namespace, user, password, controller)


async def init_environment(controller: str, user: str, password: str) -> Optional[AppgateState]:
    appgate_client = AppgateClient(controller=controller, user=user, password=password)
    await appgate_client.login()
    if not appgate_client.authenticated:
        await appgate_client.close()
        return None

    policies = await appgate_client.policies.get()
    entitlements = await appgate_client.entitlements.get()
    conditions = await appgate_client.conditions.get()
    if policies is None or entitlements is None or conditions is None:
        await appgate_client.close()
        return None
    policies_set = EntitiesSet(set(cast(List[Policy], policies)))
    entitlements_set = EntitiesSet(set(cast(List[Entitlement], entitlements)))
    conditions_set = EntitiesSet(set(cast(List[Condition], conditions)))
    appgate_state = AppgateState(policies=policies_set,
                                 entitlements=entitlements_set,
                                 conditions=conditions_set)
    await appgate_client.close()
    return appgate_state


async def event_loop(namespace: str, crd: str) -> AsyncIterable[Optional[Dict[str, Any]]]:
    log.info(f'[{crd}/{namespace}] Loop for {crd}/{namespace} started')
    log.debug('test')
    s = Watch().stream(get_crds().list_namespaced_custom_object, DOMAIN, 'v1',
                       namespace, crd)
    loop = asyncio.get_event_loop()
    while True:
        try:
            event = await loop.run_in_executor(None, functools.partial(lambda i: next(i, None), s))
            if event:
                yield event  # type: ignore
            await asyncio.sleep(1)
        except ApiException:
            log.exception('[appgate-operator/%s] Error when subscribing events in k8s.', namespace)
            sys.exit(1)


async def policies_loop(namespace: str, queue: Queue):
    async for event in event_loop(namespace, 'policies'):
        try:
            if not event:
                continue
            ev = K8SEvent(event)
            policy = policy_load(ev.object.spec)
            log.debug('[policies/%s}] K8SEvent type: %s: %s', namespace,
                      ev.type, policy)
            await queue.put(AppgateEvent(op=ev.type, entity=policy))
        except TypedloadTypeError:
            log.exception('[conditions/%s] Unable to parse event %s', namespace, event)


async def entitlements_loop(namespace: str, queue: Queue) -> None:
    async for event in event_loop(namespace, 'entitlements'):
        try:
            if not event:
                continue
            ev = K8SEvent(event)
            entitlement = entitlement_load(ev.object.spec)
            log.debug('[entitlements/%s}] K8SEvent type: %s: %s', namespace,
                      ev.type, entitlement)
            await queue.put(AppgateEvent(op=ev.type, entity=entitlement))
        except TypedloadTypeError:
            log.exception('[conditions/%s] Unable to parse event %s', namespace, event)


async def conditions_loop(namespace: str, queue: Queue) -> None:
    async for event in event_loop(namespace, 'conditions'):
        try:
            if not event:
                continue
            ev = K8SEvent(event)
            condition = condition_load(ev.object.spec)
            log.debug('[conditions/%s}] K8SEvent type: %s: %s', namespace,
                      ev.type, condition)
            await queue.put(AppgateEvent(op=ev.type, entity=condition))
        except TypedloadTypeError:
            log.exception('[conditions/%s] Unable to parse event %s', namespace, event)


async def main_loop(queue: Queue, controller: str, user: str, namespace: str,
                    password: str) -> None:
    log.info('[appgate-operator/%s] Getting current state from controller',
             namespace)
    while True:
        current_appgate_state = await init_environment(controller=controller,
                                                       user=user, password=password)
        if current_appgate_state:
            if CLEANUP_ON_STARTUP:
                expected_appgate_state = AppgateState(
                    policies=current_appgate_state.policies.builtin_entities(),
                    entitlements=current_appgate_state.entitlements.builtin_entities(),
                    conditions=current_appgate_state.conditions.builtin_entities())
            else:
                expected_appgate_state = deepcopy(current_appgate_state)
            break
        log.error('[appgate-operator/%s] Unable to get current state, trying in 30 seconds',
                  namespace)
        await asyncio.sleep(30)

    log.info('[appgate-operator/%s] Ready to get new events and compute a new plan',
             namespace)
    while True:
        try:
            event: AppgateEvent = await asyncio.wait_for(queue.get(), timeout=5.0)
            log.info('[appgate-operator/%s}] Event op: %s %s with name %s', namespace,
                     event.op, str(type(event.entity)), event.entity.name)
            assert expected_appgate_state
            expected_appgate_state.with_entity(event.entity, event.op, current_appgate_state)
        except asyncio.exceptions.TimeoutError:
            # Resolve entities now
            # First entitlements since we have conditions
            # Second policies since we have entitlements
            resolved_entitlements, entitlement_conflicts = resolve_entitlements(
                expected_appgate_state.entitlements, expected_appgate_state.conditions)
            resolved_policies, policies_conflicts = resolve_policies(
                expected_appgate_state.policies, expected_appgate_state.entitlements)
            # Create a plan
            plan = create_appgate_plan(current_appgate_state,
                                       expected_appgate_state.copy(
                                           entitlements=resolved_entitlements,
                                           policies=resolved_policies),
                                       entitlement_conflicts, policies_conflicts)
            if plan.policy_conflicts or plan.entitlement_conflicts:
                log.error('[appgate-operator/%s] Found errors in expected state and plan can' 
                          ' not be applied', namespace)
                appgate_plan_errors_summary(appgate_plan=plan, namespace=namespace)
            elif plan.needs_apply:
                log.info('[appgate-operator/%s] No more events for a while, creating a plan',
                         namespace)
                appgate_client = None
                if not DRY_MODE:
                    appgate_client = AppgateClient(controller=controller, user=user, password=password)
                    await appgate_client.login()
                else:
                    log.warning('[appgate-operator/%s] Running in dry-mode, nothing will be created',
                                namespace)
                new_plan = await appgate_plan_apply(appgate_plan=plan, namespace=namespace,
                                                    appgate_client=appgate_client)

                if appgate_client:
                    current_appgate_state = new_plan.appgate_state
                    await appgate_client.close()
            else:
                log.info('[appgate-operator/%s] Nothing changed! Keeping watching!', namespace)
