import pytest

from appgate.types import get_tags


def test_get_tags() -> None:
    assert get_tags([], None) == frozenset()
    assert get_tags(["t1"], None) == frozenset({"t1"})
    assert get_tags(["t2", "t1"], None) == frozenset({"t1", "t2"})
    assert get_tags([], "") == frozenset()
    assert get_tags(["t1"], "") == frozenset({"t1"})
    assert get_tags([], "t1") == frozenset({"t1"})
    assert get_tags(["t1", "t2"], "t1") == frozenset({"t1", "t2"})
    assert get_tags(["t1", "t2"], "t3") == frozenset({"t1", "t2", "t3"})
    assert get_tags(["t1", "t2"], "t3,t4") == frozenset({"t1", "t2", "t3", "t4"})
