from copy import deepcopy
import datetime
from functools import cached_property
from pathlib import Path
from typing import Set, TypeVar, Dict, Optional, Tuple, Literal, Any, Iterable

import typedload
import yaml
from attr import attrib, attrs, evolve

from appgate.openapi import Entity_T, K8S_APPGATE_DOMAIN, K8S_APPGATE_VERSION
from appgate.client import AppgateClient, EntityClient
from appgate.logger import log

__all__ = [
    'AppgateState',
    'AppgatePlan',
    'EntitiesSet',
    'create_appgate_plan',
    'appgate_plan_apply',
    'entities_conflict_summary',
    'appgate_plan_apply',
    'resolve_entity',
    'resolve_entities',
]


BUILTIN_TAG = 'builtin'


T = TypeVar('T', bound=Entity_T)


class EntitiesSet:
    def __init__(self, entities: Optional[Set[Entity_T]] = None,
                 entities_by_name: Optional[Dict[str, Entity_T]] = None,
                 entities_by_id: Optional[Dict[str, Entity_T]] = None) -> None:
        self.entities: Set[T] = entities or set()
        if entities_by_name:
            self.entities_by_name = entities_by_name
        else:
            self.entities_by_name = {}
            for e in self.entities:
                self.entities_by_name[e.name] = e
        if entities_by_id:
            self.entities_by_id = entities_by_id
        else:
            self.entities_by_id = {}
            for e in self.entities:
                self.entities_by_id[e.id] = e

    def __str__(self) -> str:
        return str(self.entities)

    def __copy__(self) -> 'EntitiesSet':
        return EntitiesSet(entities=deepcopy(self.entities),
                           entities_by_name=deepcopy(self.entities_by_name),
                           entities_by_id=deepcopy(self.entities_by_id))

    def builtin_entities(self) -> 'EntitiesSet':
        return EntitiesSet(entities={e for e in self.entities if 'builtin' in e.tags})

    def add(self, entity: Entity_T) -> None:
        if entity.name in self.entities_by_name:
            # Entity is already registered, so this is in the best case a modification
            return self.modify(entity)
        self.entities.add(entity)
        # Register it in the maps of ids and names
        self.entities_by_name[entity.name] = entity
        self.entities_by_id[entity.id] = entity

    def delete(self, entity: Entity_T) -> None:
        self.entities.remove(entity)
        if entity.name in self.entities_by_name:
            registered_id = self.entities_by_name[entity.name].id
            del self.entities_by_name[entity.name]
            del self.entities_by_id[registered_id]
        if entity.id in self.entities_by_id:
            del self.entities_by_id[entity.id]

    def modify(self, entity: Entity_T) -> None:
        if entity.name not in self.entities_by_name:
            # Not yet in the system, register it with its own id
            return self.add(entity)
        # All the entities expect the one being modified
        self.entities = {e for e in self.entities if e.name != entity.name}
        # Replace always the id with the one registered in the system
        self.entities.add(evolve(entity, id=self.entities_by_name[entity.name].id))


def entities_op(entity_set: EntitiesSet, entity: Entity_T,
                op: Literal['ADDED', 'DELETED', 'MODIFIED'],
                current_entities: EntitiesSet) -> None:
    # Current state should always contain the real id!!
    cached_entity = current_entities.entities_by_name.get(entity.name)
    if cached_entity:
        entity = evolve(entity, id=cached_entity.id)
    if op == 'ADDED':
        entity_set.add(entity)
    elif op == 'DELETED':
        entity_set.delete(entity)
    elif op == 'MODIFIED':
        entity_set.modify(entity)


def dump_entity(entity: Entity_T, entity_type: str) -> Dict[str, Any]:
     return {
        'apiVersion': f'{K8S_APPGATE_DOMAIN}/{K8S_APPGATE_VERSION}',
        'kind': entity_type,
        'metadata': {
            'name': entity.name
        },
        'spec': typedload.dump(entity)
     }


def dump_entities(entities: Iterable[Entity_T], dump_file: Path, entity_type: str) -> None:
    if entities:
        with dump_file.open('w') as f:
            for e in entities:
                f.write(yaml.dump(dump_entity(e, entity_type), default_flow_style=False))
                f.write('---\n')


@attrs()
class AppgateState:
    entities_set: Dict[str, EntitiesSet] = attrib()

    def with_entity(self, entity: Entity_T, op: str,
                    current_appgate_state: 'AppgateState') -> None:
        """
        Get the entity with op and register in the current state
        These entities are coming from k8s so they don't have any id
        """
        entitites = lambda state: state.entities_set.get(type(entity).__name__)
        if not entitites:
            log.error('[appgate-operator] Unknown entity type: %s', type(entity))
            return
        # TODO: Fix linter here!
        entities_op(entitites(self), entity, op, entitites(current_appgate_state))  # type: ignore

    def copy(self, entities_set: Dict[str, EntitiesSet]) -> 'AppgateState':
        new_entities_set = {}
        for k, v in self.entities_set.items():
            if k in entities_set:
                new_entities_set[k] = entities_set[k]
            else:
                new_entities_set[k] = v
        return AppgateState(new_entities_set)

    def dump(self, path: Optional[Path] = None) -> None:
        dump_dir = path or Path(str(datetime.date.today()))
        dump_dir.mkdir(exist_ok=True)
        # TODO: Discover the entity kind
        for k, v in self.entities_set.items():
            dump_entities(self.entities_set[k].entities, dump_dir / f'{k.lower()}.yaml', k)


def merge_entities(share: EntitiesSet, create: EntitiesSet, modify: EntitiesSet,
                   errors: Optional[Set[T]] = None) -> EntitiesSet:
    entities = set()
    errors = errors or set()
    entities.update(share.entities)
    entities.update({e for e in modify.entities if e.id not in errors})
    entities.update({e for e in create.entities if e.id not in errors})
    return EntitiesSet(entities)


@attrs
class Plan:
    share: EntitiesSet = attrib(factory=EntitiesSet)
    delete: EntitiesSet = attrib(factory=EntitiesSet)
    create: EntitiesSet = attrib(factory=EntitiesSet)
    modify: EntitiesSet = attrib(factory=EntitiesSet)
    errors: Optional[Set[str]] = attrib(default=None)

    @cached_property
    def expected_entities(self) -> EntitiesSet:
        """
        Set with all the names in the system in this plan
        """
        return merge_entities(self.share, self.create, self.modify)

    @cached_property
    def entities(self) -> EntitiesSet:
        entities = merge_entities(share=self.share, create=self.create, modify=self.modify,  # type: ignore
                                  errors=self.errors)
        entities.entities.update({e for e in self.delete.entities if e.id in (self.errors or set())})
        return entities

    @cached_property
    def expected_names(self) -> Dict[str, str]:
        """
        Set with all the names in the system in this plan
        """
        return {k: v.id for k, v in self.expected_entities.entities_by_name.items()}

    @cached_property
    def expected_ids(self) -> Set[str]:
        """
        Set with all the ids in the system in this plan
        """
        return set(self.expected_entities.entities_by_id.keys())

    @cached_property
    def needs_apply(self) -> bool:
        return len(self.delete.entities or self.create.entities or self.modify.entities) > 0


# TODO: Deal with repeated code
async def plan_apply(plan: Plan, namespace: str,
                     entity_client: Optional[EntityClient] = None) -> Plan:
    errors = set()
    for e in plan.create.entities:
        if not e.id:
            log.error('[appgate-operator/%s] Trying to create instance %s without id',
                      namespace, e)
        log.info('[appgate-operator/%s] + %s %s [%s]', namespace, type(e), e.name, e.id)
        if entity_client:
            if not await entity_client.post(e):
                errors.add(e.id)
    for e in plan.modify.entities:
        if not e.id:
            log.error('[appgate-operator/%s] Trying to modify instance %s without id',
                      namespace, e)
            continue
        log.info('[appgate-operator/%s] * %s %s [%s]', namespace, type(e), e.name, e.id)
        if entity_client:
            if not await entity_client.put(e):
                errors.add(e.id)
    for e in plan.delete.entities:
        if not e.id:
            log.error('[appgate-operator/%s] Trying to delete instance %s without id',
                      namespace, e)
            continue
        log.info('[appgate-operator/%s] - %s %s [%s]', namespace, type(e), e.name, e.id)
        if entity_client:
            if not await entity_client.delete(e.id):
                errors.add(e.id)

    for e in plan.share.entities:
        if not e.id:
            log.error('[appgate-operator/%s] Trying to delete instance %s without id',
                      namespace, e)
            continue
        log.info('[appgate-operator/%s] = %s %s [%s]', namespace, type(e), e.name, e.id)

    has_errors = len(errors) > 0
    return Plan(create=plan.create,
                share=plan.share,
                delete=plan.delete,
                modify=plan.modify,
                errors=errors if has_errors else None)


# Policies have entitlements that have conditions, so conditions always first.
@attrs
class AppgatePlan:
    entities_plan: Dict[str, Plan] = attrib()

    @cached_property
    def appgate_state(self) -> AppgateState:
        return AppgateState({k: v.entities for k, v in self.entities_plan.items()})

    @cached_property
    def needs_apply(self) -> bool:
        return any(v.needs_apply for v in self.entities_plan.values())


async def appgate_plan_apply(appgate_plan: AppgatePlan, namespace: str,
                             entity_clients: Dict[str, EntityClient]) -> AppgatePlan:
    log.info('[appgate-operator/%s] AppgatePlan Summary:', namespace)
    entities_plan = {k: plan_apply(v, namespace=namespace, entity_client=entity_clients.get(k))
                     for k, v in appgate_plan.entities_plan.items()}
    return AppgatePlan(entities_plan=entities_plan)


def entities_conflict_summary(conflicts: Dict[str, Optional[Dict[str, Set[str]]]],
                              namespace: str) -> None:
    for k, v in conflicts.items():
        for e, xs in v.items():
            p1 = "they are" if len(xs) > 1 else "it is"
            log.error('[appgate-operator/%s] Entity: %s references entity: %s, but %s not defined '
                      'in the system.', namespace, e, ','.join(xs), p1)


def compare_entities(current: EntitiesSet,
                     expected: EntitiesSet) -> Plan:
    current_entities = current.entities
    current_names = {e.name for e in current_entities}
    expected_entities = expected.entities
    expected_names = {e.name for e in expected_entities}
    shared_names = current_names.intersection(expected_names)
    to_delete = EntitiesSet(set(filter(
        lambda e: e.name not in expected_names and BUILTIN_TAG not in (e.tags or frozenset()),
        current_entities)))
    to_create = EntitiesSet(set(filter(
        lambda e: e.name not in current_names and e.name not in shared_names,
        expected_entities)))
    to_modify = EntitiesSet(set(filter(
        lambda e: e.name in shared_names and e not in current_entities, expected_entities)))
    to_share = EntitiesSet(set(filter(
        lambda e: e.name in shared_names and e in current_entities, expected_entities)))
    return Plan(delete=to_delete,
                create=to_create,
                modify=to_modify,
                share=to_share)


def resolve_entity(entity: Entity_T,
                   field: str,
                   names: Dict[str, Entity_T],
                   ids: Dict[str, Entity_T],
                   missing_dependencies: Dict[str, Set[str]]) -> Optional[Entity_T]:
    new_dependencies = set()
    if not hasattr(entity, field):
        raise Exception(f'Object {entity} has not field {field}.')
    dependencies = getattr(entity, field)
    for dependency in dependencies:
        if dependency in ids:
            # dependency is an id
            new_dependencies.add(dependency)
        elif dependency in names and names[dependency].id:
            # dependency is a name
            new_dependencies.add(names[dependency].id)
        else:
            if entity.name not in missing_dependencies:
                missing_dependencies[entity.name] = set()
            missing_dependencies[entity.name].add(dependency)
    if new_dependencies:
        return evolve(entity, **{field: frozenset(new_dependencies)})
    return None


def resolve_entities(e1: EntitiesSet, e2: EntitiesSet, field: str) -> Tuple[EntitiesSet,
                                                                            Optional[Dict[str, Set[str]]]]:
    to_remove = set()
    to_add = set()
    missing_entities: Dict[str, Set[str]] = {}
    e1_set = e1.entities.copy()
    names = e2.entities_by_name
    ids = e2.entities_by_id
    for e in e1_set:
        new_e = resolve_entity(e, field, names, ids, missing_entities)
        if new_e:
            to_remove.add(e)
            to_add.add(new_e)
    e1_set.difference_update(to_remove)
    e1_set.update(to_add)
    if len(missing_entities) > 0:
        return EntitiesSet(e1_set), missing_entities,
    return EntitiesSet(e1_set), None


def create_appgate_plan(current_state: AppgateState,
                        expected_state: AppgateState) -> AppgatePlan:
    """
    Creates a new AppgatePlan to apply
    """
    entities_plan = {k: compare_entities(current_state.entities_set[k], v)
                     for k, v in expected_state.entities_set.items()}
    return AppgatePlan(entities_plan=entities_plan)


