import asyncio
import functools
from typing import Optional, Dict, Any, AsyncGenerator
import kubernetes
from kubernetes.client import CustomObjectsApi
from appgate.types import entitlement_load, Event, policy_load, condition_load

DOMAIN = 'beta.appgate.com'
RESOURCE_VERSION = 'v1'

__all__ = [
    'policies_loop',
    'entitlements_loop',
    'conditions_loop',
    'init_kubernetes'
]


crds: Optional[CustomObjectsApi] = None


def get_crds() -> CustomObjectsApi:
    global crds
    if not crds:
        crds = CustomObjectsApi()
    return crds


def init_kubernetes() -> Optional[str]:
    kubernetes.config.load_kube_config()
    return kubernetes.config.list_kube_config_contexts()[1]['context'].get('namespace')


async def event_loop(namespace: str, crd: str) -> AsyncGenerator[Dict[str, Any], None]:
    w = kubernetes.watch.Watch()
    print(f'Loop for {crd}/{namespace} started')
    s = w.stream(get_crds().list_namespaced_custom_object, DOMAIN, 'v1',
                 namespace, crd)
    loop = asyncio.get_event_loop()
    while True:
        event = await loop.run_in_executor(None, functools.partial(next, s))
        yield event
        await asyncio.sleep(0)


async def policies_loop(namespace: str):
    async for event in event_loop(namespace, 'policies'):
        ev = Event(event)
        policy = policy_load(ev.object.spec)
        print(f'Event type: {ev.type}: {policy}')


async def entitlements_loop(namespace: str) -> None:
    async for event in event_loop(namespace, 'entitlements'):
        ev = Event(event)
        entitlement = entitlement_load(ev.object.spec)
        print(f'Event type: {ev.type}: {entitlement}')


async def conditions_loop(namespace: str) -> None:
    async for event in event_loop(namespace, 'conditions'):
        ev = Event(event)
        condition = condition_load(ev.object.spec)
        print(f'Event type: {ev.type}: {condition}')
