from pathlib import Path

from attr import attrib, attrs
from typing import Dict, Any, Union
from typedload import load

from appgate.client import AppgateClient, EntityClient
from appgate.logger import set_level
from appgate.openapi import parse_files, Entity_T

set_level(log_level='debug')

__all__ = [
    'K8SEvent',
    'EventObject',
    'AppgateEvent',
    'generate_entities',
    'generate_entity_clients',
]


generated_entities = None


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


def generate_entities():
    print('aaa')
    global generated_entities
    if not generated_entities:
        generated_entities = parse_files(SPEC_FILES)
    return generated_entities


def generate_entity_clients(client: AppgateClient) -> Dict[str, EntityClient]:
    generated_entities = generate_entities()
    generated_clients = {}
    for name, entity_t in generated_entities.items():
        if entity_t[2]:
            generated_clients[name] = client.entity_client(entity_t[0], entity_t[2])
    return generated_clients


@attrs(slots=True, frozen=True)
class AppgateEvent:
    op: str = attrib()
    entity: Entity_T = attrib()
