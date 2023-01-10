import os
from unittest.mock import patch

import urllib3.response
from requests import Response

from appgate.attrs import K8S_LOADER
from tests.utils import load_test_open_api_spec


@patch.dict(os.environ, {"APPGATE_FILE_SOURCE": "http"})
@patch.dict(os.environ, {"APPGATE_FILE_HTTP_ADDRESS": "localhost:8000"})
@patch.dict(os.environ, {"APPGATE_API_VERSION": "v18"})
def test_load_http_file():
    EntityTestFile = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTestFile"]
        .cls
    )
    data = {"filename": "test-entity.sh"}
    expected_entity = EntityTestFile(filename="test-entity.sh", file="c3RhcnQxMjM=")

    with patch("appgate.files.requests.get") as get:
        mock_response = Response()
        mock_response._content = b"start123"
        mock_response.status_code = 200
        get.return_value = mock_response
        e = K8S_LOADER.load(data, None, EntityTestFile)

        get.assert_called_once_with("localhost:8000/entitytestfile-v18/test-entity.sh")
        assert expected_entity == e


@patch.dict(os.environ, {"APPGATE_FILE_SOURCE": "s3"})
@patch.dict(os.environ, {"APPGATE_API_VERSION": "v18"})
def test_load_s3_file():
    EntityTestFile = (
        load_test_open_api_spec(secrets_key=None, reload=True)
        .entities["EntityTestFile"]
        .cls
    )
    data = {"filename": "test-entity.sh"}
    expected_entity = EntityTestFile(filename="test-entity.sh", file="c3RhcnQxMjM=")

    with patch("appgate.files.Minio.bucket_exists") as bucket_exists:
        with patch("appgate.files.Minio.get_object") as get_object:
            bucket_exists.return_value = True
            get_object.return_value = urllib3.response.HTTPResponse(body=b"start123")
            e = K8S_LOADER.load(data, None, EntityTestFile)
            get_object.assert_called_once_with(
                "sdp", "entitytestfile-v18/test-entity.sh"
            )
            assert expected_entity == e
