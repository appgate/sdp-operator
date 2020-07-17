import uuid
from copy import deepcopy
from functools import cached_property
from typing import Set, TypeVar, Generic, Dict, Optional, cast

from attr import attrib, attrs, evolve

from appgate.client import AppgateClient, EntityClient
from appgate.logger import log
from appgate.types import Policy, Condition, Entitlement, Entity_T, AppgateEntity


__all__ = [
    'AppgateState',
    'AppgatePlan',
    'create_appgate_plan',
    'appgate_plan_apply',
    'appgate_plan_errors_summary',
    'appgate_plan_apply',
]


BUILTIN_TAG = 'builtin'


T = TypeVar('T', bound=Entity_T)


class EntitiesSet(Generic[T]):
    def __init__(self, entities: Set[T],
                 entities_by_name: Optional[Dict[str, T]] = None) -> None:
        self.entities = entities
        if entities_by_name:
            self.entities_by_name = entities_by_name
        else:
            self.entities_by_name = {}
            for e in entities:
                self.entities_by_name[e.name] = e

    def __copy__(self) -> 'EntitiesSet[T]':
        return EntitiesSet(entities=deepcopy(self.entities),
                           entities_by_name=deepcopy(self.entities_by_name))

    def add(self, entity: T) -> None:
        if entity.name in self.entities_by_name:
            # Entity is already registered, so this is in the best case a modification
            return self.modify(entity)
        self.entities.add(entity)
        self.entities_by_name[entity.name] = entity

    def delete(self, entity: T) -> None:
        self.entities.remove(entity)
        if entity.name in self.entities_by_name:
            del self.entities_by_name[entity.name]

    def modify(self, entity: T) -> None:
        if entity.name not in self.entities_by_name:
            return self.add(entity)
        self.entities = {e for e in self.entities if e.name != entity.name}
        self.entities.add(evolve(entity, id=self.entities_by_name[entity.name].id))


def entities_op(entity_set: EntitiesSet, entity: AppgateEntity, op: str) -> None:
    if op == 'ADDED':
        entity_set.add(entity)
    elif op == 'DELETED':
        entity_set.delete(entity)
    elif op == 'MODIFIED':
        entity_set.modify(entity)


@attrs()
class AppgateState:
    policies: EntitiesSet[Policy] = attrib()
    conditions: EntitiesSet[Condition] = attrib()
    entitlements: EntitiesSet[Entitlement] = attrib()

    def with_entity(self, entity: AppgateEntity, op: str) -> None:
        """
        Get the entity with op and register in the current state
        These entities are coming from k8s so they don't have any id
        """
        known_entities = {
            Policy: lambda: self.policies,
            Entitlement: lambda: self.entitlements,
            Condition: lambda: self.conditions,
        }
        entitites = known_entities.get(type(entity))
        if not entitites:
            log.error('[appgate-operator] Unknown entity type: %s', type(entity))
            return
        entities_op(entitites(), entity, op)  # type: ignore


def merge_entities(share: Set[T], create: Set[T], modify: Set[T],
                   errors: Optional[Set[str]] = None) -> Set[T]:
    entities = set()
    errors = errors or set()
    entities.update(share)
    entities.update({e for e in modify if e.id not in errors})
    entities.update({e for e in create if e.id not in errors})
    return entities


@attrs
class Plan(Generic[T]):
    share: Set[T] = attrib(factory=set)
    delete: Set[T] = attrib(factory=set)
    create: Set[T] = attrib(factory=set)
    modify: Set[T] = attrib(factory=set)
    errors: Optional[Set[str]] = attrib(default=None)

    @cached_property
    def expected_entities(self) -> Set[T]:
        """
        Set with all the names in the system in this plan
        """
        return merge_entities(self.share, self.create, self.modify, errors=set())

    @cached_property
    def entities(self) -> Set[T]:
        entities = merge_entities(self.share, self.create, self.modify,
                                  errors=self.errors)
        entities.update({e for e in self.delete if e.id in (self.errors or set())})
        return entities

    @cached_property
    def expected_names(self) -> Dict[str, str]:
        """
        Set with all the names in the system in this plan
        """
        return {e.name: e.id for e in self.expected_entities}

    @cached_property
    def needs_apply(self) -> bool:
        return len(self.delete or self.create or self.modify) > 0


# TODO: Deal with errors and repeated code
async def plan_apply(plan: Plan, namespace: str,
                     entity_client: Optional[EntityClient] = None) -> Plan:
    errors = set()
    for e in plan.create:
        if not e.id:
            log.error('[appgate-operator/%s] Trying to create instance %s without id',
                      namespace, e)
        log.info('[appgate-operator/%s] + %s %s [%s]', namespace, type(e), e.name, e.id)
        if entity_client:
            if not await entity_client.post(cast(AppgateEntity, e)):
                errors.add(e.id)
    for e in plan.modify:
        if not e.id:
            log.error('[appgate-operator/%s] Trying to modify instance %s without id',
                      namespace, e)
            continue
        log.info('[appgate-operator/%s] * %s %s [%s]', namespace, type(e), e.name, e.id)
        if entity_client:
            if not await entity_client.put(cast(AppgateEntity, e)):
                errors.add(e.id)
    for e in plan.delete:
        if not e.id:
            log.error('[appgate-operator/%s] Trying to delete instance %s without id',
                      namespace, e)
            continue
        log.info('[appgate-operator/%s] - %s %s %s [%s]', namespace, type(e), e.name, e.id)
        if entity_client:
            if not await entity_client.delete(e.id):
                errors.add(e.id)

    for e in plan.share:
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
            policies=EntitiesSet(policies),
            entitlements=EntitiesSet(entitlements),
            conditions=EntitiesSet(conditions))


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


def compare_entities(current: Set[T],
                     expected: Set[T]) -> Plan[T]:
    current_names = {e.name for e in current}
    current_ids_by_name = {e.name: e.id for e in current if e.id}
    expected_names = {e.name for e in expected}
    shared_names = current_names.intersection(expected_names)
    to_delete = set(filter(lambda e: e.name not in expected_names and
                                     BUILTIN_TAG not in (e.tags or frozenset()),
                           current))
    to_create = set(filter(lambda e: e.name not in current_names and e.name not in shared_names,
                           expected))
    to_modify = set(map(lambda e: evolve(e, id=current_ids_by_name.get(e.name)),
                        filter(lambda e: e.name in shared_names and e not in current,
                               expected)))
    to_share = set(map(lambda e: evolve(e, id=current_ids_by_name.get(e.name)),
                       filter(lambda e: e.name in shared_names and e in current,
                              expected)))
    return Plan(delete=to_delete,
                create=to_create,
                modify=to_modify,
                share=to_share)


# TODO: These 2 functions do the same!
def resolve_entitlements(entitlements: Plan[Entitlement],
                         conditions: Plan[Condition]) -> Optional[Dict[str, Set[str]]]:
    missing_conditions: Dict[str, Set[str]] = {}
    for entitlement in entitlements.expected_entities:
        new_conditions = set()
        for condition in entitlement.conditions:
            condition_id = conditions.expected_names.get(condition)
            if not condition_id:
                if entitlement.name not in missing_conditions:
                    missing_conditions[entitlement.name] = set()
                missing_conditions[entitlement.name].add(condition)
            else:
                new_conditions.add(condition_id)
        evolve(entitlement, conditions=frozenset(new_conditions))

    if len(missing_conditions) > 0:
        return missing_conditions
    return None


def resolve_policies(policies: Plan[Policy],
                     entitlements: Plan[Entitlement]) -> Optional[Dict[str, Set[str]]]:
    missing_entitlements: Dict[str, Set[str]] = {}
    for policy in policies.expected_entities:
        new_entitlements = set()
        for entitlement in (policy.entitlements or []):
            entitlement_id = entitlements.expected_names.get(entitlement)
            if not entitlement_id:
                if policy.name not in missing_entitlements:
                    missing_entitlements[policy.name] = set()
                missing_entitlements[policy.name].add(entitlement)
            else:
                new_entitlements.add(entitlement_id)
        evolve(policy, entitlements=frozenset(new_entitlements))

    if len(missing_entitlements) > 0:
        return missing_entitlements
    return None


def create_appgate_plan(current_state: AppgateState,
                        expected_state: AppgateState) -> AppgatePlan:
    """
    Creates a new AppgatePlan to apply
    """
    conditions_plan = cast(Plan[Condition],
                           compare_entities(current_state.conditions.entities,
                                            expected_state.conditions.entities))
    entitlements_plan = cast(Plan[Entitlement],
                             compare_entities(current_state.entitlements.entities,
                                              expected_state.entitlements.entities))
    entitlement_conflicts = resolve_entitlements(entitlements_plan, conditions_plan)
    policies_plan = cast(Plan[Policy],
                         compare_entities(current_state.policies.entities,
                                          expected_state.policies.entities))
    policy_conflicts = resolve_policies(policies_plan, entitlements_plan)

    return AppgatePlan(policies=policies_plan,
                       entitlements=entitlements_plan,
                       conditions=conditions_plan,
                       entitlement_conflicts=entitlement_conflicts,
                       policy_conflicts=policy_conflicts)

