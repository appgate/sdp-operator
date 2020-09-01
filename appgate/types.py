from typing import Dict, Any
from attr import attrib, attrs

from appgate.openapi.types import Entity_T


__all__ = [
    'K8SEvent',
    'EventObject',
    'AppgateEvent',
]


class EventObject:
    def __init__(self, data: Dict[str, Any]) -> None:
        self.kind = data['kind']
        self.api_version = data['apiVersion']
        self.metadata = data['metadata']
        self.spec = data['spec']


class K8SEvent:
    def __init__(self, data: Dict[str, Any]) -> None:
        self.type = data['type']
        self.object = EventObject(data['object'])


@attrs(slots=True, frozen=True)
class AppgateEvent:
    op: str = attrib()
    entity: Entity_T = attrib()
