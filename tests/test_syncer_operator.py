from pathlib import Path
from unittest import mock

import pytest

from appgate.openapi.openapi import generate_api_spec
from appgate.openapi.types import SPEC_ENTITIES, AppgateException
from appgate.syncer.operator import generate_git_entity_clients

ALL_APPGATE_ENTITIES = set(SPEC_ENTITIES.keys())


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
