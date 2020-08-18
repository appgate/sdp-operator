import itertools
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, FrozenSet, Tuple, Callable, get_origin, Set, Union
from graphlib import TopologicalSorter

from attr import make_class, attrib, attrs
import yaml

from appgate.logger import log


__all__ = [
    'Entity_T',
    'parse_files',
    'parse',
    'K8S_APPGATE_DOMAIN',
    'K8S_APPGATE_VERSION',
    'generate_crd',
    'entity_names',
    'is_entity_t',
    'has_id',
    'has_name'
]


SPEC_DIR = 'api_specs'
VERSION_SPEC_FILE = Path(SPEC_DIR) / 'api_specs.yml'
IGNORED_EQ_ATTRIBUTES = {'updated', 'created', 'id'}
K8S_API_VERSION = 'apiextensions.k8s.io/v1beta1'
K8S_CRD_KIND = 'CustomResourceDefinition'
K8S_APPGATE_DOMAIN = 'beta.appgate.com'
K8S_APPGATE_VERSION = 'v1'
TYPES_MAP = {
    'string': str,
    'boolean': bool,
    'integer': int,
    'number': int,
}
DEFAULT_MAP = {
    'string': '',
    'array': frozenset,
}
NAMES_REGEXP = re.compile(r'\w+(\.)\w+')


@attrs()
class Entity_T:
    name: str = attrib()
    id: int = attrib()
    tags: FrozenSet[str] = attrib()


@attrs()
class EntityDependency:
    field: str = attrib()
    dependencies: Set[str] = attrib()


@attrs()
class GeneratedEntity:
    cls: type = attrib()
    level: int = attrib()
    entity_dependencies: List[EntityDependency] = attrib(factory=list)
    api_path: Optional[str] = attrib(default=None)


# Dictionary with the top level entities, those that are "exported"
EntitiesDict = Dict[str, GeneratedEntity]


# Dictionary with all the entities discovered while parsing.
# Used internally
_EntitiesDict = Dict[str, Union[EntitiesDict, type]]


@attrs()
class GeneratedEntities:
    entities: EntitiesDict = attrib()
    api_version: int = attrib()

    @property
    def entities_sorted(self) -> List[str]:
        entities_to_sort = {
            entity_name: set(itertools.chain.from_iterable(map(lambda d: d.dependencies,
                                                               entity.entity_dependencies)))
            for entity_name, entity in self.entities.items()
            if entity.level == 0 and entity.api_path is not None
        }
        ts = TopologicalSorter(entities_to_sort)
        return list(ts.static_order())


def has_name(e: Any) -> bool:
    return hasattr(e, 'name')


def has_id(e: Any) -> bool:
    return hasattr(e, 'id')


def is_entity_t(e: Any) -> bool:
    return has_name(e) and has_id(e)


def get_keys(data: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    """
    gets key0.key1... entry in `data`
    """
    while True:
        try:
            k = keys.pop(0)
        except IndexError:
            return None
        # Is the key there?
        if k in data:
            # No more entries, return the value
            if not keys:
                return data[k]
            # more entries and we dont have a dict, fail
            elif type(data[k]) is not dict:
                return None
            else:
                # iterate
                data = data[k]
        else:
            # key not found
            return None


def is_ref(entry: Dict[str, Any]) -> bool:
    """
    Checks if entry is a reference
    """
    return '$ref' in entry


def is_object(entry: Dict[str, Any]) -> bool:
    """
    Checks if entry is an object
    """
    return 'type' in entry and entry['type'] == 'object'


def is_array(entry: Dict[str, Any]) -> bool:
    """
    Checks if entry is an array
    """
    return 'type' in entry and entry['type'] == 'array'


def is_rest_api(entry: Dict[str, Any]) -> bool:
    """
    Checks ig entry is an rest api
    """
    methods = {'post', 'get', 'put', 'delete'}
    return any(filter(lambda m: m in entry, methods))


def is_post_rest_api(entry: Dict[str, Any]) -> bool:
    """
    Checks ig entry is an rest api
    """
    return is_rest_api(entry) and 'post' in entry


def is_compound(entry: Dict[str, Any]) -> bool:
    composite = {'allOf'}
    return any(filter(lambda c: c in entry, composite))


def type_is_attr(tpe: type) -> bool:
    return hasattr(tpe, '__attrs_attrs__')


def attrs_has_default(attrs) -> bool:
    """
    Checks if attrs as a default field value
    """
    return 'default' in attrs or 'factory' in attrs


def get_entry(entities: _EntitiesDict, entity: str, entry: List[str],
              spec_dir: Optional[Path] = None) -> Optional[Any]:
    """
    Resolves entity in entities, if it's not registered it tries to parse it
    from the specification in disk and saves it in entities.
    """
    p = (spec_dir or Path(SPEC_DIR)) / entity
    v = get_keys(entities, [p.name])
    if not v:
        log.debug('Reading entity from disk: %s', entity)
        with p.open('r') as f:
            entities[p.name] = yaml.safe_load(f.read())
    if entry:
        return get_keys(entities, [p.name] + entry)
    return v


def make_attrib(entities: _EntitiesDict, data: dict, entity_name: str, attrib_name: str,
                attrib_props: Dict[str, Any], required_fields: List[str],
                level: int) -> dict:
    """
    Returns an attribs dictionary used later to call attrs.attrib
    """
    required = attrib_name in required_fields
    tpe, default, factory = make_type(entities, data, entity_name, attrib_name, attrib_props, level)
    attribs = {
        'type': tpe if required else Optional[tpe],
    }
    if level == 0 and attrib_name == 'id':
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


def normalize_attrib_name(name: str) -> str:
    if NAMES_REGEXP.match(name):
        return re.sub(r'\.', '_', name)
    return name


def make_attribs(entities: _EntitiesDict, data: dict, entity_name: str, attributes,
                 level: int) -> Dict[str, int]:
    """
    Returns the attr.attrib data needed to use attr.make_class
    """
    entity_attrs = {}
    entity_attrs_attrib = {}
    dependencies = {}
    for s in attributes:
        required_fields = s.get('required', [])
        properties = s['properties']
        for attrib_name, attrib_props in properties.items():
            norm_name = normalize_attrib_name(attrib_name)
            if 'readOnly' in attrib_props:
                log.debug('Ignoring read only attribute %s', attrib_name)
                continue
            entity_attrs[norm_name] = make_attrib(entities, data, entity_name, attrib_name,
                                                  attrib_props, required_fields, level)

    # We need to create then in order. Those with default values at the end
    for attrib_name, attrib_attrs in {k: v for k, v in entity_attrs.items()
                                      if not attrs_has_default(v)}.items():
        entity_attrs_attrib[attrib_name] = attrib(**attrib_attrs)
        if 'x-appgate-entity' in attrib_attrs['metadata']:
            if not attrib_name in dependencies:
                dependencies[attrib_name] = set()
            dependencies[attrib_name].add(attrib_attrs['metadata']['x-appgate-entity'])
    for attrib_name, attrib_attrs in {k: v for k, v in entity_attrs.items()
                                      if attrs_has_default(v)}.items():
        entity_attrs_attrib[attrib_name] = attrib(**attrib_attrs)
        if 'x-appgate-entity' in attrib_attrs['metadata']:
            if not attrib_name in dependencies:
                dependencies[attrib_name] = set()
            dependencies[attrib_name].add(attrib_attrs['metadata']['x-appgate-entity'])
    return entity_attrs_attrib, dependencies


def make_type(entities: _EntitiesDict, data: dict, entity_name: str, attrib_name: str,
              type_data, level: int) -> Tuple[type, Optional[type],
                                              Optional[Callable[[], Any]]]:
    if is_ref(type_data):
        resolved_ref, name = resolve_ref(entities=entities, data=data, ref=type_data['$ref'],
                                         spec_dir=Path('api_specs)'))
        return parse_definition(entities, data, name, resolved_ref, level + 1, None)
    else:
        tpe = type_data['type']
        if tpe in TYPES_MAP:
            log.debug('Creating new attribute %s.%s :: %s', entity_name, attrib_name,
                      TYPES_MAP[tpe])
            return TYPES_MAP[tpe], DEFAULT_MAP.get(tpe), None
        elif is_array(type_data):
            # Recursion here, we parse the items as a type
            array_tpe, _, _ = make_type(entities, data, attrib_name, attrib_name, type_data['items'], level)
            log.debug('Creating new attribute %s.%s: FrozenSet[%s]', entity_name, attrib_name,
                      array_tpe)
            return FrozenSet[array_tpe], None, frozenset  # type: ignore
        elif is_object(type_data):
            # Indirect recursion here.
            # Those classes are never registered
            name = f'{entity_name}_{attrib_name.capitalize()}'
            entity_attribs, _ = make_attribs(entities, data, entity_name, [type_data], level + 1)
            generated_entity = register_entity(entities, name, entity_attribs,
                                               {}, level + 1, None)
            log.debug('Created new attribute %s.%s of type %s', entity_name, attrib_name,
                      generated_entity.cls)
            return generated_entity.cls, None, None
    raise Exception(f'Unknown type for attribute %s.%s: %s', entity_name, attrib_name,
                    type_data)


def resolve_ref(entities: _EntitiesDict, data: dict, ref: str, spec_dir: Path):
    p, k = ref.split('#', maxsplit=2)
    if not p:
        # Resolve in file (data)
        log.debug('Resolving reference: %s', k)
        resolved_ref = get_keys(data, [x for x in k.split('/') if x])
    else:
        log.debug('Resolving reference: %s: %s', p, k)
        resolved_ref = get_entry(entities=entities, entity=p, spec_dir=spec_dir,
                                 entry=[x for x in k.split('/') if x])
    return resolved_ref, [x for x in k.split('/') if x][-1]


def register_entity(entities: _EntitiesDict, entity_name: str, attrs: dict,
                    dependencies: Dict[str, Set[str]],
                    level: int, api_path: Optional[str],
                    bases: Optional[Tuple[type, ...]] = None) -> GeneratedEntity:
    log.info(f'Registering new class {entity_name}')
    if entity_name in entities['classes']:
        log.warning(f'Entity %s already registered, ignoring it', entity_name)
        return entities['classes'][entity_name]
    cls = make_class(entity_name, attrs, bases=bases or tuple(), slots=True, frozen=True)
    deps = [EntityDependency(field=f,
                             dependencies=xs)
            for f, xs in dependencies.items()]
    generated_entity = GeneratedEntity(cls=cls,
                                       entity_dependencies=deps,
                                       api_path=api_path,
                                       level=level)
    entities['classes'][entity_name] = generated_entity
    return generated_entity


def parse_all_of(entities: _EntitiesDict, data: Dict[str, Any], entity_name: str,
                 all_of: List[Dict[str, Any]], level: int,
                 api_path: Optional[str]) -> Tuple[type, Optional[type],
                                                   Optional[Callable[[], Any]]]:
    attributes = []
    for s in all_of:
        if is_ref(s):
            attrs, n = resolve_ref(entities=entities, data=data, ref=s['$ref'],
                                   spec_dir=Path('api_specs'))
            attributes.append(attrs)
        elif is_object(s):
            attributes.append(s)
        elif is_array(s):
            attributes.append(s['items'])
    attrs, dependencies = make_attribs(entities, data, entity_name, attributes, level)
    return register_entity(entities, entity_name, attrs, dependencies, level, api_path).cls, None, None


def parse_definition(entities: _EntitiesDict, data: Dict[str, Any], name: str,
                     definition: Dict[str, Any], level: int,
                     api_path: Optional[str]) -> Tuple[type, Optional[type],
                                                       Optional[Callable[[], Any]]]:
    if is_compound(definition):
        return parse_all_of(entities, data, name, get_keys(definition, ['allOf']), level,
                            api_path)
    elif is_array(definition):
        attrs, dependencies = make_attribs(entities, data, name, [definition['items']], level)
        generated_entity = register_entity(entities, name, attrs, dependencies,
                                          level, api_path)
        return FrozenSet[generated_entity.cls], None, frozenset
    elif is_object(definition):
        attrs, dependencies = make_attribs(entities, data, name, [definition], level)
        generated_entity = register_entity(entities, name, attrs, dependencies,
                                           level, api_path)
        return generated_entity.cls, None, None


def parse_definitions(entities: _EntitiesDict, data: Dict[str, Any],
                      definitions: Dict[str, Any], level: int) -> None:
    for definition, value in definitions.items():
        log.debug('Parsing: %s', definition)
        if definition in entities['classes']:
            log.info('Definition already defined: %s, reusing it', definition)
        else:
            parse_definition(entities, data, definition, value, level, None)


def parse(data: Dict[str, Any], entities: Optional[_EntitiesDict] = None) -> None:
    if not entities:
        entities = {}
    if 'classes' not in entities:
        entities['classes'] = {}
    if 'dependencies' not in entities:
        entities['dependencies'] = {}

    # Parse API first
    for k, v in data.items():
        if not is_rest_api(v):
            continue
        # This is ugly, make it better
        # Bsically some times we have 2 references, we should make it generic.
        # v = get_keys(v, ['post', 'responses', 200]) or get_keys(v, ['put', 'responses', 200])
        v = get_keys(v, ['post', 'requestBody']) or get_keys(v, ['put', 'requestBody'])
        if v and is_ref(v):
            v, _ = resolve_ref(entities=entities, data=data, ref=v['$ref'],
                               spec_dir=Path('api_spec'))
        v = get_keys(v or {}, ['content', 'application/json', 'schema'])
        if v and is_ref(v):
            resolved_ref, name = resolve_ref(entities=entities, data=data, ref=v['$ref'],
                                             spec_dir=Path('api_spec'))
            parse_definition(entities, data, name, resolved_ref, 0, api_path=k)
    # Parse definitions
    parse_definitions(entities, data, get_keys(data, ['definitions']) or [], 0)


def parse_files(files: List[Path]) -> GeneratedEntities:
    entities = {
        'classes': {},
        'dependencies': {},
    }
    for f in files:
        with f.open('r') as f:
            parse(yaml.safe_load(f.read()), entities=entities)
    # validate dependencies
    errors = False
    for e, deps in entities['dependencies'].items():
        for _, ds in deps:
            for d in ds:
                if d not in entities['classes']:
                    log.error(f'Entity %s is a dependency for %s, but it was not registered.', d, e)
                    errors = True
    # Now parse the API version
    with VERSION_SPEC_FILE.open('r') as f:
        data = yaml.safe_load(f.read())
        # TODO: Check for errors :D
        api_version = data['info']['version'].split(' ')[2]
    if errors:
        raise Exception('Error validating yaml entities.')
    return GeneratedEntities(entities=entities['classes'],
                             api_version=api_version)


def entity_names(entity: type) -> Tuple[str, str, str]:
    name = entity.__name__
    singular_name = name.lower()
    if singular_name.endswith('y'):
        plural_name = f'{singular_name[:-1]}ies'
    else:
        plural_name = f'{singular_name}s'
    return name, singular_name, plural_name


def generate_crd(entity):
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
