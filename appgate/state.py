from typing import Set, TypeVar, Generic, Callable, Optional

from attr import attrib, attrs, evolve

from appgate.types import Policy, Condition, Entitlement


@attrs()
class AppgateState:
    controller: str = attrib()
    token: str = attrib()
    user: str = attrib()
    policies: Set[Policy] = attrib()
    conditions: Set[Condition] = attrib()
    entitlements: Set[Entitlement] = attrib()


T = TypeVar('T')


@attrs
class Plan(Generic[T]):
    delete: Set[T] = attrib(factory=set)
    create: Set[T] = attrib(factory=set)
    modify: Set[T] = attrib(factory=set)


# Policies have entitlements that have conditions, so conditions always first.
@attrs
class AppgatePlan:
    policies: Plan[Policy] = attrib()
    entitlements: Plan[Entitlement] = attrib()
    conditions: Plan[Condition] = attrib()


def compare_entities(current: Set[T],
                     expected: Set[T],
                     get_name: Callable[[T], str],
                     get_id: Callable[[T], Optional[str]]) -> Plan[T]:
    current_names = {get_name(e) for e in current}
    current_ids_by_name = {get_name(e): get_id(e) for e in current if get_id(e)}
    expected_names = {get_name(e) for e in expected}
    shared_names = current_names.intersection(expected_names)
    to_delete = set(filter(lambda e: get_name(e) not in expected_names, current))
    to_create = set(filter(lambda e: get_name(e) not in current_names and get_name(e) not in shared_names,
                           expected))
    to_modify = set(map(lambda e: evolve(e, id=current_ids_by_name.get(get_name(e))),
                        filter(lambda e: get_name(e) in shared_names and e not in current,
                               expected)))
    return Plan(delete=to_delete,
                create=to_create,
                modify=to_modify)


def normalize_entitlements(entitlements: Plan[Entitlement],
                           conditions: Plan[Condition]) -> Plan[Entitlement]:
    pass


def normalize_policies(entitlements: Plan[Policy],
                       conditions: Plan[Entitlement]) -> Plan[Policy]:
    pass


def create_appgate_plan(current_state: AppgateState,
                        expected_state: AppgateState) -> AppgatePlan:
    """
    Creates a new AppgatePlan to apply
    """
    get_name = lambda e: e.name
    get_id = lambda e: e.id
    conditions_plan = compare_entities(current_state.conditions,
                                       expected_state.conditions,
                                       get_name=get_name,
                                       get_id=get_id)
    first_entitlements_plan = compare_entities(current_state.entitlements,
                                               expected_state.entitlements,
                                               get_name=get_name,
                                               get_id=get_id)
    entitlements_plan = normalize_entitlements(first_entitlements_plan,
                                               conditions_plan)
    first_policies_plan = compare_entities(current_state.policies, expected_state.policies,
                                           get_name=get_name, get_id=get_id)
    policies_plan = normalize_policies(first_policies_plan, entitlements_plan)

    return AppgatePlan(policies=policies_plan,
                       entitlements=entitlements_plan,
                       conditions=conditions_plan)
