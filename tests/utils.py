from pathlib import Path
from typing import List, Optional, Callable

from cryptography.fernet import Fernet

from appgate.client import AppgateClient
from appgate.logger import set_level
from appgate.openapi.openapi import parse_files, generate_api_spec

KEY = '9K5-LO9yhyWNtHzjd__rYfPuJqrF58yApxtvHXGxefk='
ENCRYPTED_PASSWORD = 'gAAAAABfTgED7qYN_pr9dJjwMPhM9j3kp69B8SNJwwL4Rj5DpWVR8u0KG5kAzgx2yU-rVPW0AiWHL3cgXlGwz1tpepafJdM-ZA=='
FERNET_CIPHER = Fernet(KEY.encode())

api_spec = generate_api_spec(secrets_key=KEY)
entities = api_spec.entities

Policy = entities['Policy'].cls
Entitlement = entities['Entitlement'].cls
Condition = entities['Condition'].cls
IdentityProvider = entities['IdentityProvider'].cls
TestOpenAPI = None
TestSpec = {
    '/entity-test1': 'EntityTest1',
    '/entity-test2': 'EntityTest2',
    '/entity-test2-without-password': 'EntityTest2WihoutPassword',
    '/entity-test3': 'EntityTest3',
    '/entity-test3-appgate': 'EntityTest3Appgate',
    '/entity-test4': 'EntityTest4',
    '/entity-test-with-id': 'EntityTestWithId',
    '/entity-dep-1': 'EntityDep1',
    '/entity-dep-2': 'EntityDep2',
    '/entity-dep-3': 'EntityDep3',
    '/entity-dep-4': 'EntityDep4',
    '/entity-dep-5': 'EntityDep5',
    '/entity-dep-6': 'EntityDep6',
    '/entity-cert': 'EntityCert',
}
PEM_TEST = '''-----BEGIN CERTIFICATE-----
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
-----END CERTIFICATE-----'''

CERTIFICATE_FIELD = '''
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
'''

PUBKEY_FIELD = '''
LS0tLS1CRUdJTiBQVUJMSUMgS0VZLS0tLS0KTUZ3d0RRWUpLb1pJa
HZjTkFRRUJCUUFEU3dBd1NBSkJBSnY4WnBCNWhFSzdxeFA5SzN2ND
NoVVM1ZkdUNHdhSwplN2l4NFo0bXU1VUJ2K2N3N1dTRkF0MFZhYWc
wc0Fic1B6VThIaHNyai9xUEFCdmZCOGFzVXdjQ0F3RUFBUT09Ci0t
LS0tRU5EIFBVQkxJQyBLRVktLS0tLQo='''

ISSUER = '''1.2.840.113549.1.9.1=support@frank4dd.com,CN=Frank4DD Web CA,
OU=WebCert Support,O=Frank4DD,L=Chuo-ku,ST=Tokyo,C=JP'''

SUBJECT = 'CN=www.example.com,O=Frank4DD,ST=Tokyo,C=JP'


def join_string(s):
    return ''.join(s.splitlines())


def load_test_open_api_spec(secrets_key: Optional[str] = KEY,
                            k8s_get_secret: Callable[[str, str], str] = lambda x: ENCRYPTED_PASSWORD,
                            reload: bool = False):
    global TestOpenAPI
    set_level(log_level='debug')
    if not TestOpenAPI or reload:
        TestOpenAPI = parse_files(spec_entities=TestSpec,
                                  spec_directory=Path('tests/resources/'),
                                  spec_file='test_entity.yaml',
                                  secrets_key=secrets_key,
                                  k8s_get_secret=k8s_get_secret)
    return TestOpenAPI


def entitlement(name: str, id: str = None, site: str = 'site-example',
                conditions: Optional[List[str]] = None) -> Entitlement:
    return Entitlement(id=id,
                       name=name,
                       site=site,
                       conditions=frozenset(conditions) if conditions else frozenset())


def condition(name: str, id: str = None, expression: Optional[str] = None) -> Condition:
    return Condition(id=id,
                     name=name,
                     expression=expression or 'expression-test')


def policy(name: str, id: str = None, entitlements: Optional[List[str]] = None) -> Policy:
    return Policy(name=name,
                  id=id,
                  entitlements=frozenset(entitlements) if entitlements else frozenset(),
                  expression='expression-test')


class MockedClient(AppgateClient):
    pass
