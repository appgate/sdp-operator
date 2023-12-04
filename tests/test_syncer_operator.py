import os
from pathlib import Path
from unittest import mock

import pytest

from appgate.openapi.openapi import generate_api_spec
from appgate.openapi.types import SPEC_ENTITIES, AppgateException
from appgate.syncer.operator import generate_git_entity_clients, git_operator_context
from appgate.types import (
    GitOperatorArguments,
    GIT_REPOSITORY_ENV,
    GIT_BASE_BRANCH_ENV,
    GIT_VENDOR_ENV,
)

ALL_APPGATE_ENTITIES = set(SPEC_ENTITIES.values())


def test_generate_git_entity_clients_0() -> None:
    assert len(
        generate_git_entity_clients(
            api_spec=generate_api_spec(),
            repository_path=Path("/tmp/test"),
            branch="main",
            git=mock.Mock(),
            resolution_conflicts={},
        )
    ) == len(ALL_APPGATE_ENTITIES)


def test_generate_git_entity_clients_1() -> None:
    assert (
        len(
            generate_git_entity_clients(
                api_spec=generate_api_spec(
                    entities_to_include={"Entitlement", "Policy", "Condition"}
                ),
                repository_path=Path("/tmp/test"),
                branch="main",
                git=mock.Mock(),
                resolution_conflicts={},
            )
        )
        == 3
    )


def test_generate_git_entity_clients_2() -> None:
    assert (
        len(
            generate_git_entity_clients(
                api_spec=generate_api_spec(
                    entities_to_exclude={"Entitlement", "Policy", "Condition"},
                ),
                repository_path=Path("/tmp/test"),
                branch="main",
                git=mock.Mock(),
                resolution_conflicts={},
            )
        )
        == len(ALL_APPGATE_ENTITIES) - 3
    )


def test_generate_git_entity_clients_3() -> None:
    with pytest.raises(AppgateException, match="There are no API entities to manage"):
        generate_git_entity_clients(
            api_spec=generate_api_spec(entities_to_include={"DoesNotExist"}),
            repository_path=Path("/tmp/test"),
            branch="main",
            git=mock.Mock(),
            resolution_conflicts={},
        )


def test_git_operator_context_0() -> None:
    os.environ[GIT_VENDOR_ENV] = "github"
    os.environ[GIT_REPOSITORY_ENV] = "test"
    os.environ[GIT_BASE_BRANCH_ENV] = "main"
    ctx = git_operator_context(
        GitOperatorArguments(
            namespace="ns",
        )
    )
    assert set(ctx.api_spec.api_entities.keys()) == ALL_APPGATE_ENTITIES


def test_git_operator_context_1() -> None:
    os.environ[GIT_VENDOR_ENV] = "github"
    os.environ[GIT_REPOSITORY_ENV] = "test"
    os.environ[GIT_BASE_BRANCH_ENV] = "main"
    ctx = git_operator_context(
        GitOperatorArguments(
            namespace="ns", entities_to_include={"Entitlement", "Policy", "Condition"}
        )
    )
    assert set(ctx.api_spec.api_entities.keys()) == {
        "Entitlement",
        "Policy",
        "Condition",
    }


def test_git_operator_context_2() -> None:
    os.environ[GIT_VENDOR_ENV] = "github"
    os.environ[GIT_REPOSITORY_ENV] = "test"
    os.environ[GIT_BASE_BRANCH_ENV] = "main"
    ctx = git_operator_context(
        GitOperatorArguments(
            namespace="ns", entities_to_exclude={"Entitlement", "Policy", "Condition"}
        )
    )
    assert set(ctx.api_spec.api_entities.keys()) == ALL_APPGATE_ENTITIES - {
        "Entitlement",
        "Policy",
        "Condition",
    }


def test_git_operator_context_3() -> None:
    os.environ[GIT_VENDOR_ENV] = "github"
    os.environ[GIT_REPOSITORY_ENV] = "test"
    os.environ[GIT_BASE_BRANCH_ENV] = "main"
    with pytest.raises(AppgateException, match="There are no API entities to manage"):
        _ = git_operator_context(
            GitOperatorArguments(namespace="ns", entities_to_include={"DoesNotExist"})
        ).api_spec.api_entities
