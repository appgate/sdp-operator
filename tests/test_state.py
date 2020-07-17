import pytest

from appgate.state import compare_entities, Plan, resolve_entitlements, resolve_policies
from appgate.types import Policy, Entitlement, Condition
from tests.utils import entitlement, condition, policy


def test_compare_policies_0():
    current_policies = {
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
    expected_policies = set()
    plan = compare_entities(current_policies, expected_policies)
    assert plan.delete == {
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
    delete_ids = [p.id for p in plan.delete]
    delete_ids.sort()
    assert delete_ids == ['id1', 'id2', 'id3']
    assert plan.modify == set()
    assert plan.create == set()


def test_compare_policies_1():
    current_policies = set()
    expected_policies = {
        Policy(name='policy1',
               expression='expression-1'),
        Policy(name='policy2',
               expression='expression-2'),
        Policy(name='policy3',
               expression='expression-3')
    }
    plan = compare_entities(current_policies, expected_policies)
    assert plan.create == {
        Policy(name='policy1',
               expression='expression-1'),
        Policy(name='policy2',
               expression='expression-2'),
        Policy(name='policy3',
               expression='expression-3')
    }
    assert plan.modify == set()
    assert plan.delete == set()


def test_compare_policies_2():
    current_policies = {
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
    expected_policies = {
        Policy(name='policy1',
               expression='expression-1'),
        Policy(name='policy2',
               expression='expression-2'),
        Policy(name='policy3',
               expression='expression-3')
    }
    plan = compare_entities(current_policies, expected_policies)
    assert plan.modify == set()
    assert plan.delete == set()
    assert plan.create == set()
    assert plan.share == {
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
    share_ids = [p.id for p in plan.share]
    assert len(list(filter(None, share_ids))) == 3
    share_ids.sort()
    assert share_ids == ['id1', 'id2', 'id3']


def test_compare_policies_3():
    current_policies = {
        Policy(id='id1',
               name='policy3',
               expression='expression-1'),
        Policy(id='id2',
               name='policy2',
               expression='expression-2'),
        Policy(id='id3',
               name='policy4',
               expression='expression-3')
    }
    expected_policies = {
        Policy(name='policy1',
               expression='expression-1'),
        Policy(name='policy2',
               expression='expression-2'),
        Policy(name='policy4',
               expression='expression-3')
    }
    plan = compare_entities(current_policies, expected_policies)
    assert plan.delete == {Policy(id='id1', name='policy3', expression='expression-1')}
    # test that the ids are propagated when modifying
    assert [p.id for p in plan.delete] == ['id1']
    assert plan.create == {Policy(name='policy1', expression='expression-1')}
    assert plan.modify == set()


def test_compare_policies_4():
    current_policies = {
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
    }
    expected_policies = {
        Policy(name='policy0',
               expression='expression-0'),
        Policy(name='policy1',
               expression='expression-2'),
        Policy(name='policy2',
               expression='expression-3'),
        Policy(name='policy4',
               expression='expression-4')
    }
    plan = compare_entities(current_policies, expected_policies)
    assert plan.delete == {Policy(id='id3', name='policy3', expression='expression-3')}
    # test that the ids are propagated when modifying
    assert [p.id for p in plan.delete] == ['id3']
    assert plan.create == {Policy(name='policy4', expression='expression-4')}
    assert plan.modify == {
        Policy(id='id1',
               name='policy1',
               expression='expression-2'),
        Policy(id='id2',
               name='policy2',
               expression='expression-3')
    }
    # test that the ids are propagated when modifying
    delete_ids = [p.id for p in plan.modify]
    assert len(list(filter(None, delete_ids))) == 2
    delete_ids.sort()
    assert delete_ids == ['id1', 'id2']
    assert plan.share == {Policy(id='id0',
                                 name='policy0',
                                 expression='expression-0')}
    shared_ids = [p.id for p in plan.share]
    assert len(list(filter(None, shared_ids))) == 1
    shared_ids.sort()

    assert shared_ids == ['id0']


def test_normalize_entitlements_0():
    entitlements = Plan()
    conditions = Plan()
    assert resolve_entitlements(entitlements, conditions) is None


def test_normalize_entitlements_1():
    entitlements = Plan(create={
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
    conditions = Plan()
    assert resolve_entitlements(entitlements, conditions) == {
        'entitlement-1': {'condition1', 'condition2', 'condition3'},
        'entitlement-2': {'condition1', 'condition2', 'condition3'},
    }


def test_normalize_entitlements_2():
    entitlements = Plan(create={
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
    conditions = Plan(
        create={
            condition(name='condition1'),
            condition(name='condition2'),
            condition(name='condition3'),
            condition(name='condition4'),
            condition(name='condition5'),
        }
    )
    assert resolve_entitlements(entitlements, conditions) is None


def test_normalize_entitlements_3():
    entitlements = Plan(create={
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
    conditions = Plan(
        modify={
            condition(id='id1', name='condition1'),
            condition(id='id2', name='condition2'),
            condition(id='id3', name='condition3'),
            condition(id='id4', name='condition4'),
            condition(id='id5', name='condition5'),
        }
    )
    assert resolve_entitlements(entitlements, conditions) is None


def test_normalize_policies_0():
    policies = Plan()
    entitlements = Plan()
    assert resolve_policies(policies, entitlements) is None


def test_normalize_policies_1():
    policies = Plan(create={
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
    entitlements = Plan()
    assert resolve_policies(policies, entitlements) == {
        'policy-1': {'entitlement1', 'entitlement2', 'entitlement3'},
        'policy-2': {'entitlement1', 'entitlement2', 'entitlement3'}
    }


def test_normalize_policies_2():
    policies = Plan(create={
        policy(name='entitlement-1', entitlements=[
            'entitlement1',
            'entitlement2',
            'entitlement3'
        ]),
        policy(name='entitlement-2', entitlements=[
            'entitlement1',
            'entitlement4',
            'entitlement5',
        ]),
    })
    entitlements = Plan(
        create={
            entitlement(name='entitlement1'),
            entitlement(name='entitlement2'),
            entitlement(name='entitlement3'),
            entitlement(name='entitlement4'),
            entitlement(name='entitlement5'),
        }
    )
    assert resolve_policies(policies, entitlements) is None


def test_normalize_policies_3():
    policies = Plan(create={
        policy(name='entitlement-1', entitlements=[
            'entitlement1',
            'entitlement2',
            'entitlement3'
        ]),
        policy(name='entitlement-2', entitlements=[
            'entitlement1',
            'entitlement4',
            'entitlement5',
        ]),
    })
    entitlements = Plan(
        modify={
            entitlement(id='id1', name='entitlement1'),
            entitlement(id='id2', name='entitlement2'),
            entitlement(id='id3', name='entitlement3'),
        },
        share={
            entitlement(id='id4', name='entitlement4'),
            entitlement(id='id5', name='entitlement5')
        }
    )
    assert resolve_policies(policies, entitlements) is None
