from asyncio import Queue

import pytest

from appgate.__main__ import appgate_operator_context
from appgate.openapi.openapi import generate_api_spec
from appgate.openapi.types import SPEC_ENTITIES, AppgateException
from appgate.operator import get_k8s_tasks
from appgate.types import AppgateOperatorArguments

ALL_APPGATE_ENTITIES = set(SPEC_ENTITIES.values())


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


def test_appgate_operator_context_0() -> None:
    ctx = appgate_operator_context(
        args=AppgateOperatorArguments(
            namespace="ns",
            password="password",
            user="user",
            host="http://www.appgate.com:443",
        )
    )
    assert set(ctx.api_spec.api_entities.keys()) == ALL_APPGATE_ENTITIES


def test_appgate_operator_context_1() -> None:
    ctx = appgate_operator_context(
        args=AppgateOperatorArguments(
            namespace="ns",
            password="password",
            user="user",
            host="http://www.appgate.com:443",
            entities_to_include={"Entitlement", "Policy", "Condition"},
        )
    )
    assert set(ctx.api_spec.api_entities.keys()) == {
        "Entitlement",
        "Policy",
        "Condition",
    }


def test_appgate_operator_context_2() -> None:
    ctx = appgate_operator_context(
        args=AppgateOperatorArguments(
            namespace="ns",
            password="password",
            user="user",
            host="http://www.appgate.com:443",
            entities_to_exclude={"Entitlement", "Policy", "Condition"},
        )
    )
    assert set(ctx.api_spec.api_entities.keys()) == ALL_APPGATE_ENTITIES - {
        "Entitlement",
        "Policy",
        "Condition",
    }


def test_appgate_operator_context_3() -> None:
    with pytest.raises(AppgateException, match="There are no API entities to manage"):
        _ = appgate_operator_context(
            args=AppgateOperatorArguments(
                namespace="ns",
                password="password",
                user="user",
                host="http://www.appgate.com:443",
                entities_to_include={"DoesNotExistSoItsEmpy"},
            )
        ).api_spec.api_entities
