import asyncio
import functools
import logging
from asyncio import Queue
from typing import Optional, Dict, Any, List, cast
from typing_extensions import AsyncIterable
from kubernetes.config import load_kube_config, list_kube_config_contexts
from kubernetes.client import CustomObjectsApi
from kubernetes.watch import Watch

from appgate.client import AppgateClient
from appgate.state import AppgateState, create_appgate_plan, appgate_plan_summary
from appgate.types import entitlement_load, K8SEvent, policy_load, condition_load, AppgateEvent, Policy, Entitlement, \
    Condition

DOMAIN = 'beta.appgate.com'
RESOURCE_VERSION = 'v1'

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


def init_kubernetes() -> Optional[str]:
    load_kube_config()
    return list_kube_config_contexts()[1]['context'].get('namespace')


async def init_environment(controller: str, user: str, password: str) -> AppgateState:
    appgate_client = AppgateClient(controller=controller, user=user,
                                   password=password)
    await appgate_client.login()
    policies = await appgate_client.policies.get()
    entitlements = await appgate_client.entitlements.get()
    conditions = await appgate_client.conditions.get()

    appgate_state = AppgateState(policies=set(cast(List[Policy], policies)),
                                 entitlements=set(cast(List[Entitlement], entitlements)),
                                 conditions=set(cast(List[Condition], conditions)))
    await appgate_client.close()
    return appgate_state


async def event_loop(namespace: str, crd: str) -> AsyncIterable[Dict[str, Any]]:
    log.info(f'[{crd}/{namespace}] Loop for {crd}/{namespace} started')
    log.debug('test')
    s = Watch().stream(get_crds().list_namespaced_custom_object, DOMAIN, 'v1',
                       namespace, crd)
    loop = asyncio.get_event_loop()
    while True:
        event = await loop.run_in_executor(None, functools.partial(next, s))
        yield event  # type: ignore
        await asyncio.sleep(0)


async def policies_loop(namespace: str, queue: Queue):
    async for event in event_loop(namespace, 'policies'):
        ev = K8SEvent(event)
        policy = policy_load(ev.object.spec)
        log.info('[policies/%s}] K8SEvent type: %s: %s', namespace,
                 ev.type, policy)
        await queue.put(AppgateEvent(op=ev.type, event=policy))


async def entitlements_loop(namespace: str, queue: Queue) -> None:
    async for event in event_loop(namespace, 'entitlements'):
        ev = K8SEvent(event)
        entitlement = entitlement_load(ev.object.spec)
        log.info('[entitlements/%s}] K8SEvent type: %s: %s', namespace,
                 ev.type, entitlement)
        await queue.put(AppgateEvent(op=ev.type, event=entitlement))


async def conditions_loop(namespace: str, queue: Queue) -> None:
    async for event in event_loop(namespace, 'conditions'):
        ev = K8SEvent(event)
        condition = condition_load(ev.object.spec)
        log.info('[conditions/%s}] K8SEvent type: %s: %s', namespace,
                 ev.type, condition)
        await queue.put(AppgateEvent(op=ev.type, event=condition))


async def main_loop(queue: Queue[AppgateEvent], controller: str, user: str, namespace: str,
                    password: str) -> None:
    log.info('[appgate-operator/%s] Getting current state from controller',
             namespace)
    current_appgate_state = await init_environment(controller=controller, user=user,
                                                   password=password)
    expected_appgate_state = AppgateState()
    log.info('[appgate-operator/%s] Ready to get new events and compute a new plan',
             namespace)
    while True:
        try:
            event: AppgateEvent = await asyncio.wait_for(queue.get(), timeout=5.0)
            log.info('[appgate-operator/%s}] Event op: %s: %s', namespace,
                     event.op, event)
            expected_appgate_state.with_entity(event.event, event.op)
        except asyncio.exceptions.TimeoutError:
            log.info('[appgate-operator/%s] No more events for a while, creating a plan',
                     namespace)
            plan = create_appgate_plan(current_appgate_state, expected_appgate_state)
            appgate_plan_summary(appgate_plan=plan, namespace=namespace)
