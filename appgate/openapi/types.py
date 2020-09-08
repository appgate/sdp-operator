import itertools
import re
from typing import Any, Dict, List, Optional, FrozenSet, Callable, Set, \
    Union, Iterator, Tuple

from graphlib import TopologicalSorter

from attr import attrib, attrs, Attribute

from appgate.logger import log

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


NAMES_REGEXP = re.compile(r'\w+(\.)\w+')
IGNORED_EQ_ATTRIBUTES = {'updated', 'created', 'id'}
AttribType = Union[int, bool, str, Callable[[], FrozenSet]]
OpenApiDict = Dict[str, Any]
AttributesDict = Dict[str, Any]
# Dictionary with the top level entities, those that are "exported"
EntitiesDict = Dict[str, 'GeneratedEntity']
APPGATE_LOADERS_FIELD_NAME = 'appgate_loader'
K8S_LOADERS_FIELD_NAME = 'k8s_loader'


def normalize_attrib_name(name: str) -> str:
    if NAMES_REGEXP.match(name):
        return re.sub(r'\.', '_', name)
    return name


class OpenApiParserException(Exception):
    pass


@attrs(frozen=True, slots=True)
class AppgateMetadata:
    uuid: Optional[str] = attrib(default=None)


@attrs()
class Entity_T:
    name: str = attrib()
    id: str = attrib()
    tags: FrozenSet[str] = attrib()
    __attrs_attrs__: List[Attribute] = attrib()


@attrs(frozen=True, slots=True)
class EntityDependency:
    field: str = attrib()
    dependencies: FrozenSet[str] = attrib()


@attrs()
class GeneratedEntity:
    """
    Class to represent an already parsed entity
    """
    cls: type = attrib()
    entity_dependencies: Set[EntityDependency] = attrib(factory=list)
    api_path: Optional[str] = attrib(default=None)


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
                instance_maker_config=self.instance_maker_config.with_name(self.name),
                name=self.name)
        return None


@attrs()
class InstanceMakerConfig:
    name: str = attrib()
    entity_name: str = attrib()
    definition: OpenApiDict = attrib()
    level: int = attrib()
    compare_secrets: bool = attrib()
    singleton: bool = attrib()
    api_path: Optional[str] = attrib()

    @property
    def properties_names(self) -> Iterator[Tuple[str, str]]:
        return map(lambda n: (n, normalize_attrib_name(n)),
                   self.definition.get('properties', {}).keys())

    def attrib_maker_config(self, attribute: str) -> 'AttribMakerConfig':
        properties = self.definition.get('properties', {})
        definition = properties.get(attribute)
        if not definition:
            log.error('Unable to find attribute %s in %s', attribute, ', '.join(properties.keys()))
            raise OpenApiParserException(f'Unable to find attribute %s')
        return AttribMakerConfig(
            instance_maker_config=self,
            name=normalize_attrib_name(attribute),
            definition=definition
        )

    def with_name(self, name: str) -> 'InstanceMakerConfig':
        return InstanceMakerConfig(
            name=name,
            entity_name=self.entity_name,
            definition=self.definition,  # This should be definition['name'],
            compare_secrets=self.compare_secrets,
            singleton=self.singleton,
            api_path=None,
            level=self.level + 1)


@attrs()
class APISpec:
    entities: EntitiesDict = attrib()
    api_version: int = attrib()

    @property
    def entities_sorted(self) -> List[str]:
        entities_to_sort: Dict[str, Set[str]] = {
            entity_name: set(itertools.chain.from_iterable(map(lambda d: d.dependencies,
                                                               entity.entity_dependencies)))
            for entity_name, entity in self.entities.items()
            if entity.api_path is not None
        }
        log.debug('Entities to sort %s', entities_to_sort)
        ts = TopologicalSorter(entities_to_sort)
        return list(ts.static_order())

    @property
    def api_entities(self) -> EntitiesDict:
        return {k: v for k, v in self.entities.items() if v.api_path is not None}
