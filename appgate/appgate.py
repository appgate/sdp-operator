import kubernetes
from appgate.types import entitlement_load, Event

DOMAIN = 'beta.appgate.com'
RESOURCE_VERSION = 'v1'

__all__ = [
    'event_loop'
]


def event_loop() -> None:
    kubernetes.config.load_kube_config()
    crds = kubernetes.client.CustomObjectsApi()
    w = kubernetes.watch.Watch()
    for event in w.stream(crds.list_namespaced_custom_object, DOMAIN, 'v1',
                          'appgate-test-1', 'entitlements'):
        entitlement = entitlement_load(ev.object.spec)
        print(f'Event type: {ev.type}: {entitlement}')
