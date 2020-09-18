import datetime
from typing import Dict, Any, FrozenSet
from attr import attrib, attrs, evolve

from appgate.openapi.types import Entity_T


__all__ = [
    'K8SEvent',
    'EventObject',
    'AppgateEvent',
    'EntityWrapper',
    'LatestEntityGeneration',
]


@attrs(slots=True, frozen=True)
class EventObject:
    spec: Dict[str, Any] = attrib()
    metadata: Dict[str, Any] = attrib()
    kind: str = attrib()


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

    def _needs_update(self) -> bool:
        mt = self.value.appgate_metadata
        if mt.current_generation > mt.latest_generation:
            return True
        if getattr(self.value, 'updated', None) is None:
            return True
        if mt.modified > self.value.updated:
            return True
        return False

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            raise Exception(f'Wrong other argument {other}')
        # We have passwords use modified/created
        entity_mt = self.value._entity_metadata
        if len(entity_mt.get('passwords', {})) == 0:
            return self.value == other.value
        if self._needs_update():
            return False
        return self.value == other.value

    def __hash__(self) -> int:
        return self.value.__hash__()

    def __repr__(self):
        return self.value.__repr__()


@attrs(slots=True, frozen=True)
class LatestEntityGeneration:
    generation: int = attrib(default=0)
    modified: datetime.datetime = attrib(default=datetime.datetime.now().astimezone())
