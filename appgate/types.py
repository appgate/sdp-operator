from pathlib import Path
from typing import Dict, Any, Optional
from attr import attrib, attrs

from appgate.client import AppgateClient, EntityClient
from appgate.openapi import parse_files, Entity_T, APISpec

__all__ = [
    'K8SEvent',
    'EventObject',
    'AppgateEvent',
    'generate_api_spec',
    'generate_api_spec_clients',
]


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


SPEC_ENTITIES = {
    '/identity-providers': 'IdentityProvider',
    '/administrative-roles': 'AdministrativeRole',
    '/device-scripts': 'DeviceScript',
    '/client-connections': 'ClientConnection',
    '/global-settings': 'GlobalSettings',
    '/appliances': 'Appliance',
    '/criteria-scripts': 'CriteriaScripts',
    '/entitlement-scripts': 'EntitlementScript',
    '/policies': 'Policy',
    '/conditions': 'Condition',
    '/entitlements': 'Entitlement',
}


def generate_api_spec(spec_directory: Optional[Path] = None,
                      compare_secrets: bool = False) -> APISpec:
    """
    Parses openapi yaml files and generates the ApiSpec.
    TODO: Choose the directory so we can support different versions.
    """
    return parse_files(SPEC_ENTITIES, spec_directory=spec_directory,
                       compare_secrets=compare_secrets)


def generate_api_spec_clients(api_spec: APISpec, dump_secrets: bool,
                              appgate_client: AppgateClient) -> Dict[str, EntityClient]:
    return {
        n: appgate_client.entity_client(e.cls, e.api_path, dump_secrets)
        for n, e in api_spec.entities.items()
        if e.api_path
    }


@attrs(slots=True, frozen=True)
class AppgateEvent:
    op: str = attrib()
    entity: Entity_T = attrib()
