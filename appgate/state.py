import difflib
import json
import re
import sys
from copy import deepcopy
import datetime
import time
from functools import cached_property
from logging import DEBUG
from pathlib import Path
from typing import Set, Dict, Optional, Tuple, Literal, Any, Iterable, List, FrozenSet

import yaml
from attr import attrib, attrs, evolve

from appgate.attrs import K8S_DUMPER, DIFF_DUMPER
from appgate.client import EntityClient
from appgate.logger import log
from appgate.openapi.openapi import K8S_APPGATE_DOMAIN, K8S_APPGATE_VERSION
from appgate.openapi.parser import ENTITY_METADATA_ATTRIB_NAME
from appgate.openapi.types import Entity_T, APISpec, PYTHON_TYPES
from appgate.openapi.utils import is_entity_t, has_name, is_builtin, get_passwords

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
    'resolve_appgate_state',
    'compare_entities',
    'compute_diff',
]


class EntitiesSet:
    def __init__(self, entities: Optional[Set[Entity_T]] = None,
                 entities_by_name: Optional[Dict[str, Entity_T]] = None,
                 entities_by_id: Optional[Dict[str, Entity_T]] = None) -> None:
        self.entities: Set[Entity_T] = entities or set()
        if entities_by_name:
            self.entities_by_name = entities_by_name
        else:
            self.entities_by_name = {}
            for e in self.entities:
                if is_entity_t(e):
                    self.entities_by_name[e.name] = e
        if entities_by_id:
            self.entities_by_id = entities_by_id
        else:
            self.entities_by_id = {}
            for e in self.entities:
                if is_entity_t(e):
                    self.entities_by_id[e.id] = e

    def __str__(self) -> str:
        return str(self.entities)

    def __copy__(self) -> 'EntitiesSet':
        return EntitiesSet(entities=deepcopy(self.entities),
                           entities_by_name=deepcopy(self.entities_by_name),
                           entities_by_id=deepcopy(self.entities_by_id))

    def builtin_entities(self) -> 'EntitiesSet':
        return EntitiesSet(entities={e for e in self.entities if is_builtin(e)})

    def add(self, entity: Entity_T) -> None:
        if entity.name in self.entities_by_name:
            # Entity is already registered, so this is in the best case a modification
            return self.modify(entity)
        self.entities.add(entity)
        # Register it in the maps of ids and names
        self.entities_by_name[entity.name] = entity
        self.entities_by_id[entity.id] = entity

    def delete(self, entity: Entity_T) -> None:
        if entity in self.entities:
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
    """
    name sould match this regexp:
       '[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*'
    """
    entity_name = entity.name if has_name(entity) else entity_type.lower()
    # This is ugly but we need to go from a bigger set of strings
    # into a smaller one :(
    entity_name = re.sub('[^a-z0-9-.]+', '-', entity_name.strip().lower())
    entity_mt = getattr(entity, ENTITY_METADATA_ATTRIB_NAME, {})
    singleton = entity_mt.get('singleton', False)
    metadata = {
        'name': entity_name,
        'passwords': get_passwords(entity),
        'singleton': singleton
    }
    if not singleton:
        metadata['uuid'] = entity.id
    return {
        'apiVersion': f'{K8S_APPGATE_DOMAIN}/{K8S_APPGATE_VERSION}',
        'kind': entity_type,
        'metadata': metadata,
        'spec': K8S_DUMPER.dump(entity)
    }


def dump_entities(entities: Iterable[Entity_T], dump_file: Optional[Path],
                  entity_type: str) -> Optional[List[str]]:
    entity_passwords = None
    if not entities:
        log.warning(f'No entities of type: {entity_type} found')
        return None
    f = dump_file.open('w') if dump_file else sys.stdout
    for i, e in enumerate(entities):
        if i > 0:
            f.write('---\n')
        dumped_entity = dump_entity(e, entity_type)
        entity_passwords = dumped_entity['metadata'].get('passwords')
        yaml_dump = yaml.dump(dumped_entity, default_flow_style=False)
        f.write(yaml_dump)
    if dump_file:
        f.close()
    return entity_passwords


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

    def dump(self, output_dir: Optional[Path] = None, stdout: bool = False) -> None:
        dump_dir = None
        if not stdout:
            output_dir_format = f'{str(datetime.date.today())}_{time.strftime("%H-%M")}-entities'
            dump_dir = output_dir or Path(output_dir_format)
            dump_dir.mkdir(exist_ok=True)
        password_fields = {}
        for (i, (k, v)) in enumerate(self.entities_set.items()):
            if stdout and i > 0:
                print('---\n')
            p = dump_dir / f'{k.lower()}.yaml' if dump_dir else None
            entity_password_fields = dump_entities(self.entities_set[k].entities, p, k)
            if entity_password_fields:
               password_fields[k] = entity_password_fields
        print('Passwords found in entities:')
        for entity_name, pwd_fields in password_fields.items():
            print(f'+ Entity: {entity_name}')
            for password_field in pwd_fields:
                print(f'  - {password_field}')


def merge_entities(share: EntitiesSet, create: EntitiesSet, modify: EntitiesSet,
                   errors: Optional[Set[str]] = None) -> EntitiesSet:
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
    modifications_diff: Dict[str, List[str]] = attrib(factory=dict)
    errors: Optional[Set[str]] = attrib(default=None)

    @cached_property
    def expected_entities(self) -> EntitiesSet:
        """
        Set with all the names in the system in this plan
        """
        return merge_entities(self.share, self.create, self.modify)

    @cached_property
    def entities(self) -> EntitiesSet:
        entities = merge_entities(share=self.share, create=self.create, modify=self.modify,
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
        diff = plan.modifications_diff.get(e.name)
        if diff:
            log.debug('[appgate-operator/%s]    DIFF for %s:', namespace, e.name)
            for d in diff:
                log.debug('%s', d.rstrip())
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
                modifications_diff=plan.modifications_diff,
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
    entities_plan = {k: await plan_apply(v, namespace=namespace, entity_client=entity_clients.get(k))
                     for k, v in appgate_plan.entities_plan.items()}
    return AppgatePlan(entities_plan=entities_plan)


def entities_conflict_summary(conflicts: Dict[str, Dict[str, FrozenSet[str]]],
                              namespace: str) -> None:
    for k, field_values in conflicts.items():
        for field, errors in field_values.items():
            p1 = "they are" if len(errors) > 1 else "it is"
            log.error('[appgate-operator/%s] Entity: %s references: [%s] (field %s), but %s not defined '
                     'in the system.', namespace, k, ', '.join(errors), field, p1)


def compute_diff(e1: Entity_T, e2: Entity_T) -> List[str]:
    e1_dump = json.dumps(DIFF_DUMPER.dump(e1), indent=4)
    e2_dump = json.dumps(DIFF_DUMPER.dump(e2), indent=4)
    diff = list(
        difflib.unified_diff(e1_dump.splitlines(keepends=True),
                             e2_dump.splitlines(keepends=True), n=1))
    return diff


def compare_entities(current: EntitiesSet,
                     expected: EntitiesSet) -> Plan:
    current_entities = current.entities
    current_names = {e.name for e in current_entities}
    expected_entities = expected.entities
    expected_names = {e.name for e in expected_entities}
    shared_names = current_names.intersection(expected_names)
    to_delete = EntitiesSet(set(filter(
        lambda e: e.name not in expected_names and not is_builtin(e),
        current_entities)))
    to_create = EntitiesSet(set(filter(
        lambda e: e.name not in current_names and e.name not in shared_names,
        expected_entities)))
    to_modify = EntitiesSet(set(filter(
        lambda e: e.name in shared_names and e not in current_entities, expected_entities)))
    modifications_diff = {}
    if log.level == DEBUG:
        for e in to_modify.entities:
            current_entity = current.entities_by_name.get(e.name)
            if not current_entity:
                log.warning(f'Trying to compute diff for entity %s [%s] but not registered',
                            e.name, e.id)
                continue
            diff = compute_diff(current_entity, e)
            if diff:
                modifications_diff[e.name] = diff
    to_share = EntitiesSet(set(filter(
        lambda e: e.name in shared_names and e in current_entities, expected_entities)))

    return Plan(delete=to_delete,
                create=to_create,
                modify=to_modify,
                modifications_diff=modifications_diff,
                share=to_share)


def entity_t_attribute_names(entity: Entity_T) -> Iterable[str]:
    return map(lambda a: a.name, getattr(entity, '__attrs_attrs__', []))


def get_field(entity: Entity_T, paths: List[str]) -> Tuple[Optional[Any], Optional[str]]:
    f: Any = entity
    for i, p in enumerate(paths):
        log.debug('Getting field %s in %s', p, list(entity_t_attribute_names(f)))
        if isinstance(f, frozenset):
            return f, '.'.join(paths[i:])
        f = getattr(f, p, None)
        if f is None:
            if len(paths[i:]):
                # Last field is None, it could an optional field (should be checked here)
                return frozenset(), p
            else:
                return None, '.'.join(paths[i:])
    return f, None


def evolve_rec(entity: Entity_T, path: List[str], value: Any) -> Entity_T:
    if len(path) == 1:
        return evolve(entity, **{path[0]: value})
    field = getattr(entity, path[0], None)
    if field and type(field) not in PYTHON_TYPES:
        return evolve(entity,
                      **{path[0]: evolve_rec(field, path[1:], value)})
    raise Exception(f'Field {path[0]} not found in {entity}')


def resolve_entity(entity: Entity_T,
                   field: str,
                   names: Dict[str, Entity_T],
                   ids: Dict[str, Entity_T],
                   missing_dependencies: Dict[str, Dict[str, FrozenSet[str]]],
                   reverse: bool = False) -> Optional[Entity_T]:
    new_dependencies = set()
    missing_dependencies_set = set()
    log.debug(f'Getting field %s in entity %s', field, entity.__class__.__name__)
    dependencies, rest_fields = get_field(entity, field.split('.'))
    if dependencies is None:
        raise Exception(f'Object {entity} has not field {field}.')
    is_iterable = isinstance(dependencies, frozenset)
    if not is_iterable:
        dependencies = frozenset({dependencies})
    for dependency in dependencies:
        if type(dependency) not in PYTHON_TYPES and rest_fields:
            log.debug('dependency %s and rest_fields %s', dependency, rest_fields)
            resolve_entity(dependency, rest_fields, names, ids, missing_dependencies, reverse)
        elif dependency in ids:
            # dependency is an id
            if reverse:
                new_dependencies.add(ids[dependency].name)
            else:
                new_dependencies.add(dependency)
        elif dependency in names and names[dependency].id:
            # dependency is a name
            if reverse:
                new_dependencies.add(dependency)
            else:
                new_dependencies.add(names[dependency].id)
        else:
            missing_dependencies_set.add(dependency)
    if missing_dependencies_set:
        if entity.name not in missing_dependencies:
            missing_dependencies[entity.name] = {}
        missing_dependencies[entity.name][field] = frozenset(missing_dependencies_set)
    if new_dependencies:
        if is_iterable:
            return evolve_rec(entity, field.split('.'), frozenset(new_dependencies))
        else:
            return evolve_rec(entity, field.split('.'), list(new_dependencies)[0])
    return None


def resolve_entities(e1: EntitiesSet, dependencies: List[Tuple[EntitiesSet, str]],
                     reverse: bool = False) -> Tuple[EntitiesSet,
                                                     Optional[Dict[str,
                                                                   Dict[str, FrozenSet[str]]]]]:
    to_remove = set()
    to_add = set()
    missing_entities: Dict[str, Dict[str, FrozenSet[str]]] = {}
    e1_set = e1.entities.copy()
    for e in e1_set:
        new_e = None
        for dependency_entities, field in dependencies:
            names = dependency_entities.entities_by_name
            ids = dependency_entities.entities_by_id
            new_e = resolve_entity(new_e or e, field, names, ids, missing_entities, reverse)
        if new_e:
            to_remove.add(e)
            to_add.add(new_e)
    e1_set.difference_update(to_remove)
    e1_set.update(to_add)
    if len(missing_entities) > 0:
        return EntitiesSet(e1_set), missing_entities,
    return EntitiesSet(e1_set), None


def resolve_appgate_state(appgate_state: AppgateState,
                          api_spec: APISpec,
                          reverse: bool = False) -> Dict[str,
                                                         Dict[str, FrozenSet[str]]]:
    entities = api_spec.entities
    entities_sorted = api_spec.entities_sorted
    total_conflicts = {}
    log.info('[appgate-state] Validating expected state entities')
    log.debug('[appgate-state] Resolving dependencies in order: %s', entities_sorted)
    for entity_name in entities_sorted:
        for entity_dependency in entities[entity_name].dependencies:
            log.debug('[appgate-state] Checking dependencies %s for of type %s.%s',
                      entity_dependency.dependencies, entity_name,
                      entity_dependency.field_path)
            deps_tuple = []
            e1 = appgate_state.entities_set[entity_name]
            for d in entity_dependency.dependencies:
                deps_tuple.append((appgate_state.entities_set[d],
                                   entity_dependency.field_path,))
            new_e1, conflicts = resolve_entities(e1, deps_tuple, reverse)
            if conflicts:
                total_conflicts.update(conflicts)
            appgate_state.entities_set[entity_name] = new_e1
    return total_conflicts


def create_appgate_plan(current_state: AppgateState,
                        expected_state: AppgateState) -> AppgatePlan:
    """
    Creates a new AppgatePlan to apply
    """
    entities_plan = {k: compare_entities(current_state.entities_set[k], v)
                     for k, v in expected_state.entities_set.items()}
    return AppgatePlan(entities_plan=entities_plan)


