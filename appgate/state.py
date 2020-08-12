from copy import deepcopy
import datetime
from functools import cached_property
from pathlib import Path
from typing import Set, TypeVar, Generic, Dict, Optional, cast, Tuple, Literal, Any, Iterable

import typedload
import yaml
from attr import attrib, attrs, evolve

from appgate.openapi import Entity_T
from appgate.client import AppgateClient, EntityClient
from appgate.logger import log
from appgate.types import Policy, Condition, Entitlement, AppgateEntity, DOMAIN,\
    RESOURCE_VERSION

__all__ = [
    'AppgateState',
    'AppgatePlan',
    'EntitiesSet',
    'create_appgate_plan',
    'appgate_plan_apply',
    'appgate_plan_errors_summary',
    'appgate_plan_apply',
    'resolve_entitlements',
    'resolve_policies',
]


BUILTIN_TAG = 'builtin'


T = TypeVar('T', bound=Entity_T)


class EntitiesSet(Generic[T]):
    def __init__(self, entities: Optional[Set[T]] = None,
                 entities_by_name: Optional[Dict[str, T]] = None,
                 entities_by_id: Optional[Dict[str, T]] = None) -> None:
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

    def __copy__(self) -> 'EntitiesSet[T]':
        return EntitiesSet(entities=deepcopy(self.entities),
                           entities_by_name=deepcopy(self.entities_by_name),
                           entities_by_id=deepcopy(self.entities_by_id))

    def builtin_entities(self) -> 'EntitiesSet[T]':
        return EntitiesSet(entities={e for e in self.entities if 'builtin' in e.tags})

    def add(self, entity: T) -> None:
        if entity.name in self.entities_by_name:
            # Entity is already registered, so this is in the best case a modification
            return self.modify(entity)
        self.entities.add(entity)
        # Register it in the maps of ids and names
        self.entities_by_name[entity.name] = entity
        self.entities_by_id[entity.id] = entity

    def delete(self, entity: T) -> None:
        self.entities.remove(entity)
        if entity.name in self.entities_by_name:
            registered_id = self.entities_by_name[entity.name].id
            del self.entities_by_name[entity.name]
            del self.entities_by_id[registered_id]
        if entity.id in self.entities_by_id:
            del self.entities_by_id[entity.id]

    def modify(self, entity: T) -> None:
        if entity.name not in self.entities_by_name:
            # Not yet in the system, register it with its own id
            return self.add(entity)
        # All the entities expect the one being modified
        self.entities = {e for e in self.entities if e.name != entity.name}
        # Replace always the id with the one registered in the system
        self.entities.add(evolve(entity, id=self.entities_by_name[entity.name].id))


def entities_op(entity_set: EntitiesSet, entity: AppgateEntity,
                op: Literal['ADDED', 'DELETED', 'MODIFIED'],
                current_entities: EntitiesSet[AppgateEntity]) -> None:
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
        'apiVersion': f'{DOMAIN}/{RESOURCE_VERSION}',
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
    policies: EntitiesSet[Policy] = attrib()
    conditions: EntitiesSet[Condition] = attrib()
    entitlements: EntitiesSet[Entitlement] = attrib()

    def with_entity(self, entity: AppgateEntity, op: str,
                    current_appgate_state: 'AppgateState') -> None:
        """
        Get the entity with op and register in the current state
        These entities are coming from k8s so they don't have any id
        """
        known_entities = {
            Policy: lambda s: s.policies,
            Entitlement: lambda s: s.entitlements,
            Condition: lambda s: s.conditions,
        }
        entitites = known_entities.get(type(entity))
        if not entitites:
            log.error('[appgate-operator] Unknown entity type: %s', type(entity))
            return
        # TODO: Fix linter here!
        entities_op(entitites(self), entity, op, entitites(current_appgate_state))  # type: ignore

    def copy(self, entitlements: Optional[EntitiesSet[Entitlement]] = None,
             policies: Optional[EntitiesSet[Policy]] = None,
             conditions: Optional[EntitiesSet[Condition]] = None) -> 'AppgateState':
        return AppgateState(policies=policies or self.policies,
                            entitlements=entitlements or self.entitlements,
                            conditions=conditions or self.conditions)

    def dump(self, path: Optional[Path] = None) -> None:
        dump_dir = path or Path(str(datetime.date.today()))
        dump_dir.mkdir(exist_ok=True)
        # TODO: Discover the entity kind
        dump_entities(self.conditions.entities, dump_dir / 'conditions.yaml', 'Condition')
        dump_entities(self.entitlements.entities, dump_dir / 'entitlements.yaml', 'Entitlement')
        dump_entities(self.policies.entities, dump_dir / 'policies.yaml', 'Policy')


def merge_entities(share: EntitiesSet[T], create: EntitiesSet[T], modify: EntitiesSet[T],
                   errors: Optional[Set[T]] = None) -> EntitiesSet[T]:
    entities = set()
    errors = errors or set()
    entities.update(share.entities)
    entities.update({e for e in modify.entities if e.id not in errors})
    entities.update({e for e in create.entities if e.id not in errors})
    return EntitiesSet(entities)


@attrs
class Plan(Generic[T]):
    share: EntitiesSet[T] = attrib(factory=EntitiesSet)
    delete: EntitiesSet[T] = attrib(factory=EntitiesSet)
    create: EntitiesSet[T] = attrib(factory=EntitiesSet)
    modify: EntitiesSet[T] = attrib(factory=EntitiesSet)
    errors: Optional[Set[str]] = attrib(default=None)

    @cached_property
    def expected_entities(self) -> EntitiesSet[T]:
        """
        Set with all the names in the system in this plan
        """
        return merge_entities(self.share, self.create, self.modify)

    @cached_property
    def entities(self) -> EntitiesSet[T]:
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
            if not await entity_client.post(cast(AppgateEntity, e)):
                errors.add(e.id)
    for e in plan.modify.entities:
        if not e.id:
            log.error('[appgate-operator/%s] Trying to modify instance %s without id',
                      namespace, e)
            continue
        log.info('[appgate-operator/%s] * %s %s [%s]', namespace, type(e), e.name, e.id)
        if entity_client:
            if not await entity_client.put(cast(AppgateEntity, e)):
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
    policies: Plan[Policy] = attrib()
    entitlements: Plan[Entitlement] = attrib()
    conditions: Plan[Condition] = attrib()
    entitlement_conflicts: Optional[Dict[str, Set[str]]] = attrib(default=None)
    policy_conflicts: Optional[Dict[str, Set[str]]] = attrib(default=None)

    @cached_property
    def appgate_state(self) -> AppgateState:
        policies = self.policies.entities
        entitlements = self.entitlements.entities
        conditions = self.conditions.entities
        return AppgateState(
            policies=policies,
            entitlements=entitlements,
            conditions=conditions)

    @cached_property
    def needs_apply(self) -> bool:
        return any([self.policies.needs_apply,
                    self.entitlements.needs_apply,
                    self.conditions.needs_apply])


# TODO: Deal with errors here
async def appgate_plan_apply(appgate_plan: AppgatePlan, namespace: str,
                             appgate_client: Optional[AppgateClient] = None) -> AppgatePlan:
    log.info('[appgate-operator/%s] AppgatePlan Summary:', namespace)
    conditions_plan = await plan_apply(appgate_plan.conditions, namespace,
                                       entity_client=appgate_client.conditions if appgate_client else None)
    entitlements_plan = await plan_apply(appgate_plan.entitlements, namespace,
                                         entity_client=appgate_client.entitlements if appgate_client else None)
    policies_plan = await plan_apply(appgate_plan.policies, namespace=namespace,
                                     entity_client=appgate_client.policies if appgate_client else None)

    return AppgatePlan(conditions=conditions_plan,
                       entitlements=entitlements_plan,
                       policies=policies_plan)


def appgate_plan_errors_summary(appgate_plan: AppgatePlan, namespace: str) -> None:
    if appgate_plan.entitlement_conflicts:
        for entitlement, conditions in appgate_plan.entitlement_conflicts.items():
            p1 = "they are" if len(conditions) > 1 else "it is"
            log.error('[appgate-operator/%s] Entitlement: %s references conditions: %s, but %s not defined '
                      'in the system.', namespace, entitlement, ','.join(conditions), p1)

    if appgate_plan.policy_conflicts:
        for policy, entitlements in appgate_plan.policy_conflicts.items():
            p1 = "they are" if len(entitlements) > 1 else "it is"
            log.error('[appgate-operator/%s] Policy: %s references entitlements: %s, but %s not defined '
                      'in the system.', namespace, policy, ','.join(entitlements), p1)


def compare_entities(current: EntitiesSet[T],
                     expected: EntitiesSet[T]) -> Plan[T]:
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


# TODO: These functions do the same!
def resolve_entitlement(entitlement: Entitlement,
                        names: Dict[str, Condition],
                        ids: Dict[str, Condition],
                        missing_conditions: Dict[str, Set[str]]) -> Optional[Entitlement]:
    new_conditions = set()
    for condition in entitlement.conditions:
        if condition in ids:
            # condition is an id
            new_conditions.add(condition)
        elif condition in names and names[condition].id:
            # condition is a name
            new_conditions.add(names[condition].id)
        else:
            if entitlement.name not in missing_conditions:
                missing_conditions[entitlement.name] = set()
            missing_conditions[entitlement.name].add(condition)
    if new_conditions:
        return evolve(entitlement, conditions=frozenset(new_conditions))
    return None


def resolve_entitlements(entitlements: EntitiesSet[Entitlement],
                         conditions: EntitiesSet[Condition]) -> Tuple[EntitiesSet[Entitlement],
                                                                      Optional[Dict[str, Set[str]]]]:
    to_remove = set()
    to_add = set()
    missing_conditions: Dict[str, Set[str]] = {}
    entitlements_set = entitlements.entities.copy()
    names = conditions.entities_by_name
    ids = conditions.entities_by_id
    for entitlement in entitlements_set:
        new_entitlement = resolve_entitlement(entitlement, names, ids, missing_conditions)
        if new_entitlement:
            to_remove.add(entitlement)
            to_add.add(new_entitlement)
    entitlements_set.difference_update(to_remove)
    entitlements_set.update(to_add)
    if len(missing_conditions) > 0:
        return EntitiesSet(entitlements_set), missing_conditions,
    return EntitiesSet(entitlements_set), None


def resolve_policy(policy: Policy,
                   names: Dict[str, Entitlement],
                   ids: Dict[str, Entitlement],
                   missing_entitlements: Dict[str, Set[str]]) -> Optional[Policy]:
    new_entitlements = set()
    for entitlement in policy.entitlements:
        if entitlement in ids:
            # entitlement is an id
            new_entitlements.add(entitlement)
        elif entitlement in names and names[entitlement].id:
            # entitlement is a name
            new_entitlements.add(names[entitlement].id)
        else:
            if policy.name not in missing_entitlements:
                missing_entitlements[policy.name] = set()
            missing_entitlements[policy.name].add(entitlement)
    if new_entitlements:
        return evolve(policy, entitlements=frozenset(new_entitlements))
    return None


def resolve_policies(policies: EntitiesSet[Policy],
                     entitlements: EntitiesSet[Entitlement]) -> Tuple[EntitiesSet[Policy],
                                                                      Optional[Dict[str, Set[str]]]]:
    to_remove = set()
    to_add = set()
    missing_entitlements: Dict[str, Set[str]] = {}
    policies_set = policies.entities.copy()
    names = entitlements.entities_by_name
    ids = entitlements.entities_by_id
    for policy in policies_set:
        new_policy = resolve_policy(policy, names, ids, missing_entitlements)
        if new_policy:
            to_remove.add(policy)
            to_add.add(new_policy)
    policies_set.difference_update(to_remove)
    policies_set.update(to_add)
    if len(missing_entitlements) > 0:
        return EntitiesSet(policies_set), missing_entitlements,
    return EntitiesSet(policies_set), None


def create_appgate_plan(current_state: AppgateState,
                        expected_state: AppgateState,
                        entitlement_conflicts: Optional[Dict[str, Set[str]]],
                        policy_conflicts: Optional[Dict[str, Set[str]]]) -> AppgatePlan:
    """
    Creates a new AppgatePlan to apply
    """
    conditions_plan = cast(Plan[Condition],
                           compare_entities(current_state.conditions,
                                            expected_state.conditions))
    entitlements_plan = cast(Plan[Entitlement],
                             compare_entities(current_state.entitlements,
                                              expected_state.entitlements))
    policies_plan = cast(Plan[Policy],
                         compare_entities(current_state.policies,
                                          expected_state.policies))
    return AppgatePlan(policies=policies_plan,
                       entitlements=entitlements_plan,
                       conditions=conditions_plan,
                       entitlement_conflicts=entitlement_conflicts,
                       policy_conflicts=policy_conflicts)

