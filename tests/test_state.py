from appgate.attrs import K8S_LOADER, APPGATE_LOADER
from appgate.state import compare_entities, EntitiesSet, resolve_entities, AppgateState, resolve_appgate_state, \
    compute_diff
from appgate.types import EntityWrapper
from appgate.openapi.utils import BUILTIN_TAGS
from tests.test_entities import BASE64_FILE_W0, SHA256_FILE
from tests.utils import entitlement, condition, policy, Policy, load_test_open_api_spec, PEM_TEST, \
    join_string, SUBJECT, ISSUER, CERTIFICATE_FIELD, PUBKEY_FIELD, _k8s_get_secret


def test_compare_policies_0():
    current_policies = EntitiesSet({
        EntityWrapper(Policy(id='id1',
                             name='policy1',
                             expression='expression-1')),
        EntityWrapper(Policy(id='id2',
                             name='policy2',
                             expression='expression-2')),
        EntityWrapper(Policy(id='id3',
                             name='policy3',
                             expression='expression-3'))
    })
    expected_policies = EntitiesSet(set())
    plan = compare_entities(current_policies, expected_policies, BUILTIN_TAGS, frozenset(), frozenset())

    assert plan.delete.entities == {
        EntityWrapper(Policy(id='id1',
                             name='policy1',
                             expression='expression-1')),
        EntityWrapper(Policy(id='id2',
                             name='policy2',
                             expression='expression-2')),
        EntityWrapper(Policy(id='id3',
                             name='policy3',
                             expression='expression-3'))
    }
    # test that the ids are propagated when modifying
    delete_ids = [p.id for p in plan.delete.entities]
    delete_ids.sort()
    assert delete_ids == ['id1', 'id2', 'id3']
    assert plan.modify.entities == set()
    assert plan.create.entities == set()


def test_compare_policies_1():
    current_policies = EntitiesSet(set())
    expected_policies = EntitiesSet({
        EntityWrapper(Policy(name='policy1',
                             expression='expression-1')),
        EntityWrapper(Policy(name='policy2',
                             expression='expression-2')),
        EntityWrapper(Policy(name='policy3',
                             expression='expression-3'))
    })
    plan = compare_entities(current_policies, expected_policies, BUILTIN_TAGS, frozenset(), None)
    assert plan.create.entities == {
        EntityWrapper(Policy(name='policy1',
                             expression='expression-1')),
        EntityWrapper(Policy(name='policy2',
                             expression='expression-2')),
        EntityWrapper(Policy(name='policy3',
                             expression='expression-3'))
    }
    assert plan.modify.entities == set()
    assert plan.delete.entities == set()


def test_compare_policies_2():
    current_policies = EntitiesSet({
        EntityWrapper(Policy(id='id1',
                             name='policy1',
                             expression='expression-1')),
        EntityWrapper(Policy(id='id2',
                             name='policy2',
                             expression='expression-2')),
        EntityWrapper(Policy(id='id3',
                             name='policy3',
                             expression='expression-3'))
    })
    expected_policies = EntitiesSet({
        EntityWrapper(Policy(id='id1',
                             name='policy1',
                             expression='expression-1')),
        EntityWrapper(Policy(id='id2',
                             name='policy2',
                             expression='expression-2')),
        EntityWrapper(Policy(id='id3',
                             name='policy3',
                             expression='expression-3'))
    })
    plan = compare_entities(current_policies, expected_policies, BUILTIN_TAGS, frozenset(), None)
    assert plan.modify.entities == set()
    assert plan.delete.entities == set()
    assert plan.create.entities == set()
    assert plan.share.entities == {
        EntityWrapper(Policy(id='id1',
                             name='policy1',
                             expression='expression-1')),
        EntityWrapper(Policy(id='id2',
                             name='policy2',
                             expression='expression-2')),
        EntityWrapper(Policy(id='id3',
                             name='policy3',
                             expression='expression-3'))
    }
    share_ids = [p.id for p in plan.share.entities]
    assert len(list(filter(None, share_ids))) == 3
    share_ids.sort()
    assert share_ids == ['id1', 'id2', 'id3']


def test_compare_policies_3():
    current_policies = EntitiesSet({
        EntityWrapper(Policy(id='id1',
                             name='policy3',
                             expression='expression-1')),
        EntityWrapper(Policy(id='id2',
                             name='policy2',
                             expression='expression-2')),
        EntityWrapper(Policy(id='id3',
                             name='policy4',
                             expression='expression-3'))
    })
    expected_policies = EntitiesSet({
        EntityWrapper(Policy(name='policy1',
                             expression='expression-1')),
        EntityWrapper(Policy(id='id2',
                             name='policy2',
                             expression='expression-2')),
        EntityWrapper(Policy(id='id3',
                             name='policy4',
                             expression='expression-3'))
    })
    plan = compare_entities(current_policies, expected_policies, BUILTIN_TAGS, frozenset(), None)
    assert plan.delete.entities == {
        EntityWrapper(Policy(id='id1', name='policy3', expression='expression-1'))
    }
    # test that the ids are propagated when modifying
    assert [p.id for p in plan.delete.entities] == ['id1']
    assert plan.create.entities == {
        EntityWrapper(Policy(name='policy1', expression='expression-1'))
    }
    assert plan.modify.entities == set()


def test_compare_policies_4():
    current_policies = EntitiesSet({
        EntityWrapper(Policy(id='id0',
                             name='policy0',
                             expression='expression-0')),
        EntityWrapper(Policy(id='id1',
                             name='policy1',
                             expression='expression-1')),
        EntityWrapper(Policy(id='id2',
                             name='policy2',
                             expression='expression-2')),
        EntityWrapper(Policy(id='id3',
                             name='policy3',
                             expression='expression-3'))
    })
    expected_policies = EntitiesSet({
        EntityWrapper(Policy(id='id0',
                             name='policy0',
                             expression='expression-0')),
        EntityWrapper(Policy(id='id1',
                             name='policy1',
                             expression='expression-2')),
        EntityWrapper(Policy(id='id2',
                             name='policy2',
                             expression='expression-3')),
        EntityWrapper(Policy(name='policy4',
                             expression='expression-4'))
    })
    plan = compare_entities(current_policies, expected_policies, BUILTIN_TAGS, frozenset(), None)
    assert plan.delete.entities == {
        EntityWrapper(Policy(id='id3', name='policy3', expression='expression-3'))
    }
    # test that the ids are propagated when modifying
    assert [p.id for p in plan.delete.entities] == ['id3']
    assert plan.create.entities == {
        EntityWrapper(Policy(name='policy4', expression='expression-4'))
    }
    assert plan.modify.entities == {
        EntityWrapper(Policy(id='id1',
                             name='policy1',
                             expression='expression-2')),
        EntityWrapper(Policy(id='id2',
                             name='policy2',
                             expression='expression-3'))
    }


def test_normalize_entitlements_0():
    entitlements = EntitiesSet()
    conditions = EntitiesSet()
    entitlements_set, conflicts = resolve_entities(entitlements, [(conditions, 'conditions')])
    assert entitlements_set.entities == set()
    assert conflicts is None


def test_normalize_entitlements_1():
    entitlements = EntitiesSet({
        EntityWrapper(entitlement(name='entitlement-1', conditions=[
            'condition1',
            'condition2',
            'condition3'
        ])),
        EntityWrapper(entitlement(name='entitlement-2', conditions=[
            'condition1',
            'condition2',
            'condition3',
        ])),
    })
    conditions = EntitiesSet()
    entitlements_set, conflicts = resolve_entities(entitlements, [(conditions, 'conditions')])
    assert entitlements_set.entities == entitlements.entities
    assert conflicts == {
        'entitlement-1': {
            'conditions': frozenset({'condition1', 'condition2', 'condition3'})
        },
        'entitlement-2': {
            'conditions': frozenset({'condition1', 'condition2', 'condition3'})
        },
    }


def test_normalize_entitlements_2():
    entitlements = EntitiesSet({
        EntityWrapper(entitlement(name='entitlement-1', conditions=[
            'condition1',
            'condition2',
            'condition3'
        ])),
        EntityWrapper(entitlement(name='entitlement-2', conditions=[
            'condition1',
            'condition4',
            'condition5',
        ])),
    })
    conditions = EntitiesSet({
        EntityWrapper(condition(id='c1', name='condition1')),
        EntityWrapper(condition(id='c2', name='condition2')),
        EntityWrapper(condition(id='c3', name='condition3')),
        EntityWrapper(condition(id='c4', name='condition4')),
        EntityWrapper(condition(id='c5', name='condition5')),
    })
    entitlements_set, conflicts = resolve_entities(entitlements, [(conditions, 'conditions')])
    assert entitlements_set.entities == {
        EntityWrapper(entitlement(name='entitlement-1', conditions=[
            'c1',
            'c2',
            'c3'
        ])),
        EntityWrapper(entitlement(name='entitlement-2', conditions=[
            'c1',
            'c4',
            'c5',
        ])),
    }
    assert conflicts is None


def test_normalize_entitlements_3():
    entitlements = EntitiesSet({
        EntityWrapper(entitlement(name='entitlement-1', conditions=[
            'condition1',
            'condition2',
            'condition3'
        ])),
        EntityWrapper(entitlement(name='entitlement-2', conditions=[
            'condition1',
            'condition4',
            'condition5',
        ])),
    })
    conditions = EntitiesSet({
        EntityWrapper(condition(id='id1', name='condition1')),
        EntityWrapper(condition(id='id2', name='condition2')),
        EntityWrapper(condition(id='id3', name='condition3')),
        EntityWrapper(condition(name='condition4')),
        EntityWrapper(condition(name='condition5')),
    })
    entitlements_set, conflicts = resolve_entities(entitlements, [(conditions, 'conditions')])
    assert conflicts == {
        'entitlement-2': {
            'conditions': frozenset({'condition4', 'condition5'}),
        }
    }


def test_normalize_policies_0():
    policies = EntitiesSet()
    entitlements = EntitiesSet()
    policies_set, conflicts = resolve_entities(policies, [(entitlements, 'entitlements')])
    assert policies_set.entities == set()
    assert conflicts is None


def test_normalize_policies_1():
    policies = EntitiesSet({
        EntityWrapper(policy(name='policy-1', entitlements=[
            'entitlement1',
            'entitlement2',
            'entitlement3'
        ])),
        EntityWrapper(policy(name='policy-2', entitlements=[
            'entitlement1',
            'entitlement2',
            'entitlement3',
        ])),
    })
    entitlements = EntitiesSet()
    policies_set, conflicts = resolve_entities(policies, [(entitlements, 'entitlements')])
    assert conflicts == {
        'policy-1': {
            'entitlements': frozenset({'entitlement1', 'entitlement2', 'entitlement3'})
        },
        'policy-2': {
            'entitlements': frozenset({'entitlement1', 'entitlement2', 'entitlement3'})
        }
    }


def test_normalize_policies_2():
    policies = EntitiesSet({
        EntityWrapper(policy(name='policy-1', entitlements=[
            'entitlement1',
            'entitlement2',
            'entitlement3'
        ])),
        EntityWrapper(policy(name='policy-2', entitlements=[
            'entitlement1',
            'entitlement4',
            'entitlement5',
        ])),
    })
    entitlements = EntitiesSet({
            EntityWrapper(entitlement(id='e1', name='entitlement1')),
            EntityWrapper(entitlement(id='e2', name='entitlement2')),
            EntityWrapper(entitlement(id='e3', name='entitlement3')),
            EntityWrapper(entitlement(id='e4', name='entitlement4')),
            EntityWrapper(entitlement(id='e5', name='entitlement5')),
        })
    policies_set, conflicts = resolve_entities(policies, [(entitlements, 'entitlements')])
    assert conflicts is None
    assert policies_set.entities == {
        EntityWrapper(policy(name='policy-1', entitlements=[
            'e1',
            'e2',
            'e3'
        ])),
        EntityWrapper(policy(name='policy-2', entitlements=[
            'e1',
            'e4',
            'e5',
        ])),
    }


def test_normalize_policies_3():
    policies = EntitiesSet({
        EntityWrapper(policy(name='policy-1', entitlements=[
            'entitlement1',
            'entitlement2',
            'entitlement3'
        ])),
        EntityWrapper(policy(name='policy-2', entitlements=[
            'entitlement1',
            'entitlement4',
            'entitlement5',
        ])),
    })
    entitlements = EntitiesSet({
        EntityWrapper(entitlement(id='id1', name='entitlement1')),
        EntityWrapper(entitlement(id='id2', name='entitlement2')),
        EntityWrapper(entitlement(id='id3', name='entitlement3')),
        EntityWrapper(entitlement(name='entitlement5'))
    })
    policies_set, conflicts = resolve_entities(policies, [(entitlements, 'entitlements')])
    assert conflicts == {
        'policy-2': {
            'entitlements': frozenset({'entitlement4', 'entitlement5'})
        }
    }


def test_dependencies_1():
    """
    One dependency
    EntityDep3 has an array field (deps1) with deps from EntityDep1
    """
    api = load_test_open_api_spec()
    EntityDep1 = api.entities['EntityDep1'].cls
    EntityDep3 = api.entities['EntityDep3'].cls
    deps1 = EntitiesSet({
        EntityWrapper(EntityDep1(id='d11', name='dep11')),
        EntityWrapper(EntityDep1(id='d12', name='dep12')),
        EntityWrapper(EntityDep1(id='d13', name='dep13')),
    })
    deps3 = EntitiesSet({
        EntityWrapper(EntityDep3(id='d31', name='dep31', deps1=frozenset({'dep11', 'dep12'})))
    })

    # No conflits
    deps3_resolved, conflicts = resolve_entities(deps3, [(deps1, 'deps1')])
    assert conflicts is None
    assert deps3_resolved.entities == {
        EntityWrapper(EntityDep3(id='d31', name='dep31', deps1=frozenset({'d11', 'd12'})))
    }

    # Conflicts
    deps3 = EntitiesSet({
        EntityWrapper(EntityDep3(id='d31', name='dep31', deps1=frozenset({'dep14', 'dep12'})))
    })
    deps3_resolved, conflicts = resolve_entities(deps3, [(deps1, 'deps1')])
    assert conflicts == {
        'dep31': {
            'deps1': frozenset({'dep14'})
        }
    }


def test_dependencies_2():
    """
    Two dependencies
    EntityDep4 has an array field (deps1) with deps from EntityDep1
    EntityDep4 has a string field (dep2) with deps from EntityDep2
    """
    api = load_test_open_api_spec()
    EntityDep1 = api.entities['EntityDep1'].cls
    EntityDep2 = api.entities['EntityDep2'].cls
    EntityDep4 = api.entities['EntityDep4'].cls
    deps1 = EntitiesSet({
        EntityWrapper(EntityDep1(id='d11', name='dep11')),
        EntityWrapper(EntityDep1(id='d12', name='dep12')),
        EntityWrapper(EntityDep1(id='d13', name='dep13')),
    })
    deps2 = EntitiesSet({
        EntityWrapper(EntityDep2(id='d21', name='dep21')),
        EntityWrapper(EntityDep2(id='d22', name='dep22')),
        EntityWrapper(EntityDep2(id='d23', name='dep23')),
    })

    # no conflicts
    deps4 = EntitiesSet({
        EntityWrapper(EntityDep4(id='d31', name='dep31', deps1=frozenset({'dep11', 'dep12'}),
                                 dep2='dep23'))
    })
    deps3_resolved, conflicts = resolve_entities(deps4, [(deps1, 'deps1'),
                                                         (deps2, 'dep2')])
    assert conflicts is None
    assert deps3_resolved.entities == {
        EntityWrapper(EntityDep4(id='d31', name='dep31', deps1=frozenset({'d11', 'd12'}),
                                 dep2='d23'))
    }

    # conflicts in field deps1
    deps4 = EntitiesSet({
        EntityWrapper(EntityDep4(id='d31', name='dep31', deps1=frozenset({'dep14', 'dep12'}),
                                 dep2='dep33'))
    })
    deps3_resolved, conflicts = resolve_entities(deps4, [(deps1, 'deps1'),
                                                         (deps2, 'dep2')])
    assert conflicts == {
        'dep31': {
            'deps1': frozenset({'dep14'}),
            'dep2': frozenset({'dep33'})
        }
    }


def test_dependencies_3():
    """
    several dependencies (even nested)
    See EntityDep5 for details
    """
    api = load_test_open_api_spec()
    EntityDep1 = api.entities['EntityDep1'].cls
    EntityDep5 = api.entities['EntityDep5'].cls
    EntityDep5_Obj1 = api.entities['EntityDep5_Obj1'].cls
    EntityDep5_Obj1_Obj2 = api.entities['EntityDep5_Obj1_Obj2'].cls
    deps1 = EntitiesSet({
        EntityWrapper(EntityDep1(id='d11', name='dep11')),
        EntityWrapper(EntityDep1(id='d12', name='dep12')),
        EntityWrapper(EntityDep1(id='d13', name='dep13')),
    })
    data = {
        'id': 'd51',
        'name': 'dep51',
        'obj1': {
            'obj2': {
                'dep1': 'dep11'
            }
        }
    }
    deps5 = EntitiesSet({
        EntityWrapper(K8S_LOADER.load(data, None, EntityDep5))
    })
    deps5_resolved, conflicts = resolve_entities(deps5, [(deps1, 'obj1.obj2.dep1')])
    assert conflicts is None
    assert deps5_resolved.entities == {
        EntityWrapper(EntityDep5(id='d51', name='dep51',
                                 obj1=EntityDep5_Obj1(obj2=EntityDep5_Obj1_Obj2(dep1='d11'))))
    }


def test_dependencies_4():
    """
    several dependencies (even nested)
    See EntityDep5 for details
    """
    test_api_spec = load_test_open_api_spec()
    EntityDep1 = test_api_spec.entities['EntityDep1'].cls
    EntityDep2 = test_api_spec.entities['EntityDep2'].cls
    EntityDep3 = test_api_spec.entities['EntityDep3'].cls
    EntityDep4 = test_api_spec.entities['EntityDep4'].cls
    EntityDep6 = test_api_spec.entities['EntityDep6'].cls
    EntityDep6_Obj1 = test_api_spec.entities['EntityDep6_Obj1'].cls
    EntityDep6_Obj1_Obj2 = test_api_spec.entities['EntityDep6_Obj1_Obj2'].cls
    EntityDep6_Obj1_Obj2_Deps1 = test_api_spec.entities['EntityDep6_Obj1_Obj2_Deps1'].cls

    deps1 = EntitiesSet({
        EntityWrapper(EntityDep1(id='d11', name='dep11')),
        EntityWrapper(EntityDep1(id='d12', name='dep12')),
        EntityWrapper(EntityDep1(id='d13', name='dep13')),
    })
    deps2 = EntitiesSet({
        EntityWrapper(EntityDep2(id='d21', name='dep21')),
        EntityWrapper(EntityDep2(id='d22', name='dep22')),
        EntityWrapper(EntityDep2(id='d23', name='dep23')),
    })
    deps3 = EntitiesSet({
        EntityWrapper(EntityDep3(id='d31', name='dep31', deps1=frozenset({'dep11', 'dep12'}))),
        EntityWrapper(EntityDep3(id='d32', name='dep32', deps1=frozenset({'dep11', 'dep13'}))),
        EntityWrapper(EntityDep3(id='d33', name='dep33', deps1=frozenset({'dep12', 'dep13'}))),
    })
    deps4 = EntitiesSet({
        EntityWrapper(EntityDep4(id='d41', name='dep41', deps1=frozenset({'dep11', 'dep12'}),
                                 dep2='dep21')),
        EntityWrapper(EntityDep4(id='d42', name='dep42', deps1=frozenset({'dep11', 'dep13'}),
                                 dep2='dep22')),
        EntityWrapper(EntityDep4(id='d43', name='dep43', deps1=frozenset({'dep12', 'dep13'}),
                                 dep2='dep23')),
    })

    # no conflicts
    data = {
        'id': 'd61',
        'name': 'dep61',
        'deps4': ['dep41', 'dep42'],
        'obj1': {
            'dep3': 'dep31',
            'obj2': {
                'deps1': [
                    {'dep1': 'dep11'},
                    {'dep1': 'dep12'},
                    {'dep1': 'dep13'},
                ],
                'deps2': ['dep21', 'dep22']
            }
        }
    }
    deps6 = EntitiesSet({
        EntityWrapper(K8S_LOADER.load(data, None, EntityDep6))
    })
    appgate_state = AppgateState(entities_set={
        'EntityDep1': deps1,
        'EntityDep2': deps2,
        'EntityDep3': deps3,
        'EntityDep4': deps4,
        'EntityDep5': EntitiesSet(),
        'EntityDep6': deps6,
    })
    conflicts = resolve_appgate_state(appgate_state, test_api_spec)
    assert conflicts == {}
    assert appgate_state.entities_set['EntityDep1'].entities == {
        EntityWrapper(EntityDep1(id='d11', name='dep11')),
        EntityWrapper(EntityDep1(id='d12', name='dep12')),
        EntityWrapper(EntityDep1(id='d13', name='dep13')),
    }
    assert appgate_state.entities_set['EntityDep2'].entities == {
        EntityWrapper(EntityDep2(id='d21', name='dep21')),
        EntityWrapper(EntityDep2(id='d22', name='dep22')),
        EntityWrapper(EntityDep2(id='d23', name='dep23')),
    }
    assert appgate_state.entities_set['EntityDep3'].entities == {
        EntityWrapper(EntityDep3(id='d31', name='dep31', deps1=frozenset({'d11', 'd12'}))),
        EntityWrapper(EntityDep3(id='d32', name='dep32', deps1=frozenset({'d11', 'd13'}))),
        EntityWrapper(EntityDep3(id='d33', name='dep33', deps1=frozenset({'d12', 'd13'}))),
    }
    assert appgate_state.entities_set['EntityDep4'].entities == {
        EntityWrapper(EntityDep4(id='d41', name='dep41', deps1=frozenset({'d11', 'd12'}),
                   dep2='d21')),
        EntityWrapper(EntityDep4(id='d42', name='dep42', deps1=frozenset({'d11', 'd13'}),
                                 dep2='d22')),
        EntityWrapper(EntityDep4(id='d43', name='dep43', deps1=frozenset({'d12', 'd13'}),
                                 dep2='d23')),
    }
    assert appgate_state.entities_set['EntityDep6'].entities == {
        EntityWrapper(EntityDep6(name='dep61',
                                 deps4=frozenset({'d42', 'd41'}),
                                 obj1=EntityDep6_Obj1(dep3='d31',
                                                      obj2=EntityDep6_Obj1_Obj2(
                                                          deps1=frozenset({
                                                              EntityDep6_Obj1_Obj2_Deps1(dep1='dep11'),
                                                              EntityDep6_Obj1_Obj2_Deps1(dep1='dep12'),
                                                              EntityDep6_Obj1_Obj2_Deps1(dep1='dep13'),
                                                          }),
                                                          deps2=frozenset({'d21', 'd22'})))))
    }

    # Test empty list in dependencies
    data = {
        'id': 'd61',
        'name': 'dep61',
        'obj1': {
            'dep3': 'dep31',
            'obj2': {
                'deps1': [],
                'deps2': ['dep21', 'dep22']
            }
        }
    }
    deps6 = EntitiesSet({
        EntityWrapper(K8S_LOADER.load(data, None, EntityDep6))
    })
    appgate_state = AppgateState(entities_set={
        'EntityDep1': deps1,
        'EntityDep2': deps2,
        'EntityDep3': deps3,
        'EntityDep4': deps4,
        'EntityDep5': EntitiesSet(),
        'EntityDep6': deps6,
    })
    conflicts = resolve_appgate_state(appgate_state, test_api_spec)
    assert conflicts == {}
    assert appgate_state.entities_set['EntityDep6'].entities == {
        EntityWrapper(EntityDep6(name='dep61',
                                 deps4=frozenset(),
                                 obj1=EntityDep6_Obj1(dep3='d31',
                                                      obj2=EntityDep6_Obj1_Obj2(
                                                          deps1=frozenset(),
                                                          deps2=frozenset({'d21', 'd22'})))))
    }


def test_compare_plan_entity_bytes():
    EntityTest3Appgate = load_test_open_api_spec(secrets_key=None,
                                                reload=True).entities['EntityTest3Appgate'].cls
    # fieldOne is writeOnly :: byte
    # fieldTwo is readOnly :: checksum of fieldOne
    # fieldThree is readOnly :: size of fieldOne
    e_data = {
        'id': '6a01c585-c192-475b-b86f-0e632ada6769',  # Current data always has ids
        'name': 'entity1',
        'fieldOne': None,
        'fieldTwo': SHA256_FILE,
        'fieldThree': 1563,
    }
    entities_current = EntitiesSet({
        EntityWrapper(APPGATE_LOADER.load(e_data, None, EntityTest3Appgate))
    })
    e_data = {
        'name': 'entity1',
        'fieldOne': BASE64_FILE_W0,
        'fieldTwo': None,
        'fieldThree': None,
    }
    e_metadata = {
        'uuid': '6a01c585-c192-475b-b86f-0e632ada6769'
    }
    entities_expected = EntitiesSet({
        EntityWrapper(K8S_LOADER.load(e_data, e_metadata, EntityTest3Appgate))
    })
    plan = compare_entities(entities_current, entities_expected, BUILTIN_TAGS, frozenset(), None)
    assert plan.modify.entities == frozenset()
    assert plan.modifications_diff == {}

    assert compute_diff(list(entities_current.entities)[0],
                        list(entities_expected.entities)[0]) == []

    # Let's change the bytes
    e_data = {
        'name': 'entity1',
        'fieldOne': 'Some other content',
        'fieldTwo': None,
        'fieldThree': None,
    }
    new_e = K8S_LOADER.load(e_data, e_metadata, EntityTest3Appgate)

    entities_expected = EntitiesSet({EntityWrapper(new_e)})
    plan = compare_entities(entities_current, entities_expected, BUILTIN_TAGS, frozenset(), None)
    assert plan.modify.entities == frozenset({EntityWrapper(new_e)})
    assert plan.modifications_diff == {
        'entity1': ['--- \n', '+++ \n', '@@ -2,4 +2,4 @@\n',
                    '     "name": "entity1",\n',
                    '-    "fieldTwo": "0d373afdccb82399b29ba0d6d1a282b4d10d7e70d948257e75c05999f0be9f3e",\n',
                    '-    "fieldThree": 1563\n',
                    '+    "fieldTwo": "c8f4fc85b689f8f3a70e7024e2bb8c7c8f4f7f9ffd2a1a8d01fc8fba74d1af34",\n',
                    '+    "fieldThree": 12\n', ' }']
    }


PEM2 = '''
-----BEGIN CERTIFICATE-----
MIICGjCCAYOgAwIBAgIBADANBgkqhkiG9w0BAQUFADCBmzELMAkGA1UEBhMCSlAx
DjAMBgNVBAgTBVRva3lvMRAwDgYDVQQHEwdDaHVvLWt1MREwDwYDVQQKEwhGcmFu
azRERDEYMBYGA1UECxMPV2ViQ2VydCBTdXBwb3J0MRgwFgYDVQQDEw9GcmFuazRE
RCBXZWIgQ0ExIzAhBgkqhkiG9w0BCQEWFHN1cHBvcnRAZnJhbms0ZGQuY29tMCIY
DzE5MDExMjEzMjA0NTUyWhgPMjAzODAxMTkwMzE0MDdaMEoxCzAJBgNVBAYTAkpQ
MQ4wDAYDVQQIDAVUb2t5bzERMA8GA1UECgwIRnJhbms0REQxGDAWBgNVBAMMD3d3
dy5leGFtcGxlLmNvbTBcMA0GCSqGSIb3DQEBAQUAA0sAMEgCQQCb/GaQeYRCu6sT
/St7+N4VEuXxk+MGinu4seGeJruVAb/nMO1khQLdFWmoNLAG7D81PB4bK4/6jwAb
3wfGrFMHAgMBAAEwDQYJKoZIhvcNAQEFBQADgYEAnzdeQBG2crXnvZyHgCL9dSnm
lnaXJITO//+G59uCvDKbnX+BKvXXxXQIa7GmtzYuw3LC/jJJL307r/CECZr6vV9I
KHn27+yOtrPDOwTDtXyaYOaf8V6fkSVN3iLx7tbEP6R0uEKxaVaqMZ71ed3SO1OL
wq0j8GkKY/K/zl2Nwzc=
-----END CERTIFICATE-----
'''


def test_compare_plan_entity_pem():
    EntityCert = load_test_open_api_spec(secrets_key=None,
                                         reload=True).entities['EntityCert'].cls
    appgate_data = {
        'name': 'c1',
        'fieldOne': PEM_TEST,
        'fieldTwo': {
            'version': 1,
            'serial': '3578',
            'issuer': join_string(ISSUER),
            'subject': join_string(SUBJECT),
            'validFrom': '2012-08-22T05:26:54.000Z',
            'validTo': '2017-08-21T05:26:54.000Z',
            'fingerprint': 'Xw+1FmWBquZKEBwVg7G+vnToFKkeeooUuh6DXXj26ec=',
            'certificate': join_string(CERTIFICATE_FIELD),
            'subjectPublicKey': join_string(PUBKEY_FIELD),
        }
    }
    k8s_data = {
        'name': 'c1',
        'fieldOne': PEM2
    }
    current_entities = EntitiesSet({
        EntityWrapper(APPGATE_LOADER.load(appgate_data, None, EntityCert))
    })
    new_e = K8S_LOADER.load(k8s_data, None, EntityCert)
    expected_entities = EntitiesSet({
        EntityWrapper(new_e)
    })
    plan = compare_entities(current_entities, expected_entities, BUILTIN_TAGS, frozenset(), None)
    assert plan.modify.entities == frozenset({EntityWrapper(new_e)})
    assert plan.modifications_diff == {
        'c1': [
            '--- \n', '+++ \n', '@@ -3,10 +3,10 @@\n',
            '     "fieldTwo": {\n', '-        "version": 1,\n',
            '-        "serial": "3578",\n', '+        "version": 3,\n',
            '+        "serial": "0",\n',
            '         "issuer": "1.2.840.113549.1.9.1=support@frank4dd.com, CN=Frank4DD Web CA, OU=WebCert Support, O=Frank4DD, L=Chuo-ku, ST=Tokyo, C=JP",\n',
            '         "subject": "CN=www.example.com, O=Frank4DD, ST=Tokyo, C=JP",\n',
            '-        "validFrom": "2012-08-22T05:26:54.000Z",\n',
            '-        "validTo": "2017-08-21T05:26:54.000Z",\n',
            '-        "fingerprint": "Xw+1FmWBquZKEBwVg7G+vnToFKkeeooUuh6DXXj26ec=",\n',
            '-        "certificate": "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUNFakNDQVhzQ0FnMzZNQTBHQ1NxR1NJYjNEUUVCQlFVQU1JR2JNUXN3Q1FZRFZRUUdF'
            'd0pLVURFT01Bd0cKQTFVRUNCTUZWRzlyZVc4eEVEQU9CZ05WQkFjVEIwTm9kVzh0YTNVeEVUQVBCZ05WQkFvVENFWnlZVzVyTkVSRQpNUmd3RmdZRFZRUUxFdzlYWldKRFpYS'
            'jBJRk4xY0hCdmNuUXhHREFXQmdOVkJBTVREMFp5WVc1ck5FUkVJRmRsCllpQkRRVEVqTUNFR0NTcUdTSWIzRFFFSkFSWVVjM1Z3Y0c5eWRFQm1jbUZ1YXpSa1pDNWpiMjB3SG'
            'hjTk1USXcKT0RJeU1EVXlOalUwV2hjTk1UY3dPREl4TURVeU5qVTBXakJLTVFzd0NRWURWUVFHRXdKS1VERU9NQXdHQTFVRQpDQXdGVkc5cmVXOHhFVEFQQmdOVkJBb01DRVp'
            '5WVc1ck5FUkVNUmd3RmdZRFZRUUREQTkzZDNjdVpYaGhiWEJzClpTNWpiMjB3WERBTkJna3Foa2lHOXcwQkFRRUZBQU5MQURCSUFrRUFtL3hta0htRVFydXJFLzByZS9qZUZS'
            'TGwKOFpQakJvcDd1TEhobmlhN2xRRy81ekR0WklVQzNSVnBxRFN3QnV3L05Ud2VHeXVQK284QUc5OEh4cXhUQndJRApBUUFCTUEwR0NTcUdTSWIzRFFFQkJRVUFBNEdCQUJTM'
            'lRMdUJlVFBtY2FUYVVXL0xDQjJOWU95OEdNZHpSMW14CjhpQkl1Mkg2L0UydGlZM1JJZXZWMk9XNjFxWTIvWFJRZzdZUHh4M2ZmZVV1Z1g5RjRKL2lQbm51MXpBeHh5QnkKMl'
            'ZndUt2NFNXalJGb1JrSWZJbEhYMHFWdmlNaFNsTnkyaW9GTHk3SmNQWmIrdjNmdERHeXdVcWNCaVZEb2VhMApIbitHbXhaQQotLS0tLUVORCBDRVJUSUZJQ0FURS0tLS0tCg==",\n',
            '+        "validFrom": "1901-12-13T20:45:52.000Z",\n',
            '+        "validTo": "2038-01-19T03:14:07.000Z",\n',
            '+        "fingerprint": "6b7fb51b56acaf0a8f9b9a3f8ca6737cb97821ddb830106c9fc9a14b8bfdfa36",\n',
            '+        "certificate": "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUNHakNDQVlPZ0F3SUJBZ0lCQURBTkJna3Foa2lHOXcwQkFRVUZBRENCbXpFTE1Ba0dB'
            'MVVFQmhNQ1NsQXgKRGpBTUJnTlZCQWdUQlZSdmEzbHZNUkF3RGdZRFZRUUhFd2REYUhWdkxXdDFNUkV3RHdZRFZRUUtFd2hHY21GdQphelJFUkRFWU1CWUdBMVVFQ3hNUFYyV'
            'mlRMlZ5ZENCVGRYQndiM0owTVJnd0ZnWURWUVFERXc5R2NtRnVhelJFClJDQlhaV0lnUTBFeEl6QWhCZ2txaGtpRzl3MEJDUUVXRkhOMWNIQnZjblJBWm5KaGJtczBaR1F1WT'
            'I5dE1DSVkKRHpFNU1ERXhNakV6TWpBME5UVXlXaGdQTWpBek9EQXhNVGt3TXpFME1EZGFNRW94Q3pBSkJnTlZCQVlUQWtwUQpNUTR3REFZRFZRUUlEQVZVYjJ0NWJ6RVJNQTh'
            'HQTFVRUNnd0lSbkpoYm1zMFJFUXhHREFXQmdOVkJBTU1EM2QzCmR5NWxlR0Z0Y0d4bExtTnZiVEJjTUEwR0NTcUdTSWIzRFFFQkFRVUFBMHNBTUVnQ1FRQ2IvR2FRZVlSQ3U2'
            'c1QKL1N0NytONFZFdVh4aytNR2ludTRzZUdlSnJ1VkFiL25NTzFraFFMZEZXbW9OTEFHN0Q4MVBCNGJLNC82andBYgozd2ZHckZNSEFnTUJBQUV3RFFZSktvWklodmNOQVFFR'
            'kJRQURnWUVBbnpkZVFCRzJjclhudlp5SGdDTDlkU25tCmxuYVhKSVRPLy8rRzU5dUN2REtiblgrQkt2WFh4WFFJYTdHbXR6WXV3M0xDL2pKSkwzMDdyL0NFQ1pyNnZWOUkKS0'
            'huMjcreU90clBET3dURHRYeWFZT2FmOFY2ZmtTVk4zaUx4N3RiRVA2UjB1RUt4YVZhcU1aNzFlZDNTTzFPTAp3cTBqOEdrS1kvSy96bDJOd3pjPQotLS0tLUVORCBDRVJUSUZ'
            'JQ0FURS0tLS0tCg==",\n',
            '         "subjectPublicKey": "MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBAJv8ZpB5hEK7qxP9K3v43hUS5'
            'fGT4waKe7ix4Z4mu5UBv+cw7WSFAt0Vaag0sAbsPzU8Hhsrj/qPABvfB8asUwcCAwEAAQ=="\n'
        ]
    }


def test_compare_entities_generation_changed():
    EntityTest2 = load_test_open_api_spec(reload=True,
                                          k8s_get_secret=_k8s_get_secret).entities['EntityTest2'].cls
    data_1 = {
        'fieldOne': {
            'type': 'k8s/secret',
            'name': 'secret-storage-1',
            'key': 'field-one'
        },
        'fieldTwo': 'this is write only',
        'fieldThree': 'this is a field',
    }
    data_2 = {
        'fieldOne': {
            'type': 'k8s/secret',
            'name': 'secret-storage-1',
            'key': 'field-one'
        },
        'fieldTwo': 'this is write only',
        'fieldThree': 'this is a field',
        'created': '2020-09-10T12:20:14Z',
        'updated': '2020-09-10T12:20:14Z'
    }
    appgate_metadata = {
        'generation': 2,
        'latestGeneration': 1,
        'creationTimestamp': '2020-09-10T10:20:14Z',
        'modificationTimestamp': '2020-09-10T12:20:14Z',
    }
    e1 = EntityWrapper(K8S_LOADER.load(data_1, appgate_metadata, EntityTest2))
    e2 = EntityWrapper(APPGATE_LOADER.load(data_2, None, EntityTest2))
    diff = compute_diff(e2, e1)
    assert diff == [
        '--- \n',
        '+++ \n',
        '@@ -2,3 +2,3 @@\n',
        '     "fieldThree": "this is a field",\n',
        '-    "generation": 1\n',
        '+    "generation": 2\n',
        ' }'
    ]


def test_compare_entities_updated_changed():
    EntityTest2 = load_test_open_api_spec(reload=True,
                                          k8s_get_secret=_k8s_get_secret).entities['EntityTest2'].cls
    data_1 = {
        'fieldOne': {
            'type': 'k8s/secret',
            'name': 'secret-storage-1',
            'key': 'field-one'
        },
        'fieldTwo': 'this is write only',
        'fieldThree': 'this is a field',
    }
    data_2 = {
        'fieldOne': {
            'type': 'k8s/secret',
            'name': 'secret-storage-1',
            'key': 'field-one'
        },
        'fieldTwo': 'this is write only',
        'fieldThree': 'this is a field',
        'created': '2020-09-10T12:20:14Z',
        'updated': '2020-09-10T12:20:14Z'
    }
    appgate_metadata = {
        'generation': 1,
        'latestGeneration': 1,
        'creationTimestamp': '2020-09-10T10:20:14Z',
        'modificationTimestamp': '2020-09-16T12:20:14Z',
    }
    e1 = EntityWrapper(K8S_LOADER.load(data_1, appgate_metadata, EntityTest2))
    e2 = EntityWrapper(APPGATE_LOADER.load(data_2, None, EntityTest2))

    diff = compute_diff(e2, e1)
    assert diff == [
        '--- \n',
        '+++ \n',
        '@@ -2,3 +2,3 @@\n',
        '     "fieldThree": "this is a field",\n',
        '-    "updated": "2020-09-10T12:20:14.000Z"\n',
        '+    "updated": "2020-09-16T12:20:14.000Z"\n',
        ' }'
    ]
