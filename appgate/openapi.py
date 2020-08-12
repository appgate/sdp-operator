import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, FrozenSet, Tuple, Callable

from attr import make_class, attrib, attrs
import yaml

from appgate.logger import log


__all__ = [
    'Entity_T',
    'parse_files',
    'parse',
]


SPEC_DIR = 'api_specs'
IGNORED_ATTRIBUTES = {'updated', 'created'}
IGNORED_EQ_ATTRIBUTES = {'updated', 'created', 'id'}
K8S_API_VERSION = 'apiextensions.k8s.io/v1beta1'
K8S_CRD_KIND = 'CustomResourceDefinition'
K8S_APPGATE_DOMAIN = 'beta.appgate.com'
K8S_APPGATE_VERSION = 'v1'
TYPES_MAP = {
    'string': str,
    'boolean': bool,
    'integer': int,
}

DEFAULT_MAP = {
    'string': '',
    'array': frozenset,
}


@attrs()
class Entity_T:
    name: str = attrib()
    id: int = attrib()
    tags: FrozenSet[str] = attrib()


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


def is_compound(entry: Dict[str, Any]) -> bool:
    composite = {'allOf'}
    return any(filter(lambda c: c in entry, composite))


def tpe_is_attr(tpe: type) -> bool:
    return hasattr(tpe, '__attrs_attrs__')


def attrs_has_default(attrs) -> bool:
    """
    Checks if attrs as a default field value
    """
    return 'default' in attrs or 'factory' in attrs


def get_entry(entities: Dict[str, Any], entity: str, entry: List[str],
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


def make_attrib(entities: dict, data: dict, entity_name: str, attrib_name: str,
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
        'type': str(tpe) if required else str(Optional[tpe])
    }
    if 'description' in attrib_props:
        attribs['metadata']['description'] = attrib_props['description']
    if 'example' in attrib_props:
        if isinstance(attrib_props['example'], List):
            attribs['metadata']['example'] = frozenset(attrib_props['example'])
        else:
            attribs['metadata']['example'] = attrib_props['example']

    if attrib_name in IGNORED_EQ_ATTRIBUTES:
        attribs['eq'] = False

    return attribs


def make_attribs(entities: dict, data: dict, entity_name: str, attributes,
                 level: int) -> Dict[str, int]:
    """
    Returns the attr.attrib data needed to use attr.make_class
    """
    entity_attrs = {}
    entity_attrs_attrib = {}
    for s in attributes:
        required_fields = s.get('required', [])
        properties = s['properties']
        for attrib_name, attrib_props in properties.items():
            if attrib_name not in IGNORED_ATTRIBUTES:
                entity_attrs[attrib_name] = make_attrib(entities, data, entity_name, attrib_name,
                                                        attrib_props, required_fields, level)

    # We need to create then in order. Those with default values at the end
    for attrib_name, attrib_attrs in {k: v for k,v in entity_attrs.items()
                                      if not attrs_has_default(v)}.items():
        entity_attrs_attrib[attrib_name] = attrib(**attrib_attrs)
    for attrib_name, attrib_attrs in {k: v for k, v in entity_attrs.items()
                                      if attrs_has_default(v)}.items():
        entity_attrs_attrib[attrib_name] = attrib(**attrib_attrs)
    return entity_attrs_attrib


def make_type(entities: dict, data: dict, entity_name: str, attrib_name: str, type_data,
              level: int) -> Tuple[type, Optional[type], Optional[Callable[[], Any]]]:
    if is_ref(type_data):
        resolved_ref, name = resolve_ref(entities=entities, data=data, ref=type_data['$ref'],
                                         spec_dir=Path('api_specs)'))
        return parse_definition(entities, data, name, resolved_ref, level + 1)
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
            name = f'{entity_name}_{attrib_name.capitalize()}'
            entity_attribs = make_attribs(entities, data, entity_name, [type_data], level + 1)
            cls = make_class(name, entity_attribs, frozen=True, slots=True)
            log.debug('Creating new attribute %s.%s: %s', entity_name, attrib_name, cls)
            return cls, None, None
    raise Exception(f'Unknown type for attribute %s.%s: %s', entity_name, attrib_name,
                    type_data)


def resolve_ref(entities: dict, data: dict, ref: str, spec_dir: Path):
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


def parse_all_of(entities: dict, data: Dict[str, Any], entity_name: str,
                 all_of: List[Dict[str, Any]], level: int):
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
    attrs = make_attribs(entities, data, entity_name, attributes, level)

    log.info(f'Registering new class {entity_name}')
    if entity_name in entities['classes']:
        log.warning(f'Entity %s already registered, overwriting', entity_name)
    entities['classes'][entity_name] = make_class(entity_name, attrs, bases=(Entity_T,),
                                                  slots=True, frozen=True)
    return entities['classes'][entity_name], None, None


def parse_definition(entities: dict, data: Dict[str, Any], name: str,
                     definition: Dict[str, Any], level: int):
    if is_compound(definition):
        return parse_all_of(entities, data, name, get_keys(definition, ['allOf']), level)
    elif is_array(definition):
        attrs = make_attribs(entities, data, name, [definition['items']], level)
        print(attrs)
        log.info(f'Registering new class {name}')
        if name in entities['classes']:
            log.warning(f'Entity %s already registered, overwriting', name)
        entities['classes'][name] = make_class(name, attrs, slots=True, frozen=True)
        return FrozenSet[entities['classes'][name]], None, frozenset


def parse_definitions(entities: dict, data: Dict[str, Any],
                      definitions: Dict[str, Any], level: int):
    for definition, value in definitions.items():
        log.debug('Parsing: %s', definition)
        if definition in entities['classes']:
            log.info('Definition already defined: %s, reusing it', definition)
        else:
            parse_definition(entities, data, definition, value, level)


def parse(data: Dict[str, Any], entities: Optional[dict] = None):
    if not entities:
        entities = {}
    if not 'classes' in entities:
        entities['classes'] = {}

    for k, v in data.items():
        if k == 'definitions':
            parse_definitions(entities, data, get_keys(data, ['definitions']), 0)
        if is_rest_api(v):
            pass


def parse_files(files: List[Path]):
    entities = {
        'classes': {}
    }
    for f in files:
        with f.open('r') as f:
            parse(yaml.safe_load(f.read()), entities=entities)
    return entities['classes']


def generate_crd(entity):
    name = entity.__name__
    singular_name = name.lower()
    if singular_name.endswith('y'):
        plural_name = f'{singular_name[:-1]}ies'
    else:
        plural_name = f'{singular_name}s'
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