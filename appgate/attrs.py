import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, FrozenSet, Tuple, Callable

from attr import make_class, attrib, attrs
import yaml

from appgate.logger import log


__all__ = [
    'Entity_T',
    'make_entity',
]


SPEC_DIR = 'api_specs'

IGNORED_ATTRIBUTES = {'updated', 'created'}
IGNORED_EQ_ATTRIBUTES = {'updated', 'created', 'id'}


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
    Checks ig entry is a reference
    """
    return '$ref' in entry


def is_object(entry: Dict[str, Any]) -> bool:
    """
    Checks ig entry is an object
    """
    return 'type' in entry and entry['type'] == 'object'


def is_array(entry: Dict[str, Any]) -> bool:
    """
    Checks ig entry is an array
    """
    return 'type' in entry and entry['type'] == 'array'


def get_entry(entities: Dict[str, Any], entity: str, entry: List[str],
              spec_dir: Optional[Path] = None) -> Any:
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


def make_attrib(entity_name: str, attrib_name: str, attrib_props: Dict[str, Any],
                required_fields: List[str], level: int) -> dict:
    """
    Returns an attribs dictionary used later to call attrs.attrib
    """
    log.debug(f'Creating attribute %s.%s', entity_name, attrib_name)
    required = attrib_name in required_fields
    tpe, default, factory = make_type(entity_name, attrib_name, attrib_props, level)
    attribs = {
        'type': tpe if required else Optional[tpe],
    }
    if level == 0 and attrib_name == 'id':
        attribs['factory'] = lambda: str(uuid.uuid4())
    elif factory:
        attribs['factory'] = factory
    elif not required:
        attribs['default'] = default

    if attrib_name in IGNORED_EQ_ATTRIBUTES:
        attribs['eq'] = False

    return attribs


def attrs_has_default(attrs) -> bool:
    """
    Checks if attrs as a default field value
    """
    return 'default' in attrs or 'factory' in attrs


def make_attribs(entity_name: str, attributes, level: int) -> Dict[str, int]:
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
                entity_attrs[attrib_name] = make_attrib(entity_name, attrib_name, attrib_props, required_fields, level)

    # We need to create then in order. Those with default values at the end
    for attrib_name, attrib_attrs in {k: v for k,v in entity_attrs.items()
                                      if not attrs_has_default(v)}.items():
        entity_attrs_attrib[attrib_name] = attrib(**attrib_attrs)
    for attrib_name, attrib_attrs in {k: v for k, v in entity_attrs.items()
                                      if attrs_has_default(v)}.items():
        entity_attrs_attrib[attrib_name] = attrib(**attrib_attrs)
    return entity_attrs_attrib


def make_type(entity_name: str, attrib_name: str, data,
              level: int) -> Tuple[type, Optional[type], Optional[Callable[[], Any]]]:
    tpe = data['type']
    if tpe in TYPES_MAP:
        return TYPES_MAP[tpe], DEFAULT_MAP.get(tpe), None
    elif is_array(data):
        # Recursion here, we parse the items as a type
        array_tpe, _, _ = make_type(attrib_name, attrib_name, data['items'], level)
        return FrozenSet[array_tpe], None, frozenset  # type: ignore
    elif is_object(data):
        # Indirect recursion here.
        name = f'{entity_name}_{attrib_name.capitalize()}'
        entity_attribs = make_attribs(entity_name, [data], level + 1)
        return make_class(name, entity_attribs, frozen=True, slots=True), None, None
    else:
        raise Exception(f'Unknown type: {tpe}')


def make_entity(entity: str, spec_dir: Optional[Path] = None) -> Type[Entity_T]:
    """
    Function that creates an entity class from a yaml specification
    """
    entity_yml = f'{entity}.yml'
    entity_name = entity.capitalize()
    scheme = get_entry(entities={}, entity=entity_yml, spec_dir=spec_dir,
                       entry=['definitions', entity_name, 'allOf'])
    data: dict = {}
    attributes = []
    for s in scheme:
        if is_ref(s):
            p, k = s['$ref'].split('#', maxsplit=2)
            log.debug('Resolving reference: %s: %s', p, k)
            resolved_ref = get_entry(entities=data, entity=p, spec_dir=spec_dir,
                                     entry=[x for x in k.split('/') if x])
            attributes.append(resolved_ref)
        elif is_object(s):
            attributes.append(s)
    attrs = make_attribs(entity_name, attributes, 0)
    return make_class(entity_name, attrs, bases=(Entity_T,), slots=True, frozen=True)
