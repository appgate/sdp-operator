from appgate.attrs import K8S_LOADER
from appgate.state import compare_entities, EntitiesSet, resolve_entities, AppgateState, resolve_appgate_state
from tests.utils import entitlement, condition, policy, Policy, load_test_open_api_spec, TestOpenAPI


def test_compare_policies_0():
    current_policies = EntitiesSet({
        Policy(id='id1',
               name='policy1',
               expression='expression-1'),
        Policy(id='id2',
               name='policy2',
               expression='expression-2'),
        Policy(id='id3',
               name='policy3',
               expression='expression-3')
    })
    expected_policies = EntitiesSet(set())
    plan = compare_entities(current_policies, expected_policies)
    assert plan.delete.entities == {
        Policy(id='id1',
               name='policy1',
               expression='expression-1'),
        Policy(id='id2',
               name='policy2',
               expression='expression-2'),
        Policy(id='id3',
               name='policy3',
               expression='expression-3')
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
        Policy(name='policy1',
               expression='expression-1'),
        Policy(name='policy2',
               expression='expression-2'),
        Policy(name='policy3',
               expression='expression-3')
    })
    plan = compare_entities(current_policies, expected_policies)
    assert plan.create.entities == {
        Policy(name='policy1',
               expression='expression-1'),
        Policy(name='policy2',
               expression='expression-2'),
        Policy(name='policy3',
               expression='expression-3')
    }
    assert plan.modify.entities == set()
    assert plan.delete.entities == set()


def test_compare_policies_2():
    current_policies = EntitiesSet({
        Policy(id='id1',
               name='policy1',
               expression='expression-1'),
        Policy(id='id2',
               name='policy2',
               expression='expression-2'),
        Policy(id='id3',
               name='policy3',
               expression='expression-3')
    })
    expected_policies = EntitiesSet({
        Policy(id='id1',
               name='policy1',
               expression='expression-1'),
        Policy(id='id2',
               name='policy2',
               expression='expression-2'),
        Policy(id='id3',
               name='policy3',
               expression='expression-3')
    })
    plan = compare_entities(current_policies, expected_policies)
    assert plan.modify.entities == set()
    assert plan.delete.entities == set()
    assert plan.create.entities == set()
    assert plan.share.entities == {
        Policy(id='id1',
               name='policy1',
               expression='expression-1'),
        Policy(id='id2',
               name='policy2',
               expression='expression-2'),
        Policy(id='id3',
               name='policy3',
               expression='expression-3')
    }
    share_ids = [p.id for p in plan.share.entities]
    assert len(list(filter(None, share_ids))) == 3
    share_ids.sort()
    assert share_ids == ['id1', 'id2', 'id3']


def test_compare_policies_3():
    current_policies = EntitiesSet({
        Policy(id='id1',
               name='policy3',
               expression='expression-1'),
        Policy(id='id2',
               name='policy2',
               expression='expression-2'),
        Policy(id='id3',
               name='policy4',
               expression='expression-3')
    })
    expected_policies = EntitiesSet({
        Policy(name='policy1',
               expression='expression-1'),
        Policy(id='id2',
               name='policy2',
               expression='expression-2'),
        Policy(id='id3',
               name='policy4',
               expression='expression-3')
    })
    plan = compare_entities(current_policies, expected_policies)
    assert plan.delete.entities == {Policy(id='id1', name='policy3', expression='expression-1')}
    # test that the ids are propagated when modifying
    assert [p.id for p in plan.delete.entities] == ['id1']
    assert plan.create.entities == {Policy(name='policy1', expression='expression-1')}
    assert plan.modify.entities == set()


def test_compare_policies_4():
    current_policies = EntitiesSet({
        Policy(id='id0',
               name='policy0',
               expression='expression-0'),
        Policy(id='id1',
               name='policy1',
               expression='expression-1'),
        Policy(id='id2',
               name='policy2',
               expression='expression-2'),
        Policy(id='id3',
               name='policy3',
               expression='expression-3')
    })
    expected_policies = EntitiesSet({
        Policy(id='id0',
               name='policy0',
               expression='expression-0'),
        Policy(id='id1',
               name='policy1',
               expression='expression-2'),
        Policy(id='id2',
               name='policy2',
               expression='expression-3'),
        Policy(name='policy4',
               expression='expression-4')
    })
    plan = compare_entities(current_policies, expected_policies)
    assert plan.delete.entities == {Policy(id='id3', name='policy3', expression='expression-3')}
    # test that the ids are propagated when modifying
    assert [p.id for p in plan.delete.entities] == ['id3']
    assert plan.create.entities == {Policy(name='policy4', expression='expression-4')}
    assert plan.modify.entities == {
        Policy(id='id1',
               name='policy1',
               expression='expression-2'),
        Policy(id='id2',
               name='policy2',
               expression='expression-3')
    }


def test_normalize_entitlements_0():
    entitlements = EntitiesSet()
    conditions = EntitiesSet()
    entitlements_set, conflicts = resolve_entities(entitlements, [(conditions, 'conditions')])
    assert entitlements_set.entities == set()
    assert conflicts is None


def test_normalize_entitlements_1():
    entitlements = EntitiesSet({
        entitlement(name='entitlement-1', conditions=[
            'condition1',
            'condition2',
            'condition3'
        ]),
        entitlement(name='entitlement-2', conditions=[
            'condition1',
            'condition2',
            'condition3',
        ]),
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
        entitlement(name='entitlement-1', conditions=[
            'condition1',
            'condition2',
            'condition3'
        ]),
        entitlement(name='entitlement-2', conditions=[
            'condition1',
            'condition4',
            'condition5',
        ]),
    })
    conditions = EntitiesSet({
        condition(id='c1', name='condition1'),
        condition(id='c2', name='condition2'),
        condition(id='c3', name='condition3'),
        condition(id='c4', name='condition4'),
        condition(id='c5', name='condition5'),
    })
    entitlements_set, conflicts = resolve_entities(entitlements, [(conditions, 'conditions')])
    assert entitlements_set.entities == {
        entitlement(name='entitlement-1', conditions=[
            'c1',
            'c2',
            'c3'
        ]),
        entitlement(name='entitlement-2', conditions=[
            'c1',
            'c4',
            'c5',
        ]),
    }
    assert conflicts is None


def test_normalize_entitlements_3():
    entitlements = EntitiesSet({
        entitlement(name='entitlement-1', conditions=[
            'condition1',
            'condition2',
            'condition3'
        ]),
        entitlement(name='entitlement-2', conditions=[
            'condition1',
            'condition4',
            'condition5',
        ]),
    })
    conditions = EntitiesSet({
        condition(id='id1', name='condition1'),
        condition(id='id2', name='condition2'),
        condition(id='id3', name='condition3'),
        condition(name='condition4'),
        condition(name='condition5'),
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
        policy(name='policy-1', entitlements=[
            'entitlement1',
            'entitlement2',
            'entitlement3'
        ]),
        policy(name='policy-2', entitlements=[
            'entitlement1',
            'entitlement2',
            'entitlement3',
        ]),
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
        policy(name='policy-1', entitlements=[
            'entitlement1',
            'entitlement2',
            'entitlement3'
        ]),
        policy(name='policy-2', entitlements=[
            'entitlement1',
            'entitlement4',
            'entitlement5',
        ]),
    })
    entitlements = EntitiesSet({
            entitlement(id='e1', name='entitlement1'),
            entitlement(id='e2', name='entitlement2'),
            entitlement(id='e3', name='entitlement3'),
            entitlement(id='e4', name='entitlement4'),
            entitlement(id='e5', name='entitlement5'),
        })
    policies_set, conflicts = resolve_entities(policies, [(entitlements, 'entitlements')])
    assert conflicts is None
    assert policies_set.entities == {
        policy(name='policy-1', entitlements=[
            'e1',
            'e2',
            'e3'
        ]),
        policy(name='policy-2', entitlements=[
            'e1',
            'e4',
            'e5',
        ]),
    }


def test_normalize_policies_3():
    policies = EntitiesSet({
        policy(name='policy-1', entitlements=[
            'entitlement1',
            'entitlement2',
            'entitlement3'
        ]),
        policy(name='policy-2', entitlements=[
            'entitlement1',
            'entitlement4',
            'entitlement5',
        ]),
    })
    entitlements = EntitiesSet({
        entitlement(id='id1', name='entitlement1'),
        entitlement(id='id2', name='entitlement2'),
        entitlement(id='id3', name='entitlement3'),
        entitlement(name='entitlement5')
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
        EntityDep1(id='d11', name='dep11'),
        EntityDep1(id='d12', name='dep12'),
        EntityDep1(id='d13', name='dep13'),
    })
    deps3 = EntitiesSet({
        EntityDep3(id='d31', name='dep31', deps1=frozenset({'dep11', 'dep12'}))
    })

    # No conflits
    deps3_resolved, conflicts = resolve_entities(deps3, [(deps1, 'deps1')])
    assert conflicts is None
    assert deps3_resolved.entities == {
        EntityDep3(id='d31', name='dep31', deps1=frozenset({'d11', 'd12'}))
    }

    # Conflicts
    deps3 = EntitiesSet({
        EntityDep3(id='d31', name='dep31', deps1=frozenset({'dep14', 'dep12'}))
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
        EntityDep1(id='d11', name='dep11'),
        EntityDep1(id='d12', name='dep12'),
        EntityDep1(id='d13', name='dep13'),
    })
    deps2 = EntitiesSet({
        EntityDep2(id='d21', name='dep21'),
        EntityDep2(id='d22', name='dep22'),
        EntityDep2(id='d23', name='dep23'),
    })

    # no conflicts
    deps4 = EntitiesSet({
        EntityDep4(id='d31', name='dep31', deps1=frozenset({'dep11', 'dep12'}),
                   dep2='dep23')
    })
    deps3_resolved, conflicts = resolve_entities(deps4, [(deps1, 'deps1'),
                                                         (deps2, 'dep2')])
    assert conflicts is None
    assert deps3_resolved.entities == {
        EntityDep4(id='d31', name='dep31', deps1=frozenset({'d11', 'd12'}),
                   dep2='d23')
    }

    # conflicts in field deps1
    deps4 = EntitiesSet({
        EntityDep4(id='d31', name='dep31', deps1=frozenset({'dep14', 'dep12'}),
                   dep2='dep33')
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
        EntityDep1(id='d11', name='dep11'),
        EntityDep1(id='d12', name='dep12'),
        EntityDep1(id='d13', name='dep13'),
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
        K8S_LOADER.load(data, None, EntityDep5)
    })
    deps5_resolved, conflicts = resolve_entities(deps5, [(deps1, 'obj1.obj2.dep1')])
    assert conflicts is None
    assert deps5_resolved.entities == {
        EntityDep5(id='d51', name='dep51',
                   obj1=EntityDep5_Obj1(obj2=EntityDep5_Obj1_Obj2(dep1='d11')))
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
        EntityDep1(id='d11', name='dep11'),
        EntityDep1(id='d12', name='dep12'),
        EntityDep1(id='d13', name='dep13'),
    })
    deps2 = EntitiesSet({
        EntityDep2(id='d21', name='dep21'),
        EntityDep2(id='d22', name='dep22'),
        EntityDep2(id='d23', name='dep23'),
    })
    deps3 = EntitiesSet({
        EntityDep3(id='d31', name='dep31', deps1=frozenset({'dep11', 'dep12'})),
        EntityDep3(id='d32', name='dep32', deps1=frozenset({'dep11', 'dep13'})),
        EntityDep3(id='d33', name='dep33', deps1=frozenset({'dep12', 'dep13'})),
    })
    deps4 = EntitiesSet({
        EntityDep4(id='d41', name='dep41', deps1=frozenset({'dep11', 'dep12'}),
                   dep2='dep21'),
        EntityDep4(id='d42', name='dep42', deps1=frozenset({'dep11', 'dep13'}),
                   dep2='dep22'),
        EntityDep4(id='d43', name='dep43', deps1=frozenset({'dep12', 'dep13'}),
                   dep2='dep23'),
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
        K8S_LOADER.load(data, None, EntityDep6)
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
        EntityDep1(id='d11', name='dep11'),
        EntityDep1(id='d12', name='dep12'),
        EntityDep1(id='d13', name='dep13'),
    }
    assert appgate_state.entities_set['EntityDep2'].entities == {
        EntityDep2(id='d21', name='dep21'),
        EntityDep2(id='d22', name='dep22'),
        EntityDep2(id='d23', name='dep23'),
    }
    assert appgate_state.entities_set['EntityDep3'].entities == {
        EntityDep3(id='d31', name='dep31', deps1=frozenset({'d11', 'd12'})),
        EntityDep3(id='d32', name='dep32', deps1=frozenset({'d11', 'd13'})),
        EntityDep3(id='d33', name='dep33', deps1=frozenset({'d12', 'd13'})),
    }
    assert appgate_state.entities_set['EntityDep4'].entities == {
        EntityDep4(id='d41', name='dep41', deps1=frozenset({'d11', 'd12'}),
                   dep2='d21'),
        EntityDep4(id='d42', name='dep42', deps1=frozenset({'d11', 'd13'}),
                   dep2='d22'),
        EntityDep4(id='d43', name='dep43', deps1=frozenset({'d12', 'd13'}),
                   dep2='d23'),
    }
    assert appgate_state.entities_set['EntityDep6'].entities == {
        EntityDep6(name='dep61',
                   deps4=frozenset({'d42', 'd41'}),
                   obj1=EntityDep6_Obj1(dep3='d31',
                                        obj2=EntityDep6_Obj1_Obj2(
                                            deps1=frozenset({
                                                EntityDep6_Obj1_Obj2_Deps1(dep1='dep11'),
                                                EntityDep6_Obj1_Obj2_Deps1(dep1='dep12'),
                                                EntityDep6_Obj1_Obj2_Deps1(dep1='dep13'),
                                            }),
                                            deps2=frozenset({'d21', 'd22'}))))
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
        K8S_LOADER.load(data, None, EntityDep6)
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
        EntityDep6(name='dep61',
                   deps4=frozenset(),
                   obj1=EntityDep6_Obj1(dep3='d31',
                                        obj2=EntityDep6_Obj1_Obj2(
                                            deps1=frozenset(),
                                            deps2=frozenset({'d21', 'd22'}))))
    }
