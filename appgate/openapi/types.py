import datetime
import itertools
import re
from functools import cached_property
from typing import Any, Dict, List, Optional, FrozenSet, Callable, Set, \
    Union, Iterator, Tuple

from graphlib import TopologicalSorter

from attr import attrib, attrs, Attribute, evolve

from appgate.logger import log

SPEC_ENTITIES = {
    '/sites': 'Site',
    '/ip-pools': 'IpPool',
    '/local-users': 'LocalUser',
    '/appliance-customizations': 'ApplianceCustomization',
    '/admin-mfa-settings': 'AdminMfaSettings',
    '/ringfence-rules': 'RingfenceRule',
    '/mfa-providers': 'MfaProvider',
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
    '/trusted-certificates': 'TrustedCertificate',
}

K8S_APPGATE_DOMAIN = 'beta.appgate.com'
K8S_APPGATE_VERSION = 'v1'
ENTITY_METADATA_ATTRIB_NAME = '_entity_metadata'
APPGATE_METADATA_ATTRIB_NAME = 'appgate_metadata'
NAMES_REGEXP = re.compile(r'\w+(\.)\w+')
IGNORED_EQ_ATTRIBUTES = {'updated', 'created', 'id'}
AttribType = Union[int, bool, str, Callable[[], FrozenSet]]
OpenApiDict = Dict[str, Any]
AttributesDict = Dict[str, Any]
# Dictionary with the top level entities, those that are "exported"
EntitiesDict = Dict[str, 'GeneratedEntity']
APPGATE_LOADERS_FIELD_NAME = 'appgate_loader'
K8S_LOADERS_FIELD_NAME = 'k8s_loader'
PYTHON_TYPES = (str, bool, int, dict, tuple, frozenset, set, list,
                datetime.datetime)
UUID_REFERENCE_FIELD = 'x-uuid-ref'
APPGATE_METADATA_PASSWORD_FIELDS_FIELD = 'passwordFields'
APPGATE_METADATA_GENERATION_FIELD = 'generation'
APPGATE_METADATA_LATEST_GENERATION_FIELD = 'latestGeneration'
APPGATE_METADATA_MODIFICATION_FIELD = 'modificationTimestamp'
APPGATE_METADATA_CREATION_FIELD = 'creationTime'
APPGATE_METADATE_FIELDS = {
    APPGATE_METADATA_CREATION_FIELD,
    APPGATE_METADATA_MODIFICATION_FIELD,
    APPGATE_METADATA_GENERATION_FIELD,
    APPGATE_METADATA_LATEST_GENERATION_FIELD,
}


def normalize_attrib_name(name: str) -> str:
    if NAMES_REGEXP.match(name):
        return re.sub(r'\.', '_', name)
    return name


class OpenApiParserException(Exception):
    pass


@attrs(frozen=True, slots=True)
class AppgateMetadata:
    created: datetime.datetime = attrib(metadata={
        'name': 'creationTimestamp'
    }, default=datetime.datetime.now().astimezone())
    modified: datetime.datetime = attrib(metadata={
        'name': 'modificationTimestamp'
    }, default=datetime.datetime.now().astimezone())
    current_generation: int = attrib(default=1, metadata={
        'name': 'generation'
    })
    latest_generation: int = attrib(default=1, metadata={
        'name': 'latestGeneration'
    })
    api_version: str = attrib(metadata={
        'name': 'apiVersion'
    }, default=f'{K8S_APPGATE_DOMAIN}/{K8S_APPGATE_VERSION}')
    uuid: Optional[str] = attrib(default=None)
    passwords: Optional[Dict[str, Union[str, Dict[str, str]]]] = attrib(default=None)
    password_fields: Optional[List[str]] = attrib(default=None, metadata={
        'name': 'passwordFields'
    })

    def with_password_values(self, passwords: Dict[str, Union[str, Dict[str, str]]]) -> 'AppgateMetadata':
        return evolve(self, passwords=passwords)

    def with_password_fields(self, fields: List[str]) -> 'AppgateMetadata':
        return evolve(self, password_fields=fields)


@attrs()
class Entity_T:
    name: str = attrib()
    id: str = attrib()
    tags: FrozenSet[str] = attrib()
    __attrs_attrs__: List[Attribute] = attrib()
    appgate_metadata: AppgateMetadata = attrib()
    _entity_metadata: Dict[str, Any] = attrib()
    updated: datetime.datetime = attrib()


LoaderFunc = Callable[[Dict[str, Any], Optional[Dict[str, Any]], type], Entity_T]
DumperFunc = Callable[[Entity_T], Dict[str, Any]]


@attrs(frozen=True, slots=True)
class EntityDependency:
    field_path: str = attrib()
    dependencies: FrozenSet[str] = attrib()

    def __str__(self) -> str:
        return f'{{{self.field_path} :: {",".join(self.dependencies)}}}'

    @property
    def field(self) -> str:
        return self.field_path.split('.')[0]


def get_dependencies(cls: type, field_path: Optional[str] = None) -> Set[EntityDependency]:
    deps = set()
    attributes = getattr(cls, '__attrs_attrs__', [])
    for attribute in attributes:
        mt = getattr(attribute, 'metadata', None)
        attribute_name = (mt or {}).get('name')
        if attribute_name in {APPGATE_METADATA_ATTRIB_NAME, ENTITY_METADATA_ATTRIB_NAME}:
            continue
        if not mt or not attribute_name:
            continue
        updated_field_path: str = attribute_name
        if field_path:
            updated_field_path = f'{field_path}.{attribute_name}'
        base_type = mt['base_type']
        if base_type not in PYTHON_TYPES:
            _d = get_dependencies(base_type, updated_field_path)
            deps.update(_d)
        elif UUID_REFERENCE_FIELD in mt:
            deps.add(EntityDependency(field_path=updated_field_path,
                                      dependencies=frozenset([mt.get(UUID_REFERENCE_FIELD)])))
    return deps


@attrs()
class GeneratedEntity:
    """
    Class to represent an already parsed entity
    """
    cls: type = attrib()
    singleton: bool = attrib()
    api_path: Optional[str] = attrib(default=None)

    @cached_property
    def dependencies(self) -> Set[EntityDependency]:
        return get_dependencies(self.cls)

    @cached_property
    def entity_dependencies(self) -> Set[str]:
        return set(itertools.chain.from_iterable(map(lambda d: d.dependencies,
                                                 get_dependencies(self.cls))))


class EntitiesContext:
    data: Dict[str, Any]
    entities: Dict[str, GeneratedEntity]


@attrs()
class AttribMakerConfig:
    instance_maker_config: 'InstanceMakerConfig' = attrib()
    name: str = attrib()
    definition: OpenApiDict = attrib()

    def from_key(self, key: str) -> Optional['AttribMakerConfig']:
        definition = self.definition.get(key)
        if definition:
            return AttribMakerConfig(
                definition=definition,
                instance_maker_config=self.instance_maker_config,
                name=self.name)
        return None


@attrs()
class InstanceMakerConfig:
    name: str = attrib()
    entity_name: str = attrib()
    definition: OpenApiDict = attrib()
    level: int = attrib()
    singleton: bool = attrib()
    api_path: Optional[str] = attrib()

    @property
    def properties_names(self) -> Iterator[Tuple[str, str]]:
        return map(lambda n: (n, normalize_attrib_name(n)),
                   self.definition.get('properties', {}).keys())

    def attrib_maker_config(self, attribute: str) -> 'AttribMakerConfig':
        properties = self.definition.get('properties', {})
        definition = properties.get(attribute)
        x_name = definition.get('x-name')
        if not definition:
            log.error('Unable to find attribute %s in %s', attribute, ', '.join(properties.keys()))
            raise OpenApiParserException(f'Unable to find attribute %s')
        return AttribMakerConfig(
            instance_maker_config=self,
            name=normalize_attrib_name(x_name or attribute),
            definition=definition
        )


@attrs()
class APISpec:
    entities: EntitiesDict = attrib()
    api_version: int = attrib()

    @property
    def entities_sorted(self) -> List[str]:
        entities_to_sort: Dict[str, Set[str]] = {
            entity_name: entity.entity_dependencies
            for entity_name, entity in self.entities.items()
            if entity.api_path is not None
        }
        log.debug('Entities to sort %s', entities_to_sort)
        ts = TopologicalSorter(entities_to_sort)
        return list(ts.static_order())

    @property
    def api_entities(self) -> EntitiesDict:
        return {k: v for k, v in self.entities.items() if v.api_path is not None}
