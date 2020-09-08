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
TestOpenAPIWithSecrets = None
TestSpec = {
    '/entity-test1': 'EntityTest1',
    '/entity-test2': 'EntityTest2',
    '/entity-test3': 'EntityTest3',
    '/entity-test4': 'EntityTest4',
    '/entity-test-with-id': 'EntityTestWithId',
}


def load_test_open_api_spec(secrets_key: Optional[str] = KEY,
                            k8s_get_secret: Callable[[str, str], str] = lambda x: ENCRYPTED_PASSWORD,
                            reload: bool = False):
    global TestOpenAPI
    set_level(log_level='debug')
    if not TestOpenAPI or reload:
        open_api_spec = parse_files(spec_entities=TestSpec,
                                    spec_directory=Path('tests/resources/'),
                                    spec_file='test_entity.yaml',
                                    secrets_key=secrets_key,
                                    k8s_get_secret=k8s_get_secret)
        TestOpenAPI = open_api_spec.entities
    return TestOpenAPI


def load_test_open_api_compare_secrets_spec(secrets_key: str = KEY,
                                            k8s_get_secret: Callable[[str, str], str] = lambda x: ENCRYPTED_PASSWORD,
                                            reload: bool = False):
    global TestOpenAPIWithSecrets
    set_level(log_level='debug')
    if not TestOpenAPIWithSecrets or reload:
        open_api_spec = parse_files(spec_entities=TestSpec,
                                    spec_directory=Path('tests/resources/'),
                                    spec_file='test_entity.yaml',
                                    compare_secrets=True,
                                    secrets_key=secrets_key,
                                    k8s_get_secret=k8s_get_secret)
        TestOpenAPIWithSecrets = open_api_spec.entities
    return TestOpenAPIWithSecrets


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