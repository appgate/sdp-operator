import asyncio
import functools
import logging
from typing import Optional, Dict, Any
from typing_extensions import AsyncIterable
from kubernetes.config import load_kube_config, list_kube_config_contexts
from kubernetes.client import CustomObjectsApi
from kubernetes.watch import Watch

from appgate.client import AppgateClient
from appgate.types import entitlement_load, Event, policy_load, condition_load

DOMAIN = 'beta.appgate.com'
RESOURCE_VERSION = 'v1'

__all__ = [
    'policies_loop',
    'entitlements_loop',
    'conditions_loop',
    'init_kubernetes',
    'init_environment',
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


async def init_environment(controller: str, user: str, password: str) -> None:
    appgate_client = AppgateClient(controller=controller, user=user,
                                   password=password)
    await appgate_client.login()
    policies = await appgate_client.get_policies()
    entitlements = await appgate_client.get_entitlements()
    conditions = await appgate_client.get_policies()
    await appgate_client.close()


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


async def policies_loop(namespace: str):
    async for event in event_loop(namespace, 'policies'):
        ev = Event(event)
        policy = policy_load(ev.object.spec)
        log.info('[policies/%s}] Event type: %s: %s', namespace,
                 ev.type, policy)


async def entitlements_loop(namespace: str) -> None:
    async for event in event_loop(namespace, 'entitlements'):
        ev = Event(event)
        entitlement = entitlement_load(ev.object.spec)
        log.info('[entitlements/%s}] Event type: %s: %s', namespace,
                 ev.type, entitlement)


async def conditions_loop(namespace: str) -> None:
    async for event in event_loop(namespace, 'conditions'):
        ev = Event(event)
        condition = condition_load(ev.object.spec)
        log.info('[conditions/%s}] Event type: %s: %s', namespace,
                 ev.type, condition)