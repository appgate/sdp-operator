from pathlib import Path

from attr import attrib, attrs
from typing import Dict, Any, Union
from typedload import load

__all__ = [
    'K8SEvent',
    'EventObject',
    'Entitlement',
    'Policy',
    'Condition',
    'AppgateEvent',
    'AppgateEntity',
    'DOMAIN',
    'RESOURCE_VERSION'
]

from appgate.openapi import Entity_T, parse_files

DOMAIN = 'beta.appgate.com'
RESOURCE_VERSION = 'v1'


class EventObject:
    def __init__(self, data: Dict[str, Any]) -> None:
        self.kind = data['kind']
        self.api_version = data['apiVersion']
        self.metadata = data['metadata']
        self.spec = data['spec']


class K8SEvent:
    def __init__(self, data: Dict[str, Any]) -> None:
        self.type = data['type']
        self.object = EventObject(data['object'])


SPEC_FILES = [
    Path('api_specs/identity_provider.yml'),
    Path('api_specs/entitlement.yml'),
    Path('api_specs/policy.yml'),
    Path('api_specs/condition.yml')
]
cls = parse_files(SPEC_FILES)

Entitlement = cls['Entitlement']


def entitlement_load(data: Dict[str, Any]) -> Entitlement:
    return load(data, Entitlement)


Policy = cls['Policy']


def policy_load(data: Dict[str, Any]) -> Policy:
    return load(data, Policy)


Condition = cls['Condition']


def condition_load(data: Dict[str, Any]) -> Condition:
    return load(data, Condition)


AppgateEntity = Union[Entitlement, Policy, Condition]


@attrs(slots=True, frozen=True)
class AppgateEvent:
    op: str = attrib()
    entity: AppgateEntity = attrib()
