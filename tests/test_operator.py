from asyncio import Queue

import pytest

from appgate.openapi.openapi import generate_api_spec
from appgate.openapi.types import SPEC_ENTITIES, AppgateException
from appgate.operator import get_k8s_tasks


ALL_APPGATE_ENTITIES = set(SPEC_ENTITIES.keys())


def test_get_k8s_tasks_0() -> None:
    assert len(
        get_k8s_tasks(
            queue=Queue(),
            api_spec=generate_api_spec(),
            namespace="test",
            k8s_configmap_client=None,
        )
    ) == len(ALL_APPGATE_ENTITIES)


def test_get_k8s_tasks_1() -> None:
    assert (
        len(
            get_k8s_tasks(
                queue=Queue(),
                api_spec=generate_api_spec(
                    entities_to_include={"Entitlement", "Policy", "Condition"}
                ),
                namespace="test",
                k8s_configmap_client=None,
            )
        )
        == 3
    )


def test_get_k8s_tasks_2() -> None:
    assert (
        len(
            get_k8s_tasks(
                queue=Queue(),
                api_spec=generate_api_spec(
                    entities_to_exclude={"Entitlement", "Policy", "Condition"}
                ),
                namespace="test",
                k8s_configmap_client=None,
            )
        )
        == len(ALL_APPGATE_ENTITIES) - 3
    )


def test_get_k8s_tasks_3() -> None:
    with pytest.raises(AppgateException, match="There are no API entities to manage"):
        get_k8s_tasks(
            queue=Queue(),
            api_spec=generate_api_spec(entities_to_include={"DoesNotExistSoItsEmpy"}),
            namespace="test",
            k8s_configmap_client=None,
        )
