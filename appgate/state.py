from functools import cached_property
from typing import Set, TypeVar, Generic, Dict, List, Optional

from attr import attrib, attrs, evolve

from appgate.types import Policy, Condition, Entitlement, Entity_T


@attrs()
class AppgateState:
    controller: str = attrib()
    token: str = attrib()
    user: str = attrib()
    policies: Set[Policy] = attrib()
    conditions: Set[Condition] = attrib()
    entitlements: Set[Entitlement] = attrib()


T = TypeVar('T', bound=Entity_T)


@attrs
class Plan(Generic[T]):
    delete: Set[T] = attrib(factory=set)
    create: Set[T] = attrib(factory=set)
    modify: Set[T] = attrib(factory=set)

    @cached_property
    def expected_names(self) -> Set[str]:
        """
        Set with all the names in the system in this plan
        """
        names = {c.name for c in self.modify}
        names.update({c.name for c in self.create})
        return names

    @cached_property
    def expected_ids(self) -> Set[str]:
        """
        Set with all the known id names in the system in this plan
        """
        return set(filter(None, map(lambda c: c.id, self.modify)))


# Policies have entitlements that have conditions, so conditions always first.
@attrs
class AppgatePlan:
    policies: Plan[Policy] = attrib()
    entitlements: Plan[Entitlement] = attrib()
    conditions: Plan[Condition] = attrib()
    entitlement_errors: Optional[Dict[str, Set[str]]] = attrib(default=None)
    policy_errors: Optional[Dict[str, Set[str]]] = attrib(default=None)

    @cached_property
    def expected_condition_names(self) -> Set[str]:
        """
        Set with all the condition names in the system after the plan is applied
        """
        return self.conditions.expected_names

    @cached_property
    def expected_entitlement_names(self) -> Set[str]:
        """
        Set with all the condition names in the system after the plan is applied
        """
        return self.entitlements.expected_names


def compare_entities(current: Set[T],
                     expected: Set[T]) -> Plan[T]:
    current_names = {e.name for e in current}
    current_ids_by_name = {e.name: e.id for e in current if e.id}
    expected_names = {e.name for e in expected}
    shared_names = current_names.intersection(expected_names)
    to_delete = set(filter(lambda e: e.name not in expected_names, current))
    to_create = set(filter(lambda e: e.name not in current_names and e.name not in shared_names,
                           expected))
    to_modify = set(map(lambda e: evolve(e, id=current_ids_by_name.get(e.name)),
                        filter(lambda e: e.name in shared_names and e not in current,
                               expected)))
    return Plan(delete=to_delete,
                create=to_create,
                modify=to_modify)


# TODO: These 2 functions do the same!
def check_entitlements(entitlements: Plan[Entitlement],
                       conditions: Plan[Condition]) -> Optional[Dict[str, Set[str]]]:
    missing_conditions: Dict[str, Set[str]] = {}
    for entitlement in entitlements.create.union(entitlements.modify):
        for condition in entitlement.conditions:
            if condition not in conditions.expected_names:
                if entitlement.name not in missing_conditions:
                    missing_conditions[entitlement.name] = set()
                missing_conditions[entitlement.name].add(condition)

    if len(missing_conditions) > 0:
        return missing_conditions
    return None


def check_policies(policies: Plan[Policy],
                   entitlements: Plan[Entitlement]) -> Optional[Dict[str, Set[str]]]:
    missing_entitlements: Dict[str, Set[str]] = {}
    for policy in policies.create.union(policies.modify):
        for entitlement in (policy.entitlements or []):
            if entitlement not in entitlements.expected_names:
                if policy.name not in missing_entitlements:
                    missing_entitlements[policy.name] = set()
                missing_entitlements[policy.name].add(entitlement)

    if len(missing_entitlements) > 0:
        return missing_entitlements

    return None


def create_appgate_plan(current_state: AppgateState,
                        expected_state: AppgateState) -> AppgatePlan:
    """
    Creates a new AppgatePlan to apply
    """
    conditions_plan = compare_entities(current_state.conditions,
                                       expected_state.conditions)
    entitlements_plan = compare_entities(current_state.entitlements,
                                         expected_state.entitlements)
    entitlement_errors = check_entitlements(entitlements_plan, conditions_plan)
    policies_plan = compare_entities(current_state.policies, expected_state.policies)
    policy_errors = check_policies(policies_plan, entitlements_plan)

    return AppgatePlan(policies=policies_plan,
                       entitlements=entitlements_plan,
                       conditions=conditions_plan,
                       entitlement_errors=entitlement_errors,
                       policy_errors=policy_errors)
