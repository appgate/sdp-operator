import datetime
from typing import Dict, Any, FrozenSet
from attr import attrib, attrs, evolve

from appgate.openapi.types import Entity_T


__all__ = [
    'K8SEvent',
    'EventObject',
    'AppgateEvent',
    'EntityWrapper',
    'EventObjectMetadata',
]


@attrs(slots=True, frozen=True)
class EventObjectMetadata:
    created: datetime.datetime = attrib(metadata={
        'name': 'creationTimestamp'
    })
    name: str = attrib()
    namespace: str = attrib()
    generation: int = attrib()
    resource_version: str = attrib(metadata={
        'name': 'resourceVersion'
    })


@attrs(slots=True, frozen=True)
class EventObject:
    spec: Dict[str, Any] = attrib()
    metadata: EventObjectMetadata = attrib()
    kind: str = attrib()
    api_version: str = attrib(metadata={
        'name': 'apiVersion'
    })

@attrs(slots=True, frozen=True)
class K8SEvent:
    type: str = attrib()
    object: EventObject = attrib()


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
