import enum
from typing import Dict, Any, List

from typedload import dataloader
from typedload import datadumper


__all__ = [
    'K8S_DUMPER',
    'APPGATE_DUMPER',
    'K8S_LOADER',
    'APPGATE_LOADER',
    'APPGATE_DUMPER_WITH_SECRETS',
    'get_loader',
    'get_dumper',
]

from typedload.exceptions import TypedloadException

from appgate.customloaders import CustomEntityLoader, CustomLoader, CustomAttribLoader
from appgate.openapi.parser import APPGATE_METADATA_ATTRIB_NAME


class PlatformType(enum.Enum):
    K8S = 1
    APPGATE = 2


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


def get_dumper(platform_type: PlatformType, dump_secrets: bool = False):

    def _attrdump(d, value) -> Dict[str, Any]:
        r = {}
        for attr in value.__attrs_attrs__:
            attrval = getattr(value, attr.name)
            read_only = attr.metadata.get('readOnly', False)
            write_only = attr.metadata.get('writeOnly', False)
            format = attr.metadata.get('format')
            if not attr.repr:
                continue
            if read_only:
                continue
            if write_only and format == 'password':
                if not dump_secrets and platform_type == PlatformType.APPGATE:
                    continue
            if not (d.hidedefault and attrval == attr.default):
                name = attr.metadata.get('name', attr.name)
                r[name] = d.dump(attrval)
        return r

    dumper = datadumper.Dumper(**{})  # type: ignore
    dumper.handlers.insert(0, (datadumper.is_attrs, _attrdump))
    return dumper


def get_loader(platform_type: PlatformType):

    def _namedtupleload_wrapper(l, value, t):
        entity = dataloader._namedtupleload(l, value, t)
        try:
            if hasattr(entity, APPGATE_METADATA_ATTRIB_NAME):
                appgate_metadata = getattr(entity, APPGATE_METADATA_ATTRIB_NAME)
                if platform_type == PlatformType.K8S \
                        and 'k8s_loader' in appgate_metadata:
                    els: List[CustomEntityLoader] = appgate_metadata['k8s_loader']
                    for el in (els or []):
                        entity = el.load(entity)
                elif platform_type == PlatformType.APPGATE \
                        and 'appgate_loader' in appgate_metadata.get('metadata', {}):
                    els: List[CustomEntityLoader] = appgate_metadata['appgate_loader']
                    for el in (els or []):
                        entity = el.load(entity)
        except Exception as e:
            raise TypedloadException(str(e))
        return entity

    def _attrload(l, value, type_):
        if not isinstance(value, dict):
            raise dataloader.TypedloadTypeError('Expected dictionary, got %s' % type(value),
                                                type_=type_, value=value)
        value = value.copy()
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
                    cl: CustomLoader = attribute.metadata['k8s_loader']
                    if isinstance(cl, CustomAttribLoader):
                        value = cl.load(value)
                elif platform_type == PlatformType.APPGATE \
                        and 'appgate_loader' in attribute.metadata:
                    cl: CustomLoader = attribute.metadata['appgate_loader']
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

        return _namedtupleload_wrapper(l, value, t)

    loader = dataloader.Loader(**{})  # type: ignore
    loader.handlers.insert(0, (dataloader.is_attrs, _attrload))
    return loader


K8S_LOADER = get_loader(PlatformType.K8S)
K8S_DUMPER = get_dumper(PlatformType.K8S)
APPGATE_LOADER = get_loader(PlatformType.APPGATE)
APPGATE_DUMPER = get_dumper(PlatformType.APPGATE)
APPGATE_DUMPER_WITH_SECRETS = get_dumper(PlatformType.APPGATE, dump_secrets=True)
