from typing import Set, TypeVar, Generic, Callable, Optional, Dict, List, Any

from attr import attrib, attrs, evolve

from appgate.types import Policy, Condition, Entitlement, Entity


@attrs()
class AppgateState:
    controller: str = attrib()
    token: str = attrib()
    user: str = attrib()
    policies: Set[Policy] = attrib()
    conditions: Set[Condition] = attrib()
    entitlements: Set[Entitlement] = attrib()


T = TypeVar('T', bound=Entity)


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


def normalize_entitlements(entitlements: Plan[Entitlement],
                           conditions: Plan[Condition]) -> Plan[Entitlement]:
    pass



def normalize_policies(entitlements: Plan[Policy],
                       conditions: Plan[Entitlement]) -> Plan[Policy]:
    pass


def entity_dependencies_dag(entity_dependencies: Dict[str, List[str]]):
    reversed_deps: Dict[str, Set[str]] = {}
    candidates: List[str] = []
    rest_nodes: Dict[str, int] = {}
    dag:List[Any] = []
    visited = 0
    # Used to show a better output on errors
    added_nodes = set()
    total_nodes = set()
    # Initialize a reversed index to find easily where an edge is pointing to
    # also generate the candidates and rest_nodes lists
    for p, ds in entity_dependencies.items():
        total_nodes.add(p)
        if len(ds) == 0:
            candidates.insert(0, p)
        else:
            rest_nodes[p] = len(ds)
        for d in ds:
            if d not in reversed_deps:
                reversed_deps[d] = set()
            reversed_deps[d].add(p)
    candidates = sorted(candidates)
    group = -1
    while candidates:
        node = candidates.pop(0)
        added_nodes.add(node)
        # This candidate depends on the previous group
        if group >= 0 and dag[group].intersection(set(entity_dependencies[node])):
            dag.append({node})
            group += 1
        # This candidate does not depend on the previous one
        elif group >= 0:
            dag[group].add(node)
        else:
            dag.append({node})
            group += 1
        visited += 1
        for d in reversed_deps.get(node, []):
            rest_nodes[d] = rest_nodes[d] - 1
            if rest_nodes[d] == 0:
                candidates.append(d)
    if visited < len(entity_dependencies):
        unfit_nodes = total_nodes.difference(added_nodes)
        raise Exception(f'Unable to fullfit dependencies: {unfit_nodes}')
    return dag


def create_appgate_plan(current_state: AppgateState,
                        expected_state: AppgateState) -> AppgatePlan:
    """
    Creates a new AppgatePlan to apply
    """
    conditions_plan = compare_entities(current_state.conditions,
                                       expected_state.conditions)
    first_entitlements_plan = compare_entities(current_state.entitlements,
                                               expected_state.entitlements)
    entitlements_plan = normalize_entitlements(first_entitlements_plan,
                                               conditions_plan)
    first_policies_plan = compare_entities(current_state.policies, expected_state.policies)
    policies_plan = normalize_policies(first_policies_plan, entitlements_plan)

    return AppgatePlan(policies=policies_plan,
                       entitlements=entitlements_plan,
                       conditions=conditions_plan)
