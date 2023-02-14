import os
from unittest.mock import patch

import pytest

from appgate.attrs import K8S_LOADER
from appgate.openapi.types import AppgateTypedloadException, PlatformType
from tests.utils import load_test_open_api_spec, new_file_source


@pytest.fixture
def http_file_source():
    with new_file_source(
        {
            # file referenced via name/field (test test_bytes_diff_dump)
            "localhost:8000/entitytestfilecomplex-v18/2c4779e28ec964baa2afdeb862be4b9776562866443cfcf22f37950c20ed0af2": b"start123",
            "localhost:8000/entitytestfilecomplex-v18/my-script.sh": b"start123",
        }
    ) as s:
        yield s


@pytest.fixture
def s3_file_source():
    with new_file_source(
        tpe="S3",
        contents={
            # file referenced via name/field (test test_bytes_diff_dump)
            "sdp/entitytestfilecomplex-v18/2c4779e28ec964baa2afdeb862be4b9776562866443cfcf22f37950c20ed0af2": b"start123",
            "sdp/entitytestfilecomplex-v18/my-script.sh": b"start123",
        },
    ) as s:
        yield s


@patch.dict(os.environ, {"APPGATE_FILE_SOURCE": "http"})
@patch.dict(os.environ, {"APPGATE_FILE_HTTP_ADDRESS": "localhost:8000"})
@patch.dict(os.environ, {"APPGATE_API_VERSION": "v18"})
def test_load_http_file_0(http_file_source):
    """
    Test EntityTestFile file source.
    This entity does not define readOnly or readWrite fields so an external bytes source won't be used
    """
    EntityTestFile = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTestFile"]
        .cls
    )
    data = {"filename": "test-entity.sh"}
    expected_entity = EntityTestFile(filename="test-entity.sh", file="")
    e = K8S_LOADER.load(data, None, EntityTestFile)
    assert http_file_source.call_count == 0
    assert expected_entity == e


@patch.dict(os.environ, {"APPGATE_FILE_SOURCE": "http"})
@patch.dict(os.environ, {"APPGATE_FILE_HTTP_ADDRESS": "localhost:8000"})
@patch.dict(os.environ, {"APPGATE_API_VERSION": "v18"})
def test_load_http_file_1(http_file_source):
    """
    Test EntityTEstFileComplex file source.
    This entity defines readOnly or readWrite fields. It does define a checksum field also
    """
    EntityTestFileComplex = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTestFileComplex"]
        .cls
    )
    # Test 1: file field is not specified
    data = {
        "filename": "test-entity.sh",
        "checksum": "2c4779e28ec964baa2afdeb862be4b9776562866443cfcf22f37950c20ed0af2",
    }
    e = K8S_LOADER.load(data, None, EntityTestFileComplex)
    http_file_source.assert_called_once_with(
        "localhost:8000/entitytestfilecomplex-v18/2c4779e28ec964baa2afdeb862be4b9776562866443cfcf22f37950c20ed0af2"
    )

    assert e == EntityTestFileComplex(
        filename="test-entity.sh",
        file="c3RhcnQxMjM=",
        checksum="2c4779e28ec964baa2afdeb862be4b9776562866443cfcf22f37950c20ed0af2",
    )

    # Test 2: file field is specified
    # The contents of file will be used to compute the URL
    data = {
        "filename": "test-entity.sh",
        "file": "my-script.sh",
        "checksum": "2c4779e28ec964baa2afdeb862be4b9776562866443cfcf22f37950c20ed0af2",
    }
    expected_entity = EntityTestFileComplex(
        filename="test-entity.sh",
        file="c3RhcnQxMjM=",
        checksum="2c4779e28ec964baa2afdeb862be4b9776562866443cfcf22f37950c20ed0af2",
    )
    http_file_source.call_count = 0
    e = K8S_LOADER.load(data, None, EntityTestFileComplex)
    http_file_source.assert_called_once_with(
        "localhost:8000/entitytestfilecomplex-v18/my-script.sh"
    )
    assert expected_entity == e


def test_load_http_file_2(http_file_source):
    """
    We don't have defined any HTTP server we should fail to load the entity
    """
    EntityTestFileComplex = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTestFileComplex"]
        .cls
    )
    data = {"filename": "test-entity.sh"}
    with pytest.raises(AppgateTypedloadException) as exc:
        _ = K8S_LOADER.load(data, None, EntityTestFileComplex)
    assert exc.value.platform_type == PlatformType.K8S
    assert exc.value.args == (
        "Unable to load field file for entity EntityTestFileComplex.\nPath: .",
    )


@patch.dict(os.environ, {"APPGATE_FILE_SOURCE": "s3"})
@patch.dict(os.environ, {"APPGATE_API_VERSION": "v18"})
def test_load_s3_file_0(s3_file_source):
    """
    Test EntityTestFile file source.
    This entity does not define readOnly or readWrite fields so an external bytes source won't be used
    """
    EntityTestFile = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTestFile"]
        .cls
    )
    data = {"filename": "test-entity.sh"}
    expected_entity = EntityTestFile(
        filename="test-entity.sh",
        file="",
    )
    e = K8S_LOADER.load(data, None, EntityTestFile)
    assert s3_file_source.call_count == 0
    assert expected_entity == e


@patch.dict(os.environ, {"APPGATE_FILE_SOURCE": "s3"})
@patch.dict(os.environ, {"APPGATE_API_VERSION": "v18"})
def test_load_s3_file_1(s3_file_source):
    """
    Test EntityTEstFileComplex file source.
    This entity defines readOnly or readWrite fields. It does define a checksum field also
    """
    EntityTestFileComplex = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTestFileComplex"]
        .cls
    )

    # Test 1: file field is not specified
    # The entity defines `x-checksum: checksum` so checksum field will be used to generate the url
    data = {
        "filename": "test-entity.sh",
        "checksum": "2c4779e28ec964baa2afdeb862be4b9776562866443cfcf22f37950c20ed0af2",
    }
    expected_entity = EntityTestFileComplex(
        filename="test-entity.sh",
        file="c3RhcnQxMjM=",
        checksum="2c4779e28ec964baa2afdeb862be4b9776562866443cfcf22f37950c20ed0af2",
    )
    e = K8S_LOADER.load(data, None, EntityTestFileComplex)
    s3_file_source.assert_called_once_with(
        "sdp",
        "entitytestfilecomplex-v18/2c4779e28ec964baa2afdeb862be4b9776562866443cfcf22f37950c20ed0af2",
    )
    assert expected_entity == e

    # Test 1: file field is not specified
    # The entity defines `x-checksum: checksum` so checksum field will be used to generate the url
    data = {"filename": "test-entity.sh", "file": "my-script.sh"}
    expected_entity = EntityTestFileComplex(
        filename="test-entity.sh",
        file="c3RhcnQxMjM=",
        checksum="2c4779e28ec964baa2afdeb862be4b9776562866443cfcf22f37950c20ed0af2",
    )
    s3_file_source.call_count = 0
    e = K8S_LOADER.load(data, None, EntityTestFileComplex)
    s3_file_source.assert_called_once_with(
        "sdp", "entitytestfilecomplex-v18/my-script.sh"
    )
    assert expected_entity == e


def test_load_s3_file_2():
    """
    We don't have defined any S3 server we should fail to load the entity
    """
    EntityTestFileComplex = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTestFileComplex"]
        .cls
    )
    data = {
        "filename": "test-entity.sh",
    }
    with pytest.raises(AppgateTypedloadException) as exc:
        _ = K8S_LOADER.load(data, None, EntityTestFileComplex)
    assert exc.value.platform_type == PlatformType.K8S
    assert exc.value.args == (
        "Unable to load field file for entity EntityTestFileComplex.\nPath: .",
    )
