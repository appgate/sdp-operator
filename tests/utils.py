from pathlib import Path
from typing import List, Optional

from appgate.logger import set_level
from appgate.openapi import parse_files
from appgate.types import generate_api_spec

api_spec = generate_api_spec()
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
}


def load_test_open_api_spec():
    global TestOpenAPI
    set_level(log_level='debug')
    if not TestOpenAPI:
        open_api_spec = parse_files(spec_entities=TestSpec,
                                    spec_directory=Path('tests/resources/'),
                                    spec_file='test_entity.yaml')
        TestOpenAPI = open_api_spec.entities
    return TestOpenAPI


def load_test_open_api_compare_secrets_spec():
    global TestOpenAPIWithSecrets
    set_level(log_level='debug')
    if not TestOpenAPIWithSecrets:
        open_api_spec = parse_files(spec_entities=TestSpec,
                                    spec_directory=Path('tests/resources/'),
                                    spec_file='test_entity.yaml',
                                    compare_secrets=True)
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
