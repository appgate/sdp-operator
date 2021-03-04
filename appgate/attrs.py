import datetime
import enum
from typing import Dict, Any, List, Callable, Optional, Iterable, Union, Type

from typedload import dataloader
from typedload import datadumper
from typedload.exceptions import TypedloadException, TypedloadValueError

from appgate.customloaders import CustomFieldsEntityLoader, CustomLoader, CustomAttribLoader, \
    CustomEntityLoader
from appgate.openapi.types import Entity_T, ENTITY_METADATA_ATTRIB_NAME, APPGATE_METADATA_ATTRIB_NAME, \
    APPGATE_METADATE_FIELDS, APPGATE_LOADERS_FIELD_NAME, K8S_LOADERS_FIELD_NAME, EntityLoader, \
    EntityDumper, AppgateException

__all__ = [
    'K8S_DUMPER',
    'APPGATE_DUMPER',
    'K8S_LOADER',
    'APPGATE_LOADER',
    'DIFF_DUMPER',
    'get_loader',
    'get_dumper',
    'dump_datetime',
    'parse_datetime',
]


class PlatformType(enum.Enum):
    K8S = 1
    APPGATE = 2
    DIFF = 3


def _attrdump(d, value) -> Dict[str, Any]:
    r = {}
    for attr in value.__attrs_attrs__:
        attrval = getattr(value, attr.name)
        if not attr.repr:
            continue
        if 'readOnly' in attr.metadata:
            continue
        if not (d.hidedefault and attrval == attr.default):
            name = attr.metadata.get('name', attr.name)
            r[name] = d.dump(attrval)
    return r


def is_datetime_loader(type_: Type[Any]) -> bool:
    name = getattr(type_, '__name__', None)
    return name and name == 'datetime'


def is_datetime_dumper(value: Any) -> bool:
    return isinstance(value, datetime.datetime)


def parse_datetime(value) -> datetime.datetime:
    try:
        return datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except Exception as e:
        raise TypedloadException(f'Unable to parse {value} as a datetime: {e}')


def dump_datetime(v: datetime.datetime) -> str:
    return v.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def get_dumper(platform_type: PlatformType):

    def _attrdump(d, value) -> Dict[str, Any]:
        r = {}
        for attr in value.__attrs_attrs__:
            attrval = getattr(value, attr.name)
            read_only = attr.metadata.get('readOnly', False)
            name = attr.metadata.get('name', attr.name)
            if platform_type == PlatformType.DIFF and not attr.eq:
                # DIFF mode we only dump eq fields
                continue
            elif not platform_type == PlatformType.DIFF:
                if not attr.repr:
                    continue
                if name == APPGATE_METADATA_ATTRIB_NAME and platform_type == PlatformType.APPGATE:
                    continue
                if read_only:
                    continue
            if d.hidedefault:
                if attrval == attr.default:
                    continue
                elif hasattr(attr.default, 'factory') and attrval == attr.default.factory():
                    continue
            d_val = d.dump(attrval)
            if isinstance(d_val, dict) and not d_val:
                continue
            name = attr.metadata.get('name', attr.name)
            r[name] = d_val

        return r

    dumper = datadumper.Dumper(**{})  # type: ignore
    dumper.handlers.insert(0, (datadumper.is_attrs, _attrdump))
    dumper.handlers.insert(0, (is_datetime_dumper, lambda _a, v: dump_datetime(v)))
    return dumper


def get_loader(platform_type: PlatformType) -> Callable[[Dict[str, Any], Optional[Dict[str, Any]], type],
                                                        Entity_T]:

    def _namedtupleload_wrapper(orig_values, l, value, t):
        entity = dataloader._namedtupleload(l, value, t)
        try:
            if hasattr(entity, ENTITY_METADATA_ATTRIB_NAME):
                appgate_metadata = getattr(entity, ENTITY_METADATA_ATTRIB_NAME)
                if platform_type == PlatformType.K8S \
                        and K8S_LOADERS_FIELD_NAME in appgate_metadata:
                    els: List[Union[CustomFieldsEntityLoader, CustomEntityLoader]] = \
                        appgate_metadata[K8S_LOADERS_FIELD_NAME]
                    for el in (els or []):
                        entity = el.load(orig_values, entity)
                elif platform_type == PlatformType.APPGATE \
                        and APPGATE_LOADERS_FIELD_NAME in appgate_metadata:
                    els: List[Union[CustomFieldsEntityLoader,
                                    CustomEntityLoader]] = appgate_metadata[APPGATE_LOADERS_FIELD_NAME]
                    for el in (els or []):
                        entity = el.load(orig_values, entity)
        except Exception as e:
            raise TypedloadException(str(e))
        return entity

    def _attrload(l, value, type_):
        if not isinstance(value, dict):
            raise dataloader.TypedloadTypeError('Expected dictionary, got %s' % type(value),
                                                type_=type_, value=value)
        value = value.copy()
        orig_values = value.copy()
        names = []
        defaults = {}
        types = {}
        for attribute in type_.__attrs_attrs__:
            read_only = attribute.metadata.get('readOnly', False)
            write_only = attribute.metadata.get('writeOnly', False)
            if read_only and platform_type == PlatformType.K8S:
                # Don't load attribute from K8S in read only mode even if
                # it's defined
                continue
            elif write_only and platform_type == PlatformType.APPGATE:
                # Don't load attribute from APPGATE in read only mode even if
                # it's defined
                continue
            names.append(attribute.name)
            types[attribute.name] = attribute.type
            defaults[attribute.name] = attribute.default

            # Manage name mangling
            if 'name' in attribute.metadata:
                dataname = attribute.metadata['name']
                pyname = attribute.name

                if dataname in value:
                    tmp = value[dataname]
                    del value[dataname]
                    value[pyname] = tmp

            # Custom loading values
            try:
                if platform_type == PlatformType.K8S \
                        and 'k8s_loader' in attribute.metadata:
                    cls: Iterable[CustomLoader] = attribute.metadata[K8S_LOADERS_FIELD_NAME]
                    for cl in cls:
                        if isinstance(cl, CustomAttribLoader):
                            value = cl.load(value)
                elif platform_type == PlatformType.APPGATE \
                        and 'appgate_loader' in attribute.metadata:
                    cls: Iterable[CustomLoader] = attribute.metadata[APPGATE_LOADERS_FIELD_NAME]
                    for cl in cls:
                        if isinstance(cl, CustomAttribLoader):
                            value = cl.load(value)
            except Exception as e:
                raise TypedloadException(str(e))

        t = dataloader._FakeNamedTuple((
            tuple(names),
            types,
            defaults,
            type_,
        ))
        return _namedtupleload_wrapper(orig_values, l, value, t)

    loader = dataloader.Loader(**{})  # type: ignore
    loader.handlers.insert(0, (dataloader.is_attrs, _attrload))
    loader.handlers.insert(0, (is_datetime_loader, lambda _1, v, _2: parse_datetime(v)))

    def load(data: Dict[str, Any], metadata: Optional[Dict[str, Any]],
             entity: type) -> Entity_T:
        metadata = metadata or {}
        if APPGATE_METADATA_ATTRIB_NAME in data:
            appgate_mt = data[APPGATE_METADATA_ATTRIB_NAME]
        else:
            appgate_mt = {}
        for k in APPGATE_METADATE_FIELDS:
            if k in metadata:
                appgate_mt[k] = metadata[k]
        if platform_type == PlatformType.APPGATE:
            appgate_mt['fromAppgate'] = True
        data[APPGATE_METADATA_ATTRIB_NAME] = appgate_mt
        try:
            return loader.load(data, entity)
        except TypedloadValueError as e:
            raise AppgateException(f'loader: {platform_type}, value: {e.value}, type: {e.type_}')

    if platform_type == PlatformType.K8S:
        return load  # type: ignore
    return lambda data, _, entity: load(data, None, entity)  # type: ignore


K8S_LOADER = EntityLoader(load=get_loader(PlatformType.K8S))
K8S_DUMPER = EntityDumper(dump=get_dumper(PlatformType.K8S).dump)
APPGATE_LOADER = EntityLoader(load=get_loader(PlatformType.APPGATE))
APPGATE_DUMPER = EntityDumper(dump=get_dumper(PlatformType.APPGATE).dump)
DIFF_DUMPER = EntityDumper(dump=get_dumper(PlatformType.DIFF).dump)
