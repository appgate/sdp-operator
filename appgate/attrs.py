import enum
from typing import Dict, Any

from typedload import dataloader
from typedload import datadumper


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


def get_dumper(platform_type: PlatformType):

    def _attrdump(d, value) -> Dict[str, Any]:
        r = {}
        for attr in value.__attrs_attrs__:
            attrval = getattr(value, attr.name)
            if not attr.repr:
                continue
            if not (d.hidedefault and attrval == attr.default):
                name = attr.metadata.get('name', attr.name)
                r[name] = d.dump(attrval)
        return r

    dumper = datadumper.Dumper(**{})
    dumper.handlers.insert(0, (datadumper.is_attrs, _attrdump))
    return dumper


def get_loader(platform_type: PlatformType):

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
            if read_only and platform_type.K8S:
                # Don't load attribute from K8S in read only mode even if
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

        t = dataloader._FakeNamedTuple((
            tuple(names),
            types,
            defaults,
            type_,
        ))

        return dataloader._namedtupleload(l, value, t)

    loader = dataloader.Loader(**{})
    loader.handlers.insert(0, (dataloader.is_attrs, _attrload))
    return loader
