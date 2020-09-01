import hashlib
import itertools
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, FrozenSet, Tuple, Callable, Set, \
    Union, Type, cast, Iterator
from graphlib import TopologicalSorter

from attr import make_class, attrib, attrs, evolve
import yaml

from appgate.logger import log


__all__ = [
    'Entity_T',
    'parse_files',
    'APISpec',
    'K8S_APPGATE_DOMAIN',
    'K8S_APPGATE_VERSION',
    'APPGATE_METADATA_ATTRIB_NAME',
    'OpenApiDict',
    'SimpleAttribMaker',
    'AttributesDict',
    'CustomAttribLoader',
    'CustomEntityLoader',
    'CustomLoader',
    'BUILTIN_TAGS',
    'SPEC_DIR',
    'generate_crd',
    'entity_names',
    'is_entity_t',
    'has_id',
    'has_name'
]


SPEC_DIR = 'api_specs/v12'
IGNORED_EQ_ATTRIBUTES = {'updated', 'created', 'id'}
K8S_API_VERSION = 'apiextensions.k8s.io/v1beta1'
K8S_CRD_KIND = 'CustomResourceDefinition'
K8S_APPGATE_DOMAIN = 'beta.appgate.com'
K8S_APPGATE_VERSION = 'v1'
LIST_PROPERTIES = {'range', 'data', 'query', 'orderBy', 'descending', 'filterBy'}
APPGATE_METADATA_ATTRIB_NAME = '_appgate_metadata'
BUILTIN_TAGS = frozenset({'builtin'})
TYPES_MAP: Dict[str, Type] = {
    'string': str,
    'boolean': bool,
    'integer': int,
    'number': int,
}
AttribType = Union[int, bool, str, Callable[[], FrozenSet]]
OpenApiDict = Dict[str, Any]
AttributesDict = Dict[str, Any]
BasicOpenApiType = Union[str, int, bool]
AnyOpenApiType = Union[BasicOpenApiType, Dict[str, BasicOpenApiType], List[BasicOpenApiType]]
# Dictionary with the top level entities, those that are "exported"
EntitiesDict = Dict[str, 'GeneratedEntity']
DEFAULT_MAP: Dict[str, AttribType] = {
    'string': '',
    'array': frozenset,
}
NAMES_REGEXP = re.compile(r'\w+(\.)\w+')


class OpenApiParserException(Exception):
    pass


@attrs()
class Entity_T:
    name: str = attrib()
    id: str = attrib()
    tags: FrozenSet[str] = attrib()


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
        ts = TopologicalSorter(entities_to_sort)
        return list(ts.static_order())


class ParserContext:
    def __init__(self, spec_entities: Dict[str, str], spec_api_path: Path) -> None:
        self.entities: Dict[str, GeneratedEntity] = {}
        self.data: OpenApiDict = {}
        self.spec_api_path: Path = spec_api_path
        self.entity_name_by_path: Dict[str, str] = spec_entities
        self.entity_path_by_name: Dict[str, str] = {v: k for k, v in spec_entities.items()}

    def get_entity_path(self, entity_name: str) -> Optional[str]:
        return self.entity_path_by_name.get(entity_name)

    def get_entity_name(self, entity_path: str) -> Optional[str]:
        return self.entity_name_by_path.get(entity_path)

    def register_entity(self, entity_name: str, entity: GeneratedEntity) -> GeneratedEntity:
        log.info(f'Registering new class {entity_name}')
        if entity_name in self.entities:
            log.warning(f'Entity %s already registered, ignoring it', entity_name)
        else:
            self.entities[entity_name] = entity
        return self.entities[entity_name]

    def load_namespace(self, namespace: str) -> Dict[str, Any]:
        path = self.spec_api_path / namespace
        if path.name in self.data:
            log.debug('Using cached namespace %s', path)
            return self.data[path.name]
        with path.open('r') as f:
            log.info('Loading namespace %s from disk', path)
            self.data[path.name] = yaml.safe_load(f.read())
        return self.data[path.name]


def has_default(definition: AttributesDict) -> bool:
    """
    Checks if attrs as a default field value
    """
    return 'factory' in definition or 'default' in definition


def has_name(e: Any) -> bool:
    return hasattr(e, 'name')


def has_id(e: Any) -> bool:
    return hasattr(e, 'id')


def is_entity_t(e: Any) -> bool:
    return has_name(e) and has_id(e)


def is_ref(entry: Any) -> bool:
    """
    Checks if entry is a reference
    """
    return isinstance(entry, dict) \
           and '$ref' in entry


def is_object(entry: Any) -> bool:
    """
    Checks if entry is an object
    """
    return isinstance(entry, dict) \
           and 'type' in entry \
           and entry['type'] == 'object'


def is_array(entry: Any) -> bool:
    """
    Checks if entry is an array
    """
    return isinstance(entry, dict) \
           and 'type' in entry \
           and entry['type'] == 'array'


def is_compound(entry: Any) -> bool:
    composite = {'allOf'}
    return isinstance(entry, dict) \
           and any(filter(lambda c: c in entry, composite))


def get_field(entity: Entity_T, field: str) -> Any:
    try:
        return getattr(entity, field)
    except AttributeError:
        raise Exception('Field %s not found in entity: %s', field,
                        entity)


class CustomLoader:
    pass


@attrs()
class CustomAttribLoader(CustomLoader):
    loader: Callable[[Any], Any] = attrib()
    field: str = attrib()

    def load(self, values: AttributesDict) -> AttributesDict:
        v = values[self.field]
        values[self.field] = self.loader(v)
        return values


@attrs()
class CustomEntityLoader(CustomLoader):
    loader: Callable[..., Any] = attrib()
    field: str = attrib()
    dependencies: List[str] = attrib(factory=list)

    def load(self, entity: Any) -> Any:
        deps = [get_field(entity, a.name) for a in entity.__attrs_attrs__
                if a.name in self.dependencies]
        if len(deps) != len(self.dependencies):
            # TODO: Return the attributes missing
            raise TypeError('Missing dependencies when loading entity')
        field_value = get_field(entity, self.field)
        new_value = self.loader(*([field_value] + deps))
        return evolve(entity, **{
            self.field: new_value
        })


class SimpleAttribMaker:
    def __init__(self, name: str, tpe: type, default: Optional[AttribType],
                 factory: Optional[type], definition: OpenApiDict) -> None:
        self.name = name
        self.tpe = tpe
        self.default = default
        self.factory = factory
        self.definition = definition

    @property
    def metadata(self) -> Dict[str, Any]:
        return self.definition.get('metadata', {})

    @property
    def has_default(self) -> bool:
        """
        Checks if attrs as a default field value
        """
        return self.factory is not None or self.default is not None

    def values(self, attributes: Dict[str, 'SimpleAttribMaker'], required_fields: List[str],
               instance_maker_config: 'InstanceMakerConfig') -> AttributesDict:
        required = self.name in required_fields
        definition = self.definition
        read_only = definition.get('readOnly', False)
        write_only = definition.get('writeOnly', False)
        format = definition.get('format')
        attribs: AttributesDict = {}
        attribs['metadata'] = {
            'name': self.name,
            'readOnly': read_only,
            'writeOnly': write_only,
            'format': format,
        }
        if 'description' in definition:
            attribs['metadata']['description'] = definition['description']
        if 'example' in definition:
            if isinstance(definition['example'], List):
                attribs['metadata']['example'] = frozenset(definition['example'])
            else:
                attribs['metadata']['example'] = definition['example']
        if 'x-appgate-entity' in definition:
            attribs['metadata']['x-appgate-entity'] = definition['x-appgate-entity']

        if self.name in IGNORED_EQ_ATTRIBUTES or write_only or read_only:
            attribs['eq'] = False

        # Set type
        if not required or read_only or write_only:
            attribs['type'] = Optional[self.tpe]
            attribs['metadata']['type'] = str(Optional[self.tpe])
        elif required and (read_only or write_only):
            raise OpenApiParserException(f'readOnly/writeOnly attribute {self.name} '
                                         'can not be required')
        else:
            attribs['type'] = self.tpe
            attribs['metadata']['type'] = str(self.tpe)

        if instance_maker_config.level == 0 and self.name == 'id':
            attribs['factory'] = lambda: str(uuid.uuid4())
        elif self.factory and not (read_only or write_only):
            attribs['factory'] = self.factory
        elif not required or read_only or write_only:
            attribs['default'] = definition.get('default',
                                                None if (read_only or write_only) else self.default)

        return attribs


class DeprecatedAttribMaker(SimpleAttribMaker):
    pass


class DefaultAttribMaker(SimpleAttribMaker):
    def values(self, attributes: Dict[str, 'SimpleAttribMaker'], required_fields: List[str],
               instance_maker_config: 'InstanceMakerConfig') -> AttributesDict:
        return {
            'type': self.tpe,
            'repr': False,
            'eq': False,
            'default': self.default
        }


def decrypt_password():
    key = 'not implemented'
    def _decrypt_password(value: str):
        return value

    return _decrypt_password


def checksum_bytes(value: Any, bytes: str) -> str:
    return hashlib.sha256(bytes.encode()).hexdigest()


class PasswordAttribMaker(SimpleAttribMaker):
    def values(self, attributes: Dict[str, 'SimpleAttribMaker'], required_fields: List[str],
               instance_maker_config: 'InstanceMakerConfig') -> AttributesDict:
        # Compare passwords if compare_secrets was enabled
        values = super().values(attributes, required_fields, instance_maker_config)
        values['eq'] = instance_maker_config.compare_secrets
        if 'metadata' not in values:
            values['metadata'] = {}
        values['metadata']['k8s_loader'] = CustomAttribLoader(
            loader=decrypt_password(),
            field=self.name,
        )
        return values


class ChecksumAttribMaker(SimpleAttribMaker):
    def __init__(self, name: str, tpe: type, default: Optional[AttribType],
                 factory: Optional[type], definition: OpenApiDict,
                 source_field: str) -> None:
        super().__init__(name, tpe, default, factory, definition)
        self.source_field = source_field

    def values(self, attributes: Dict[str, 'SimpleAttribMaker'], required_fields: List[str],
               instance_maker_config: 'InstanceMakerConfig',
               ) -> AttributesDict:
        # Compare passwords if compare_secrets was enabled
        values = super().values(attributes, required_fields, instance_maker_config)
        values['eq'] = True
        if 'metadata' not in values:
            values['metadata'] = {}
        values['metadata']['k8s_loader'] = CustomEntityLoader(
            loader=checksum_bytes,
            dependencies=[self.source_field],
            field=self.name,
        )
        return values


class ArrayAttribMaker(SimpleAttribMaker):
    pass


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


def normalize_attrib_name(name: str) -> str:
    if NAMES_REGEXP.match(name):
        return re.sub(r'\.', '_', name)
    return name


@attrs()
class InstanceMakerConfig:
    name: str = attrib()
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
            definition=self.definition,  # This should be definition['name'],
            compare_secrets=self.compare_secrets,
            singleton=self.singleton,
            api_path=None,
            level=self.level + 1)


class InstanceMaker:
    def __init__(self, name: str, attributes: Dict[str, SimpleAttribMaker]) -> None:
        self.name = name
        self.attributes = attributes

    @property
    def attributes_with_default(self) -> Dict[str, SimpleAttribMaker]:
        return {k: v for k, v in self.attributes.items() if v.has_default}

    @property
    def attributes_without_default(self) -> Dict[str, SimpleAttribMaker]:
        return {k: v for k, v in self.attributes.items() if not v.has_default}

    @property
    def dependencies(self) -> Set[EntityDependency]:
        dependencies: Set[EntityDependency] = set()
        for attrib_name, attrib_attrs in self.attributes.items():
            mt = attrib_attrs.metadata
            if 'x-appgate-entity' in mt:
                dependency = mt['x-appgate-entity']
                dependencies.add(EntityDependency(field=attrib_name,
                                                  dependencies=frozenset(dependency)))

        return dependencies

    def make_instance(self, instance_maker_config: InstanceMakerConfig) -> GeneratedEntity:
        # Add attributes if needed after instance level
        if 'name' not in self.attributes and instance_maker_config.singleton:
            self.attributes['name'] = create_default_attrib(self.name, self.name)
        if 'id' not in self.attributes and instance_maker_config.singleton:
            self.attributes['id'] = create_default_attrib(self.name, self.name)
        if 'tags' not in self.attributes and instance_maker_config.singleton:
            self.attributes['tags'] = create_default_attrib('tags', BUILTIN_TAGS)

        # Get values from attrib makers
        values = dict(
            map(lambda kv: (kv[0], kv[1].values(self.attributes,
                                                instance_maker_config.definition.get('required', {}),
                                                instance_maker_config)),
                filter(lambda kv: not isinstance(kv[1], DeprecatedAttribMaker),
                       self.attributes.items())))
        # Add custom entity loaders if needed
        k8s_custom_entity_loaders = []
        appgate_custom_entity_loaders = []
        for n, v in values.items():
            if 'metadata' not in v:
                continue
            k8s_loader = v['metadata'].get('k8s_loader')
            appgate_loader = v['metadata'].get('appgate_loader')
            if k8s_loader and isinstance(k8s_loader, CustomEntityLoader):
                k8s_custom_entity_loaders.append(k8s_loader)
            if appgate_loader and isinstance(appgate_loader, CustomEntityLoader):
                appgate_custom_entity_loaders.append(k8s_loader)
        metadata_default_attrib = create_default_attrib(
            APPGATE_METADATA_ATTRIB_NAME,
            {
                'singleton': instance_maker_config.singleton,
                'k8s_loader': k8s_custom_entity_loaders or None,
                'appgate_loader': appgate_custom_entity_loaders or None,
            })
        # Build the dictionary of attribs
        attrs = {}
        # First attributes with no default values
        for k, v in filter(lambda p: not has_default(p[1]), values.items()):
            attrs[k] = attrib(**v)
        # Now attributes with default values
        for k, v in filter(lambda p: has_default(p[1]), values.items()):
            attrs[k] = attrib(**v)
        attrs[APPGATE_METADATA_ATTRIB_NAME] = attrib(**metadata_default_attrib.values(
            self.attributes,
            instance_maker_config.definition.get('required', {}),
            instance_maker_config))
        cls = make_class(self.name, attrs, slots=True, frozen=True)
        return GeneratedEntity(cls=cls,
                               entity_dependencies=self.dependencies,
                               api_path=instance_maker_config.api_path)


def make_explicit_references(definition: Dict[str, Any], namespace: str) -> Dict[str, Any]:
    if is_compound(definition):
        return {'allOf': [make_explicit_references(d, namespace) for d in definition['allOf']]}
    elif type(definition) is not dict:
        return definition
    elif is_ref(definition):
        path, ref = definition['$ref'].split('#', maxsplit=2)
        if not path:
            explicit_reference = f'{namespace}#{ref}'
            log.debug('Making reference to %s explicit as %s', ref, explicit_reference)
            return {'$ref': explicit_reference}
        else:
            return definition
    for k, v in definition.items():
        if is_ref(v):
            path, ref = v['$ref'].split('#', maxsplit=2)
            if not path:
                explicit_reference = f'{namespace}#{ref}'
                log.debug('Making reference to %s explicit as %s', ref, explicit_reference)
                definition[k] = {'$ref': explicit_reference}
        else:
            definition[k] = make_explicit_references(v, namespace)
    return definition


def join(sep: str, xs: List[Any]) -> str:
    return sep.join(map(str, xs))


def create_default_attrib(name: str, attrib_value: Any) -> DefaultAttribMaker:
    return DefaultAttribMaker(
        tpe=type(attrib_value),
        name=name,
        default=attrib_value,
        factory=None,
        definition={})


class Parser:
    def __init__(self, parser_context: ParserContext, namespace: str) -> None:
        self.namespace = namespace
        self.parser_context = parser_context
        self.data: Dict[str, Any] = parser_context.load_namespace(namespace)

    def resolve_reference(self, reference: str, keys: List[str]) -> Dict[str, Any]:
        path, ref = reference.split('#', maxsplit=2)
        new_keys = [x for x in ref.split('/') if x] + keys
        if not path:
            # Resolve in current namespace
            # Resolve in current namespace
            log.info('Resolving reference %s in current namespace: %s',
                     join('.', new_keys), self.namespace)
            resolved_ref = self.get_keys(new_keys)
        else:
            log.info('Resolving reference %s in %s namespace', join('.', new_keys), path)
            resolved_ref = Parser(self.parser_context, namespace=path).get_keys(new_keys)
        if not resolved_ref:
            raise OpenApiParserException(f'Unable to resolve reference {reference}')
        return resolved_ref

    def get_keys(self, keys: List[str]) -> Optional[Any]:
        keys_cp = keys.copy()
        data = self.data
        while True:
            try:
                # TODO: This should be TRACE level or something
                # log.debug('Trying %s in [%s]', join('.', keys),
                #          join(', ', data.keys()))
                k = keys.pop(0)
            except IndexError:
                log.debug('Keys not found %s', join('.', keys_cp))
                return None
            # Is the key there?
            if k in data:
                value = data[k]
                # this is a reference, solve it
                if '$ref' in value:
                    data = self.resolve_reference(value['$ref'], keys)
                    # If the resolution succeed that means it should have consumed
                    # all the keys
                    keys = []
                    value = data
                # More keys but we don't have a dict, fail
                elif keys and type(value) is not dict:
                    return None
                else:
                    # iterate
                    data = value

                # No more entries, return the value
                if not keys:
                    return make_explicit_references(value, self.namespace)
            else:
                # key not found
                log.debug('Key %s not found in [%s]', k, ', '.join(data.keys()))
                return None

    def resolve_definition(self, definition: OpenApiDict) -> OpenApiDict:
        if type(definition) is not dict:
            return definition
        for k, v in definition.items():
            if is_ref(v):
                resolved = self.resolve_reference(v['$ref'], [])
                resolved = self.resolve_definition(resolved)
                definition[k] = resolved
            else:
                definition[k] = self.resolve_definition(v)
        return definition

    def parse_all_of(self, definitions: List[OpenApiDict]) -> OpenApiDict:
        for i, d in enumerate(definitions):
            definitions[i] = self.resolve_definition({'to-resolve': d})['to-resolve']
        new_definition: OpenApiDict = {
            'type': 'object',
            'required': [],
            'properties': {},
            'discriminator': {},
            'description': ''
        }
        descriptions = []
        for d in definitions:
            new_definition['required'].extend(d.get('required', {}))
            new_definition['properties'].update(d.get('properties', {}))
            new_definition['discriminator'].update(d.get('discriminator', {}))
            if 'description' in d:
                descriptions.append(d['description'])
        new_definition['description'] = '.'.join(descriptions)
        return new_definition

    def make_type(self, attrib_maker_config: AttribMakerConfig) -> SimpleAttribMaker:
        definition = attrib_maker_config.definition
        entity_name = attrib_maker_config.instance_maker_config.name
        attrib_name = attrib_maker_config.name
        tpe = definition.get('type')
        if is_compound(definition):
            definition = self.parse_all_of(definition['allOf'])
            instance_maker_config = InstanceMakerConfig(
                name=f'{entity_name.capitalize()}_{attrib_name.capitalize()}',
                definition=definition,
                compare_secrets=attrib_maker_config.instance_maker_config.compare_secrets,
                singleton=attrib_maker_config.instance_maker_config.singleton,
                api_path=attrib_maker_config.instance_maker_config.api_path,
                level=attrib_maker_config.instance_maker_config.level+1)
            generated_entity = self.register_entity(instance_maker_config=instance_maker_config)
            log.debug('Created new attribute %s.%s of type %s', entity_name, attrib_name,
                      generated_entity.cls)
            return SimpleAttribMaker(name=instance_maker_config.name,
                                     tpe=generated_entity.cls,
                                     default=None,
                                     factory=None,
                                     definition=attrib_maker_config.definition)
        elif not tpe:
            raise Exception('type field not found in %s', definition)
        elif tpe in TYPES_MAP:
            log.debug('Creating new attribute %s.%s :: %s', entity_name, attrib_name,
                      TYPES_MAP[tpe])
            format = definition.get('format', None)
            if format == 'password':
                return PasswordAttribMaker(name=attrib_name,
                                           tpe=TYPES_MAP[tpe],
                                           default=DEFAULT_MAP.get(tpe),
                                           factory=None,
                                           definition=attrib_maker_config.definition)
            elif isinstance(format, dict) and 'type' in format and format['type'] == 'checksum':
                return ChecksumAttribMaker(name=attrib_name,
                                           tpe=TYPES_MAP[tpe],
                                           default=DEFAULT_MAP.get(tpe),
                                           factory=None,
                                           definition=attrib_maker_config.definition,
                                           source_field=format['source'])
            else:
                return SimpleAttribMaker(name=attrib_name,
                                         tpe=TYPES_MAP[tpe],
                                         default=DEFAULT_MAP.get(tpe),
                                         factory=None,
                                         definition=attrib_maker_config.definition)
        elif is_array(definition):
            # Recursion here, we parse the items as a type
            new_attrib_maker_config = attrib_maker_config.from_key('items')
            if not new_attrib_maker_config:
                raise OpenApiParserException('Unable to get items from array defintion.')
            attr_maker = self.make_type(new_attrib_maker_config)
            log.debug('Creating new attribute %s.%s: FrozenSet[%s]', entity_name, attrib_name,
                      attr_maker.tpe)
            return SimpleAttribMaker(name=attr_maker.name,
                                     tpe=FrozenSet[attr_maker.tpe],  # type: ignore
                                     default=None,
                                     factory=frozenset,
                                     definition=new_attrib_maker_config.definition)
        elif is_object(definition):
            # Indirect recursion here.
            # Those classes are never registered
            instance_maker_config = InstanceMakerConfig(
                name=f'{entity_name.capitalize()}_{attrib_name.capitalize()}',
                definition=definition,
                compare_secrets=attrib_maker_config.instance_maker_config.compare_secrets,
                singleton=attrib_maker_config.instance_maker_config.singleton,
                api_path=attrib_maker_config.instance_maker_config.api_path,
                level=attrib_maker_config.instance_maker_config.level + 1)
            generated_entity = self.register_entity(instance_maker_config=instance_maker_config)
            log.debug('Created new attribute %s.%s of type %s', entity_name, attrib_name,
                      generated_entity.cls)
            return SimpleAttribMaker(name=instance_maker_config.name,
                                     tpe=generated_entity.cls,
                                     default=None,
                                     factory=None,
                                     definition=instance_maker_config.definition)
        raise Exception(f'Unknown type for attribute %s.%s: %s', entity_name, attrib_name,
                        definition)

    def attrib_maker(self, attrib_maker_config: AttribMakerConfig) -> SimpleAttribMaker:
        """
        Returns an attribs dictionary used later to call attrs.attrib
        """
        definition = attrib_maker_config.definition
        deprecated = definition.get('deprecated', False)
        attrib = self.make_type(attrib_maker_config)
        if deprecated:
            return DeprecatedAttribMaker(
                name=attrib.name,
                definition=attrib.definition,
                default=attrib.default,
                factory=attrib.factory,
                tpe=attrib.tpe)
        return attrib

    def instance_maker(self, instance_maker_config: InstanceMakerConfig) -> InstanceMaker:
        return InstanceMaker(
            name=instance_maker_config.name,
            attributes={
                nn: self.attrib_maker(instance_maker_config.attrib_maker_config(n))
                for n, nn in instance_maker_config.properties_names
            })

    def register_entity(self, instance_maker_config: InstanceMakerConfig) -> GeneratedEntity:
        instance_maker = self.instance_maker(instance_maker_config)
        generated_entity = instance_maker.make_instance(instance_maker_config)
        self.parser_context.register_entity(entity_name=instance_maker.name,
                                            entity=generated_entity)
        return generated_entity

    def parse_definition(self, keys: List[List[str]], entity_name: str,
                         singleton: bool, compare_secrets: bool) -> Optional[GeneratedEntity]:
        while True:
            errors: List[str] = []
            try:
                k: List[str] = keys.pop()
                definition = self.get_keys(k)
                break
            except OpenApiParserException as e:
                errors.append(str(e))
            except IndexError:
                raise OpenApiParserException(', '.join(errors))

        definition_to_use = None
        if is_compound(definition):
            definition_to_use = self.parse_all_of(cast(dict, definition)['allOf'])
        elif is_object(definition):
            definition_to_use = definition

        if not definition_to_use:
            log.error('Definition %s yet not supported', definition)
            return None
        api_path = self.parser_context.get_entity_path(entity_name)
        instance_maker_config = InstanceMakerConfig(name=entity_name,
                                                    definition=definition_to_use,
                                                    compare_secrets=compare_secrets,
                                                    singleton=singleton,
                                                    api_path=api_path,
                                                    level=0)
        generated_entity = self.register_entity(instance_maker_config=instance_maker_config)
        return generated_entity


def parse_files(spec_entities: Dict[str, str],
                spec_directory: Optional[Path] = None,
                spec_file: str = 'api_specs.yml',
                compare_secrets: bool = False) -> APISpec:
    parser_context = ParserContext(spec_entities=spec_entities,
                                   spec_api_path=spec_directory \
                                                 or Path(SPEC_DIR))
    parser = Parser(parser_context, spec_file)
    # First parse those paths we are interested in
    for path, v in parser.data['paths'].items():
        if not parser_context.get_entity_name(path):
            continue
        entity_name = spec_entities[path]
        log.info('Generating entity %s for path %s', entity_name, path)
        keys = ['requestBody', 'content', 'application/json', 'schema']
        # Check if path returns a singleton or a list of entities
        get_schema = parser.get_keys(keys=['paths', path, 'get', 'responses', '200',
                                           'content', 'application/json', 'schema'])
        if isinstance(get_schema, dict) and is_compound(get_schema):
            # TODO: when data.items is a compound method the references are not resolved.
            parsed_schema = parser.parse_all_of(get_schema['allOf'])
        elif isinstance(get_schema, dict):
            parsed_schema = get_schema
        else:
            parsed_schema = {}
        singleton = not all(map(lambda f: f in parsed_schema.get('properties', {}),
                                LIST_PROPERTIES))
        parser.parse_definition(entity_name=entity_name,
                                keys=[
                                     ['paths', path] + ['post'] + keys,
                                     ['paths', path] + ['put'] + keys
                                 ],
                                singleton=singleton,
                                compare_secrets=compare_secrets)

    # Now parse the API version
    api_version_str = parser.get_keys(['info', 'version'])
    if not api_version_str:
        raise OpenApiParserException('Unable to find Appgate API version')
    try:
        api_version = api_version_str.split(' ')[2]
    except IndexError:
        raise OpenApiParserException('Unable to find Appgate API version')
    return APISpec(entities=parser_context.entities,
                   api_version=api_version)


def entity_names(entity: type, short_names: Dict[str, str]) -> Tuple[str, str, str, str]:
    name = entity.__name__
    short_name = name[0:3].lower()
    if short_name in short_names:
        a = name
        b = short_names[short_name]
        rest = []
        for i in range(2):
            # Another CRD has the same short name
            rest = a.split(b)
            if len(rest) == 1:
                a = short_names[short_name]
                b = name
        if len(rest) < 1:
            raise OpenApiParserException('Unable to generate short name for entity %s', name)
        short_name = rest[1].lower()[0:3]
    short_names[short_name] = name
    singular_name = name.lower()
    if singular_name.endswith('y'):
        plural_name = f'{singular_name[:-1]}ies'
    else:
        plural_name = f'{singular_name}s'
    return name, singular_name, plural_name, short_name


def generate_crd(entity: Type, short_names: Dict[str, str]) -> str:
    name, singular_name, plural_name, short_name = entity_names(entity, short_names)
    crd = {
        'apiVersion': K8S_API_VERSION,
        'kind': K8S_CRD_KIND,
        'metadata': {
            'name': f'{plural_name}.{K8S_APPGATE_DOMAIN}',
        },
        'spec': {
            'group': K8S_APPGATE_DOMAIN,
            'versions': [{
                'name': K8S_APPGATE_VERSION,
                'served': True,
                'storage': True
            }],
            'scope': 'Namespaced',
            'names': {
                'singular': singular_name,
                'plural': plural_name,
                'kind': name,
                'shortNames': [
                    short_name
                ]
            }
        }
    }
    """
    TODO: Iterate over all attributes here to generate the spec
    for a in entity.__attrs_attrs__:
        spec = a.metadata['spec']
        str[a.name] = spec()
    """
    return yaml.safe_dump(crd)
