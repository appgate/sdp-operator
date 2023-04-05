import datetime
import re

from attr import evolve
from dateutil import parser
from typing import Dict, Any, List, Callable, Optional, Union, Type

from typedload import dataloader
from typedload import datadumper
from typedload.datadumper import Dumper
from typedload.exceptions import (
    TypedloadException,
    TypedloadValueError,
    TypedloadTypeError,
    TypedloadAttributeError,
)

from appgate.customloaders import (
    CustomFieldsEntityLoader,
    CustomAttribLoader,
    CustomEntityLoader,
)
from appgate.logger import log
from appgate.openapi.types import (
    Entity_T,
    ENTITY_METADATA_ATTRIB_NAME,
    APPGATE_METADATA_ATTRIB_NAME,
    APPGATE_METADATE_FIELDS,
    APPGATE_LOADERS_FIELD_NAME,
    K8S_LOADERS_FIELD_NAME,
    EntityLoader,
    EntityDumper,
    AppgateTypedloadException,
    PlatformType,
    APISpec,
    is_singleton,
    K8S_ID_ANNOTATION,
    MissingFieldDependencies,
)
from appgate.openapi.utils import has_name, has_id


__all__ = [
    "K8S_DUMPER",
    "APPGATE_DUMPER",
    "K8S_LOADER",
    "APPGATE_LOADER",
    "DIFF_DUMPER",
    "GIT_DUMPER",
    "GIT_LOADER",
    "get_loader",
    "get_dumper",
    "dump_datetime",
    "parse_datetime",
    "k8s_name",
]


def _attrdump(d, value) -> Dict[str, Any]:
    r = {}
    for attr in value.__attrs_attrs__:
        attrval = getattr(value, attr.name)
        if not attr.repr:
            continue
        if "readOnly" in attr.metadata:
            continue
        if not (d.hidedefault and attrval == attr.default):
            name = attr.metadata.get("name", attr.name)
            r[name] = d.dump(attrval)
    return r


def is_datetime_loader(type_: Type[Any]) -> bool:
    name = getattr(type_, "__name__", None)
    return name == "datetime"


def is_datetime_dumper(value: Any) -> bool:
    return isinstance(value, datetime.datetime)


def parse_datetime(value) -> datetime.datetime:
    try:
        # dateutil.fromisofromat cannot handle string that contains 6+ sub-second digits
        return parser.isoparse(value.replace("Z", "+00:00"))
    except Exception as e:
        raise TypedloadException(f"Unable to parse {value} as a datetime: {e}")


def dump_datetime(v: datetime.datetime) -> str:
    return v.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def k8s_name(name: str) -> str:
    # TODO: We need to think how to deal with potential conflicts here
    # This is ugly but we need to go from a bigger set of strings
    # into a smaller one :(
    return re.sub("[^a-z0-9-.]+", "-", name.strip().lower())[:64]


def k8s_dumper(
    dumper: Dumper,
    entity: Entity_T,
    api_spec: APISpec,
    strict: bool = True,
    resolution_conflicts: Dict[str, List[MissingFieldDependencies]] | None = None,
) -> Dict[str, Any]:
    entity_kind = entity.__class__.__qualname__
    annotations = {}
    if has_id(entity):
        annotations[K8S_ID_ANNOTATION] = entity.id
        entity = evolve(
            entity,
            appgate_metadata=evolve(entity.appgate_metadata, uuid=entity.id),
        )
    if is_singleton(entity):
        entity_name = k8s_name(entity_kind)
    elif has_name(entity):
        entity_name = k8s_name(entity.name)
    elif strict:
        raise AppgateTypedloadException(
            "Unable to dump entity: name/id field is missing",
            platform_type=PlatformType.K8S,
        )
    else:
        entity_name = k8s_name(entity_kind)
    spec = dumper.dump(entity)
    return {
        "apiVersion": f"v{api_spec.api_version}.{entity.appgate_metadata.api_version}",
        "kind": entity_kind,
        "metadata": {
            "name": entity_name,
            "annotations": annotations,
        },
        "spec": spec,
    }


def get_dumper(platform_type: PlatformType, api_spec: APISpec | None = None):
    def _attrdump(d, value) -> Dict[str, Any]:
        r = {}
        for attr in value.__attrs_attrs__:
            attrval = getattr(value, attr.name)
            read_only = attr.metadata.get("readOnly", False)
            write_only = attr.metadata.get("writeOnly", False)
            name = attr.metadata.get("name", attr.name)
            if platform_type == PlatformType.DIFF and not attr.eq:
                # DIFF mode we only dump eq fields
                continue
            elif not platform_type == PlatformType.DIFF:
                if not attr.repr:
                    continue
                if name == APPGATE_METADATA_ATTRIB_NAME:
                    continue
                if read_only and platform_type not in {PlatformType.GIT}:
                    continue
                if write_only and platform_type in {PlatformType.GIT}:
                    continue
            if d.hidedefault:
                if name == "_entity_metadata":
                    continue
                if attrval is None or attrval == "":
                    continue
                if (
                    hasattr(attr.default, "factory")
                    and attrval == attr.default.factory()
                ):
                    continue
            d_val = d.dump(attrval)
            if isinstance(d_val, dict) and not d_val:
                continue
            name = attr.metadata.get("name", attr.name)
            r[name] = d_val

        return r

    dumper = datadumper.Dumper(**{})
    dumper.handlers.insert(0, (datadumper.is_attrs, _attrdump))
    dumper.handlers.insert(0, (is_datetime_dumper, lambda _a, v: dump_datetime(v)))

    if platform_type in {PlatformType.K8S, PlatformType.GIT}:
        if api_spec is None:
            raise AppgateTypedloadException(
                "Unable to dump, APISpec is required",
                platform_type=PlatformType.K8S,
            )
        else:
            api = api_spec

            def _get_dumper(
                e: Entity_T,
                strict: bool = True,
                resolution_conflicts: Dict[str, List[MissingFieldDependencies]]
                | None = None,
            ) -> Dict[str, Any]:
                return k8s_dumper(
                    dumper,
                    e,
                    api,
                    strict=strict,
                    resolution_conflicts=resolution_conflicts,
                )

            return _get_dumper
    else:

        def _get_dumper(
            e: Entity_T,
            strict: bool = True,
            resolution_conflicts: Dict[str, List[MissingFieldDependencies]]
            | None = None,
        ) -> Dict[str, Any]:
            return dumper.dump(e)

        return _get_dumper


def get_loader(
    platform_type: PlatformType,
) -> Callable[[Dict[str, Any], Optional[Dict[str, Any]], type], Entity_T]:
    # TODO: Implement GIT_LOADERS_FIELD_NAME
    def _attrload(l, value, type_):
        from attr._make import _Nothing as NOTHING

        if not isinstance(value, dict):
            raise dataloader.TypedloadTypeError(
                "Expected dictionary, got %s" % type(value), type_=type_, value=value
            )

        fields = {i.name for i in type_.__attrs_attrs__}
        necessary_fields = set()
        type_hints = {
            i.name: (
                dataloader._get_attr_converter_type(i.converter)
                if i.converter
                else i.type
            )
            for i in type_.__attrs_attrs__
        }
        namesmap = {}  # type: Dict[str, str]

        value = value.copy()
        orig_values = value.copy()

        for attribute in type_.__attrs_attrs__:

            read_only = attribute.metadata.get("readOnly", False)
            write_only = attribute.metadata.get("writeOnly", False)
            if (read_only and platform_type == PlatformType.K8S) or (
                write_only
                and platform_type
                in {
                    PlatformType.APPGATE,
                    PlatformType.GIT,
                }
            ):
                # Don't load attribute from K8S in read only mode even if
                # it's defined
                fields.remove(attribute.name)
                continue

            if attribute.default is NOTHING and attribute.init:
                necessary_fields.add(attribute.name)

            # Manage name mangling
            if l.mangle_key in attribute.metadata:
                namesmap[attribute.metadata[l.mangle_key]] = attribute.name

            # Custom loading values
            try:
                if (
                    platform_type == PlatformType.K8S
                    and "k8s_loader" in attribute.metadata
                ):
                    # cls: Iterable[CustomLoader]
                    cls = attribute.metadata[K8S_LOADERS_FIELD_NAME]
                    for cl in cls:
                        if isinstance(cl, CustomAttribLoader):
                            value = cl.load(value)
                elif (
                    platform_type == PlatformType.APPGATE
                    and "appgate_loader" in attribute.metadata
                ):
                    # cls: Iterable[CustomLoader]
                    cls = attribute.metadata[APPGATE_LOADERS_FIELD_NAME]
                    for cl in cls:
                        if isinstance(cl, CustomAttribLoader):
                            value = cl.load(value)
            except Exception as e:
                raise TypedloadException(str(e))

        try:
            value = dataloader._mangle_names(namesmap, value, l.failonextra)
        except ValueError as e:
            raise TypedloadValueError(str(e), value=value, type_=type_)
        except AttributeError as e:
            raise TypedloadAttributeError(str(e), value=value, type_=type_)

        entity = dataloader._objloader(
            l, fields, necessary_fields, type_hints, value, type_
        )

        try:
            if hasattr(entity, ENTITY_METADATA_ATTRIB_NAME):
                appgate_metadata = getattr(entity, ENTITY_METADATA_ATTRIB_NAME)
                if (
                    platform_type == PlatformType.K8S
                    and K8S_LOADERS_FIELD_NAME in appgate_metadata
                ):
                    els: List[
                        Union[CustomFieldsEntityLoader, CustomEntityLoader]
                    ] = appgate_metadata[K8S_LOADERS_FIELD_NAME]
                    for el in els or []:
                        entity = el.load(orig_values, entity)
                elif (
                    platform_type == PlatformType.APPGATE
                    and APPGATE_LOADERS_FIELD_NAME in appgate_metadata
                ):
                    els: List[
                        Union[CustomFieldsEntityLoader, CustomEntityLoader]
                    ] = appgate_metadata[APPGATE_LOADERS_FIELD_NAME]
                    for el in els or []:
                        entity = el.load(orig_values, entity)
        except TypedloadException as e:
            raise TypedloadException(
                description=str(e), value=e.value, type_=e.type_
            ) from None
        except Exception as e:
            raise TypedloadException(
                description=str(e), value=value, type_=type
            ) from None
        return entity

    loader = dataloader.Loader(**{})
    loader.handlers.insert(0, (dataloader.is_attrs, _attrload))
    loader.handlers.insert(0, (is_datetime_loader, lambda _1, v, _2: parse_datetime(v)))

    def load(
        data: Dict[str, Any], metadata: Optional[Dict[str, Any]], entity: Type
    ) -> Entity_T:
        metadata = metadata or {}
        if APPGATE_METADATA_ATTRIB_NAME in data:
            appgate_mt = data[APPGATE_METADATA_ATTRIB_NAME]
        else:
            appgate_mt = {}
        for k in APPGATE_METADATE_FIELDS:
            if k in metadata:
                appgate_mt[k] = metadata[k]
        if platform_type == PlatformType.APPGATE:
            appgate_mt["fromAppgate"] = True
        data[APPGATE_METADATA_ATTRIB_NAME] = appgate_mt
        try:
            loaded_entity = loader.load(data, entity)
            if metadata:
                annotations = metadata.get("annotations", {})
                if K8S_ID_ANNOTATION in annotations:
                    loaded_entity = evolve(
                        loaded_entity, id=annotations[K8S_ID_ANNOTATION]
                    )
                    log.info(
                        "[k8s-loader] Recovering id identity: %s | %s",
                        loaded_entity.name,
                        annotations[K8S_ID_ANNOTATION],
                    )
            return loaded_entity
        except TypedloadException as e:
            raise AppgateTypedloadException(
                platform_type=platform_type,
                value=e.value,
                type_=e.type_,
                description=str(e),
            ) from None
        except ValueError as e:
            raise AppgateTypedloadException(
                platform_type=platform_type,
                description=str(e),
            ) from None

    if platform_type == PlatformType.K8S:
        return load
    return lambda data, _, entity: load(data, None, entity)


K8S_LOADER = EntityLoader(load=get_loader(PlatformType.K8S))
K8S_DUMPER = lambda api_spec: EntityDumper(
    dump=get_dumper(PlatformType.K8S, api_spec=api_spec)
)
APPGATE_LOADER = EntityLoader(load=get_loader(PlatformType.APPGATE))
APPGATE_DUMPER = EntityDumper(dump=get_dumper(PlatformType.APPGATE))

DIFF_DUMPER = EntityDumper(dump=get_dumper(PlatformType.DIFF))

GIT_DUMPER = lambda api_spec: EntityDumper(
    dump=get_dumper(PlatformType.GIT, api_spec=api_spec)
)
GIT_LOADER = EntityLoader(load=get_loader(PlatformType.GIT))
