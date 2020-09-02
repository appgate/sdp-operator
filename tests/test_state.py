from appgate.openapi.openapi import generate_api_spec
from appgate.state import compare_entities, EntitiesSet, resolve_entities
from tests.utils import entitlement, condition, policy, Policy


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
    entitlements_set, conflicts = resolve_entities(entitlements, conditions, 'conditions')
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
    entitlements_set, conflicts = resolve_entities(entitlements, conditions, 'conditions')
    assert entitlements_set.entities == entitlements.entities
    assert conflicts == {
        'entitlement-1': ('conditions', {'condition1', 'condition2', 'condition3'}),
        'entitlement-2': ('conditions', {'condition1', 'condition2', 'condition3'}),
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
    entitlements_set, conflicts = resolve_entities(entitlements, conditions, 'conditions')
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
    entitlements_set, conflicts = resolve_entities(entitlements, conditions, 'conditions')
    assert conflicts == {
        'entitlement-2': ('conditions', {'condition4', 'condition5'})
    }


def test_normalize_policies_0():
    policies = EntitiesSet()
    entitlements = EntitiesSet()
    policies_set, conflicts = resolve_entities(policies, entitlements, 'entitlements')
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
    policies_set, conflicts = resolve_entities(policies, entitlements, 'entitlements')
    assert conflicts == {
        'policy-1': ('entitlements', {'entitlement1', 'entitlement2', 'entitlement3'}),
        'policy-2': ('entitlements', {'entitlement1', 'entitlement2', 'entitlement3'})
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
    policies_set, conflicts = resolve_entities(policies, entitlements, 'entitlements')
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
    policies_set, conflicts = resolve_entities(policies, entitlements, 'entitlements')
    assert conflicts == {
        'policy-2': ('entitlements', {'entitlement4', 'entitlement5'})
    }
