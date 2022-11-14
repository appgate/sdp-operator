from pathlib import Path

import pytest
import yaml

from appgate.openapi.openapi import generate_crd, generate_api_spec, SPEC_DIR


ENTITIES_TO_TEST = {
    "Appliance",
    "Policy",
    "Entitlement",
    "Condition",
    "IdentityProvider",
    "IpPool",
}


def assert_equal_crd(version: str) -> None:
    open_api = generate_api_spec(Path(SPEC_DIR).parent / version)
    for entity in ENTITIES_TO_TEST:
        crd = generate_crd(open_api.entities[entity].cls, {}, version)

        with (Path("tests/resources/crd") / version / entity.lower()).with_suffix(
            ".yaml"
        ).open("r") as f:
            assert yaml.safe_load(crd) == yaml.safe_load(f)


@pytest.mark.skip("SDP v5.1 is unsupported")
def test_generate_crd_v12():
    assert_equal_crd("v12")


@pytest.mark.skip("SDP v5.2 is unsupported")
def test_generate_crd_v13():
    assert_equal_crd("v13")


def test_generate_crd_v14():
    assert_equal_crd("v14")


def test_generate_crd_v15():
    assert_equal_crd("v15")


def test_generate_crd_v16():
    assert_equal_crd("v16")


def test_generate_crd_v17():
    assert_equal_crd("v17")


def test_generate_crd_v18():
    assert_equal_crd("v18")
