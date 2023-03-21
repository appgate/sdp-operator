from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Callable, Dict, Union
from unittest.mock import patch

import urllib3
from cryptography.fernet import Fernet
from requests import Response

from appgate.client import AppgateClient
from appgate.logger import set_level
from appgate.openapi.openapi import parse_files, generate_api_spec
from appgate.openapi.types import APISpec, EntitiesDict

KEY = "9K5-LO9yhyWNtHzjd__rYfPuJqrF58yApxtvHXGxefk="
ENCRYPTED_PASSWORD = "gAAAAABfTgED7qYN_pr9dJjwMPhM9j3kp69B8SNJwwL4Rj5DpWVR8u0KG5kAzgx2yU-rVPW0AiWHL3cgXlGwz1tpepafJdM-ZA=="
FERNET_CIPHER = Fernet(KEY.encode())


_api_spec = None


def api_spec() -> APISpec:
    global _api_spec
    if not _api_spec:
        _api_spec = generate_api_spec(secrets_key=KEY)
    return _api_spec


def entities() -> EntitiesDict:
    return api_spec().entities


TestOpenAPI = None
TestSpec = {
    "/entity-test0": "EntityTest0",
    "/entity-test1": "EntityTest1",
    "/entity-test2": "EntityTest2",
    "/entity-test2-without-password": "EntityTest2WihoutPassword",
    "/entity-test3": "EntityTest3",
    "/entity-test3-appgate": "EntityTest3Appgate",
    "/entity-test4": "EntityTest4",
    "/entity-test-with-id": "EntityTestWithId",
    "/entity-test-file": "EntityTestFile",
    "/entity-test-file-complex": "EntityTestFileComplex",
    "/entity-test-secret": "EntityTestSecret",
    "/entity-test-secret-nested": "EntityTestSecretNested",
    "/entity-dep-1": "EntityDep1",
    "/entity-dep-2": "EntityDep2",
    "/entity-dep-3": "EntityDep3",
    "/entity-dep-4": "EntityDep4",
    "/entity-dep-5": "EntityDep5",
    "/entity-dep-6": "EntityDep6",
    "/entity-cert": "EntityCert",
    "/entity-dep-nested": "EntityDepNested7",
    "/entity-dep-nested-nullable": "EntityDepNestedNullable",
    "/entity-discriminator": "EntityDiscriminator",
    "/entity-array": "EntityArray",
}
PEM_TEST = """-----BEGIN CERTIFICATE-----
MIICEjCCAXsCAg36MA0GCSqGSIb3DQEBBQUAMIGbMQswCQYDVQQGEwJKUDEOMAwG
A1UECBMFVG9reW8xEDAOBgNVBAcTB0NodW8ta3UxETAPBgNVBAoTCEZyYW5rNERE
MRgwFgYDVQQLEw9XZWJDZXJ0IFN1cHBvcnQxGDAWBgNVBAMTD0ZyYW5rNEREIFdl
YiBDQTEjMCEGCSqGSIb3DQEJARYUc3VwcG9ydEBmcmFuazRkZC5jb20wHhcNMTIw
ODIyMDUyNjU0WhcNMTcwODIxMDUyNjU0WjBKMQswCQYDVQQGEwJKUDEOMAwGA1UE
CAwFVG9reW8xETAPBgNVBAoMCEZyYW5rNEREMRgwFgYDVQQDDA93d3cuZXhhbXBs
ZS5jb20wXDANBgkqhkiG9w0BAQEFAANLADBIAkEAm/xmkHmEQrurE/0re/jeFRLl
8ZPjBop7uLHhnia7lQG/5zDtZIUC3RVpqDSwBuw/NTweGyuP+o8AG98HxqxTBwID
AQABMA0GCSqGSIb3DQEBBQUAA4GBABS2TLuBeTPmcaTaUW/LCB2NYOy8GMdzR1mx
8iBIu2H6/E2tiY3RIevV2OW61qY2/XRQg7YPxx3ffeUugX9F4J/iPnnu1zAxxyBy
2VguKv4SWjRFoRkIfIlHX0qVviMhSlNy2ioFLy7JcPZb+v3ftDGywUqcBiVDoea0
Hn+GmxZA
-----END CERTIFICATE-----"""

CERTIFICATE_FIELD = """
LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUNFakNDQVhz
Q0FnMzZNQTBHQ1NxR1NJYjNEUUVCQlFVQU1JR2JNUXN3Q1FZRFZR
UUdFd0pLVURFT01Bd0cKQTFVRUNCTUZWRzlyZVc4eEVEQU9CZ05W
QkFjVEIwTm9kVzh0YTNVeEVUQVBCZ05WQkFvVENFWnlZVzVyTkVS
RQpNUmd3RmdZRFZRUUxFdzlYWldKRFpYSjBJRk4xY0hCdmNuUXhH
REFXQmdOVkJBTVREMFp5WVc1ck5FUkVJRmRsCllpQkRRVEVqTUNF
R0NTcUdTSWIzRFFFSkFSWVVjM1Z3Y0c5eWRFQm1jbUZ1YXpSa1pD
NWpiMjB3SGhjTk1USXcKT0RJeU1EVXlOalUwV2hjTk1UY3dPREl4
TURVeU5qVTBXakJLTVFzd0NRWURWUVFHRXdKS1VERU9NQXdHQTFV
RQpDQXdGVkc5cmVXOHhFVEFQQmdOVkJBb01DRVp5WVc1ck5FUkVN
Umd3RmdZRFZRUUREQTkzZDNjdVpYaGhiWEJzClpTNWpiMjB3WERB
TkJna3Foa2lHOXcwQkFRRUZBQU5MQURCSUFrRUFtL3hta0htRVFy
dXJFLzByZS9qZUZSTGwKOFpQakJvcDd1TEhobmlhN2xRRy81ekR0
WklVQzNSVnBxRFN3QnV3L05Ud2VHeXVQK284QUc5OEh4cXhUQndJ
RApBUUFCTUEwR0NTcUdTSWIzRFFFQkJRVUFBNEdCQUJTMlRMdUJl
VFBtY2FUYVVXL0xDQjJOWU95OEdNZHpSMW14CjhpQkl1Mkg2L0Uy
dGlZM1JJZXZWMk9XNjFxWTIvWFJRZzdZUHh4M2ZmZVV1Z1g5RjRK
L2lQbm51MXpBeHh5QnkKMlZndUt2NFNXalJGb1JrSWZJbEhYMHFW
dmlNaFNsTnkyaW9GTHk3SmNQWmIrdjNmdERHeXdVcWNCaVZEb2Vh
MApIbitHbXhaQQotLS0tLUVORCBDRVJUSUZJQ0FURS0tLS0tCg==
"""

PUBKEY_FIELD = """MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBAJv8ZpB5hEK7qxP9
K3v43hUS5fGT4waKe7ix4Z4mu5UBv+cw7WSFAt0Vaag0sAbsPzU8Hhsrj/qPABvfB8
asUwcCAwEAAQ==
"""

ISSUER = """1.2.840.113549.1.9.1=support@frank4dd.com, CN=Frank4DD Web CA,
 OU=WebCert Support, O=Frank4DD, L=Chuo-ku, ST=Tokyo, C=JP"""

SUBJECT = "CN=www.example.com, O=Frank4DD, ST=Tokyo, C=JP"

FINGERPRINT = "5f0fb5166581aae64a101c1583b1bebe74e814a91e7a8a14ba1e835d78f6e9e7"


def join_string(s):
    return "".join(s.splitlines())


def load_test_open_api_spec(
    secrets_key: Optional[str] = KEY,
    k8s_get_secret: Callable[[str, str], str] = lambda x, y: ENCRYPTED_PASSWORD,
    reload: bool = False,
):
    global TestOpenAPI
    set_level(log_level="debug")
    if not TestOpenAPI or reload:
        TestOpenAPI = parse_files(
            spec_entities=TestSpec,
            spec_directory=Path(__file__).parent / "resources",
            spec_file="test_entity.yaml",
            secrets_key=secrets_key,
            k8s_get_secret=k8s_get_secret,
            operator_mode="appgate-operator",
        )
    return TestOpenAPI


class MockedClient(AppgateClient):
    pass


def _k8s_get_secret(name: str, key: str) -> str:
    k8s_secrets = {"secret-storage-1": {"field-one": "1234567890-from-k8s"}}
    if name in k8s_secrets and key in k8s_secrets[name]:
        return k8s_secrets[name][key]
    raise Exception(f"Unable to get secret: {name}.{key}")


@contextmanager
def new_file_source(
    contents: Optional[Dict[str, bytes]] = None,
    default: Optional[bytes] = None,
    tpe: str = "HTTP",
):
    def _response(v: str) -> Union[Response, urllib3.response.HTTPResponse]:
        data = (contents or {}).get(v) or default
        if tpe == "HTTP":
            mock_response = Response()
            if data:
                mock_response._content = data
                mock_response.status_code = 200
            else:
                raise Exception(f"No data for {v}")
            return mock_response
        elif tpe == "S3":
            if data:
                mock_response2 = urllib3.response.HTTPResponse(body=data)
            else:
                raise Exception(f"No data for {v}")
            return mock_response2
        raise Exception("Unknown file source type to mock")

    if tpe == "HTTP":
        with patch("appgate.files.requests.get") as get:
            get.side_effect = _response
            yield get
    elif tpe == "S3":
        with patch("appgate.files.Minio.bucket_exists") as bucket_exists, patch(
            "appgate.files.Minio.get_object"
        ) as get_object:
            bucket_exists.return_value = True
            get_object.side_effect = lambda a, b: _response(f"{a}/{b}")
            yield get_object
