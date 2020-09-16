import datetime
from typing import Dict, Any, FrozenSet
from attr import attrib, attrs, evolve

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


class EntityWrapper:
    def __init__(self, entity: Entity_T) -> None:
        self.value = entity

    @property
    def name(self) -> str:
        return self.value.name

    @property
    def id(self) -> str:
        return self.value.id

    @property
    def tags(self) -> FrozenSet[str]:
        return self.value.tags

    def with_id(self, id: str) -> 'EntityWrapper':
        return EntityWrapper(evolve(self.value, id=id))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            raise Exception(f'Wrong other argument {other}')
        return self.value == other.value

    def __hash__(self) -> int:
        return self.value.__hash__()

    def __repr__(self):
        return self.value.__repr__()


@attrs(slots=True, frozen=True)
class EntityVersion:
    type: str = attrib()
    name: str = attrib()
    version: str = attrib()
    timestamp: datetime.datetime = attrib()
