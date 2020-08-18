import itertools
from pathlib import Path
from graphlib import TopologicalSorter

from typing import Dict, Any
from attr import attrib, attrs

from appgate.client import AppgateClient, EntityClient
from appgate.openapi import parse_files, Entity_T, GeneratedEntities

__all__ = [
    'K8SEvent',
    'EventObject',
    'AppgateEvent',
    'generated_entities',
    'generate_entity_clients',
]


_generated_entities = None
_api_version = None
_entities_sorted = None


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
    Path('api_specs/administrative_role.yml'),
    Path('api_specs/device_script.yml'),
    Path('api_specs/client_connections.yml'),
    Path('api_specs/global_settings.yml'),
    Path('api_specs/appliance.yml'),
    Path('api_specs/criteria_script.yml'),
    Path('api_specs/entitlement_script.yml'),
    Path('api_specs/entitlement.yml'),
    Path('api_specs/policy.yml'),
    Path('api_specs/condition.yml')
]


def generated_entities() -> GeneratedEntities:
    global _generated_entities
    if not _generated_entities:
        _generated_entities = parse_files(SPEC_FILES)
    return _generated_entities


def generate_entity_clients(client: AppgateClient) -> Dict[str, EntityClient]:
    return {
        n: client.entity_client(e.cls, e.api_path)
        for n, e in generated_entities().entities.items()
        if e.api_path
    }


@attrs(slots=True, frozen=True)
class AppgateEvent:
    op: str = attrib()
    entity: Entity_T = attrib()
