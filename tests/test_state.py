import pytest

from appgate.state import compare_entities, Plan
from appgate.types import Policy


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
    assert compare_entities(current_policies, expected_policies) == Plan()


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
