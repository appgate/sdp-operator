import datetime
from typing import Dict, Any, FrozenSet, Optional, List
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
class OperatorArguments:
    namespace: Optional[str] = attrib(default=None)
    spec_directory: Optional[str] = attrib(default=None)
    dry_run: bool = attrib(default=False)
    host: Optional[str] = attrib(default=None)
    user: Optional[str] = attrib(default=None)
    password: Optional[str] = attrib(default=None)
    two_way_sync: bool = attrib(default=True)
    timeout: str = attrib(default='30')
    cleanup: bool = attrib(default=True)
    target_tags: Optional[List[str]] = attrib(default=None)


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

    def changed_generation(self) -> bool:
        mt = self.value.appgate_metadata
        if mt.current_generation > mt.latest_generation:
            return True
        return False

    def updated(self, other: object) -> bool:
        assert isinstance(other, self.__class__)
        mt = self.value.appgate_metadata
        if getattr(other.value, 'updated', None) is not None:
            return mt.modified > other.value.updated
        return False

    def needs_update(self, other: object) -> bool:
        if self.changed_generation():
            return True
        if self.updated(other):
            return True
        return False

    def has_secrets(self) -> bool:
        # We have passwords use modified/created
        entity_mt = self.value._entity_metadata
        return len(entity_mt.get('passwords', {})) > 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            raise Exception(f'Wrong other argument {other}')
        if not self.has_secrets():
            return self.value == other.value
        if self.needs_update(other):
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
