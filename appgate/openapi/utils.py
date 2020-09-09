import os
from typing import Any, List, Dict, FrozenSet, Optional

from appgate.logger import log
from appgate.openapi.types import Entity_T, AttributesDict, PYTHON_TYPES

__all__ = [
    'builtin_tags',
    'is_ref',
    'is_array',
    'is_object',
    'is_entity_t',
    'is_compound',
    'has_id',
    'has_default',
    'is_builtin',
    'is_target',
    'has_name',
    'get_field',
    'get_passwords',
    'join',
    'make_explicit_references',
    'APPGATE_TARGET_TAGS_ENV',
    'APPGATE_BUILTIN_TAGS_ENV',
]


APPGATE_BUILTIN_TAGS_ENV = 'APPGATE_OPERATOR_BUILTIN_TAGS'
APPGATE_TARGET_TAGS_ENV = 'APPGATE_OPERATOR_TARGET_TAGS'
BUILTIN_TAGS = frozenset({'builtin'})


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


def builtin_tags() -> FrozenSet[str]:
    custom_tags = os.getenv(APPGATE_BUILTIN_TAGS_ENV, '')
    return BUILTIN_TAGS.union(frozenset(custom_tags.split(',')))


def is_builtin(entity: Entity_T) -> bool:
    return any(map(lambda t: t in (entity.tags or frozenset()), builtin_tags()))


def is_target(entity: Entity_T, tags: Optional[FrozenSet[str]] = None) -> bool:
    if not tags:
        return True
    return any(map(lambda t: t in (entity.tags or frozenset()), tags))


def _get_passwords(entity: Entity_T, names: List[str]) -> List[str]:
    fields = []
    prefix = '.'.join(names)
    for a in entity.__attrs_attrs__:
        mt = getattr(a, 'metadata')
        if mt and mt.get('format') == 'password':
            if prefix:
                fields.append(f'{prefix}.{a.name}')
            else:
                fields.append(a.name)
        base_type = mt.get('base_type', None)
        if base_type and base_type not in PYTHON_TYPES:
            fields.extend(_get_passwords(base_type, names + [a.name]))
    return fields


def get_passwords(entity: Entity_T) -> List[str]:
    return _get_passwords(entity, [])
