from unittest import mock

import pytest

from appgate.openapi.openapi import generate_api_spec, generate_api_spec_clients
from appgate.openapi.types import (
    AppgateException,
    get_supported_entities,
    SPEC_ENTITIES,
)

ALL_APPGATE_ENTITIES = set(get_supported_entities(SPEC_ENTITIES).keys())


def test_generate_api_spec_clients_0() -> None:
    assert len(
        generate_api_spec_clients(
            api_spec=generate_api_spec(),
            appgate_client=mock.Mock(),
        )
    ) == len(ALL_APPGATE_ENTITIES)


def test_generate_api_spec_clients_1() -> None:
    assert (
        len(
            generate_api_spec_clients(
                api_spec=generate_api_spec(
                    entities_to_include=frozenset(
                        {"Entitlement", "Policy", "Condition"}
                    )
                ),
                appgate_client=mock.Mock(),
            )
        )
        == 3
    )


def test_generate_api_spec_clients_2() -> None:
    assert (
        len(
            generate_api_spec_clients(
                api_spec=generate_api_spec(
                    entities_to_exclude=frozenset(
                        {"Entitlement", "Policy", "Condition"}
                    )
                ),
                appgate_client=mock.Mock(),
            )
        )
        == len(ALL_APPGATE_ENTITIES) - 3
    )


def test_generate_api_spec_clients_3() -> None:
    with pytest.raises(AppgateException, match="There are no API entities to manage"):
        generate_api_spec_clients(
            api_spec=generate_api_spec(entities_to_include=frozenset({"IDontExist"})),
            appgate_client=mock.Mock(),
        )
