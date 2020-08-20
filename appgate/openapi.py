import itertools
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, FrozenSet, Tuple, Callable, Set, \
    Union, Type, cast
from graphlib import TopologicalSorter

from attr import make_class, attrib, attrs
import yaml

from appgate.logger import log


__all__ = [
    'Entity_T',
    'parse_files',
    'APISpec',
    'K8S_APPGATE_DOMAIN',
    'K8S_APPGATE_VERSION',
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


TYPES_MAP: Dict[str, Type] = {
    'string': str,
    'boolean': bool,
    'integer': int,
    'number': int,
}


AttribType = Union[int, bool, str, Callable[[], FrozenSet]]


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
    cls: type = attrib()
    entity_dependencies: Set[EntityDependency] = attrib(factory=list)
    api_path: Optional[str] = attrib(default=None)


OpenApiDict = Dict[str, Any]
AttributesDict = Dict[str, Any]
BasicOpenApiType = Union[str, int, bool]
AnyOpenApiType = Union[BasicOpenApiType, Dict[str, BasicOpenApiType], List[BasicOpenApiType]]

# Dictionary with the top level entities, those that are "exported"
EntitiesDict = Dict[str, GeneratedEntity]


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
                     '.'.join(new_keys), self.namespace)
            resolved_ref = self.get_keys(new_keys)
        else:
            log.info('Resolving reference %s in %s namespace', '.'.join(new_keys), path)
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
                #log.debug('Trying %s in [%s]', '.'.join(keys),
                #          ', '.join(data.keys()))
                k = keys.pop(0)
            except IndexError:
                log.debug('Keys not found %s', '.'.join(keys_cp))
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

    def make_type(self, entity_name: str, attrib_name: str,
                  type_data: OpenApiDict) -> Tuple[Type,
                                                   Optional[AttribType],
                                                   Optional[Callable[[], Type]]]:
        tpe = type_data.get('type')
        if not type:
            raise Exception('type field not found in %s', type_data)
        if tpe in TYPES_MAP:
            log.debug('Creating new attribute %s.%s :: %s', entity_name, attrib_name,
                      TYPES_MAP[tpe])
            return TYPES_MAP[tpe], DEFAULT_MAP.get(tpe), None
        elif is_array(type_data):
            # Recursion here, we parse the items as a type
            array_tpe, _, _ = self.make_type(attrib_name, attrib_name, type_data['items'])
            log.debug('Creating new attribute %s.%s: FrozenSet[%s]', entity_name, attrib_name,
                      array_tpe)
            return FrozenSet[array_tpe], None, frozenset  # type: ignore
        elif is_object(type_data):
            # Indirect recursion here.
            # Those classes are never registered
            name = f'{entity_name.capitalize()}_{attrib_name.capitalize()}'
            attribs, _ = self.make_attribs(name, type_data, top_level_entry=False)
            generated_entity = self.register_entity(name, attribs=attribs, dependencies=set())
            log.debug('Created new attribute %s.%s of type %s', entity_name, attrib_name,
                      generated_entity.cls)
            return generated_entity.cls, None, None
        elif is_compound(type_data):
            name = f'{entity_name.capitalize()}_{attrib_name.capitalize()}'
            definition = self.parse_all_of(type_data['allOf'])
            attribs, dependencies = self.make_attribs(entity_name, definition,
                                                      top_level_entry=False)
            generated_entity = self.register_entity(name, attribs=attribs, dependencies=set())
            log.debug('Created new attribute %s.%s of type %s', entity_name, attrib_name,
                      generated_entity.cls)
            return generated_entity.cls, None, None
        raise Exception(f'Unknown type for attribute %s.%s: %s', entity_name, attrib_name,
                        type_data)

    def make_attrib(self, entity_name: str, attrib_name: str,
                    attrib_props: AttributesDict, required_fields: List[str],
                    top_level_entity: bool = False) -> AttributesDict:
        """
        Returns an attribs dictionary used later to call attrs.attrib
        """
        required = attrib_name in required_fields
        tpe, default, factory = self.make_type(entity_name, attrib_name, attrib_props)
        attribs: AttributesDict = {
            'type': tpe if required else Optional[tpe],
        }
        if top_level_entity and attrib_name == 'id':
            attribs['factory'] = lambda: str(uuid.uuid4())
        elif factory:
            attribs['factory'] = factory
        elif not required:
            attribs['default'] = attrib_props.get('default', default)

        attribs['metadata'] = {
            'type': str(tpe) if required else str(Optional[tpe]),
            'name': attrib_name
        }
        if 'description' in attrib_props:
            attribs['metadata']['description'] = attrib_props['description']
        if 'example' in attrib_props:
            if isinstance(attrib_props['example'], List):
                attribs['metadata']['example'] = frozenset(attrib_props['example'])
            else:
                attribs['metadata']['example'] = attrib_props['example']
        if 'x-appgate-entity' in attrib_props:
            attribs['metadata']['x-appgate-entity'] = attrib_props['x-appgate-entity']
        if attrib_name in IGNORED_EQ_ATTRIBUTES:
            attribs['eq'] = False

        return attribs

    def make_attribs(self, entity_name: str, definition,
                     top_level_entry: bool) -> Tuple[Dict[str, Any],
                                                             Set[EntityDependency]]:
        """
        Returns the attr.attrib data needed to use attr.make_class with the
        dependencies for this attribute.
        TODO: Return a list of EntityDependencies instead of a Dict
        """
        entity_attrs = {}
        entity_attrs_attrib = {}
        dependencies: Set[EntityDependency] = set()
        required_fields = definition.get('required', [])
        properties = definition['properties']
        for attrib_name, attrib_props in properties.items():
            norm_name = normalize_attrib_name(attrib_name)
            if 'readOnly' in attrib_props:
                log.debug('Ignoring read only attribute %s', attrib_name)
                continue
            entity_attrs[norm_name] = self.make_attrib(entity_name,
                                                       attrib_name,
                                                       attrib_props,
                                                       required_fields,
                                                       top_level_entry)

        # We need to create then in order. Those with default values at the end
        for attrib_name, attrib_attrs in {k: v for k, v in entity_attrs.items()
                                          if not has_default(v)}.items():
            entity_attrs_attrib[attrib_name] = attrib(**attrib_attrs)
            if 'x-appgate-entity' in attrib_attrs['metadata']:
                dependency = attrib_attrs['metadata']['x-appgate-entity']
                dependencies.add(EntityDependency(field=attrib_name,
                                                  dependencies=frozenset(dependency)))
        for attrib_name, attrib_attrs in {k: v for k, v in entity_attrs.items()
                                          if has_default(v)}.items():
            entity_attrs_attrib[attrib_name] = attrib(**attrib_attrs)
            if 'x-appgate-entity' in attrib_attrs['metadata']:
                dependency = attrib_attrs['metadata']['x-appgate-entity']
                dependencies.add(EntityDependency(field=attrib_name,
                                                  dependencies=frozenset(dependency)))
        return entity_attrs_attrib, dependencies

    def register_entity(self, entity_name: str, attribs: Dict[str, Any],
                        dependencies: Set[EntityDependency]) -> GeneratedEntity:
        entity_path = self.parser_context.get_entity_path(entity_name)
        cls = make_class(entity_name, attribs, slots=True, frozen=True)
        generated_entity = GeneratedEntity(cls=cls,
                                           entity_dependencies=dependencies,
                                           api_path=entity_path)
        self.parser_context.register_entity(entity_name=entity_name,
                                            entity=generated_entity)
        return generated_entity

    def parse_definition(self, keys: List[List[str]],
                         entity_name: str) -> Optional[GeneratedEntity]:
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
        if is_compound(definition):
            definition = self.parse_all_of(cast(dict, definition)['allOf'])
            attribs, dependencies = self.make_attribs(entity_name, definition,
                                                      top_level_entry=True)
            generated_entity = self.register_entity(entity_name=entity_name,
                                                    attribs=attribs,
                                                    dependencies=dependencies)
            return generated_entity
        log.error('Definition %s yet not supported', definition)

        return None

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


def has_default(entry: Any) -> bool:
    """
    Checks if attrs as a default field value
    """
    return isinstance(entry, dict) \
           and ('default' in entry or 'factory' in entry)


def normalize_attrib_name(name: str) -> str:
    if NAMES_REGEXP.match(name):
        return re.sub(r'\.', '_', name)
    return name


def parse_files(spec_entities: Dict[str, str],
                spec_directory: Optional[Path] = None) -> APISpec:
    parser_context = ParserContext(spec_entities=spec_entities,
                                   spec_api_path=spec_directory \
                                                 or Path(SPEC_DIR))
    parser = Parser(parser_context, 'api_specs.yml')
    # First parse those paths we are interested in
    for path, v in parser.data['paths'].items():
        if not parser_context.get_entity_name(path):
            continue
        entity_name = spec_entities[path]
        log.info('Generating entity %s for path %s', entity_name, path)
        keys = ['requestBody', 'content', 'application/json', 'schema']
        parser.parse_definition(entity_name=entity_name,
                                keys=[
                                    ['paths', path] + ['post'] + keys,
                                    ['paths', path] + ['put'] + keys
                                ])

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


def entity_names(entity: type) -> Tuple[str, str, str]:
    name = entity.__name__
    singular_name = name.lower()
    if singular_name.endswith('y'):
        plural_name = f'{singular_name[:-1]}ies'
    else:
        plural_name = f'{singular_name}s'
    return name, singular_name, plural_name


def generate_crd(entity) -> str:
    name, singular_name, plural_name = entity_names(entity)
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
                    name[0:3].lower()
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
