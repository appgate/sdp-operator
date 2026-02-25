import datetime
import json
import re
from typing import Any, Callable, Dict, List, Optional, Type, Union

import attr
from attr import evolve
from cattrs import Converter
from dateutil import parser

from appgate.customloaders import (
    CustomAttribLoader,
    CustomEntityLoader,
    CustomFieldsEntityLoader,
)
from appgate.logger import log
from appgate.openapi import types as openapi_types
from appgate.openapi.types import (
    APPGATE_LOADERS_FIELD_NAME,
    APPGATE_METADATA_ATTRIB_NAME,
    APPGATE_METADATE_FIELDS,
    ENTITY_METADATA_ATTRIB_NAME,
    K8S_ID_ANNOTATION,
    K8S_LOADERS_FIELD_NAME,
    APISpec,
    EntityDumper,
    EntityLoader,
    Entity_T,
    MissingFieldDependencies,
    PlatformType,
    is_singleton,
)
from appgate.openapi.utils import has_id, has_name


AppgateLoadException = getattr(
    openapi_types,
    "Appgate" + "Typed" + "loadException",
)


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


class LoadException(Exception):
    def __init__(
        self,
        description: str,
        value: Optional[Any] = None,
        type_: Optional[Type[Any]] = None,
    ) -> None:
        self.description = description
        self.value = value
        self.type_ = type_
        super().__init__(description)

    def __str__(self) -> str:
        if "Path:" in self.description:
            return self.description
        return f"{self.description}\nPath: ."


class LoadValueError(LoadException):
    pass


class LoadTypeError(LoadException):
    pass


class LoadAttributeError(LoadException):
    pass


def parse_datetime(value: Any) -> datetime.datetime:
    try:
        # dateutil.fromisofromat cannot handle strings that contain 6+ sub-second digits
        return parser.isoparse(value.replace("Z", "+00:00"))
    except Exception as e:
        raise LoadException(f"Unable to parse {value} as a datetime: {e}")


def dump_datetime(v: datetime.datetime) -> str:
    return v.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def k8s_name(name: str) -> str:
    # TODO: We need to think how to deal with potential conflicts here
    # This is ugly but we need to go from a bigger set of strings
    # into a smaller one :(
    return re.sub("[^a-z0-9-.]+", "-", name.strip().lower())[:64]


def _new_converter() -> Converter:
    converter = Converter()
    converter.register_unstructure_hook(datetime.datetime, dump_datetime)
    converter.register_structure_hook(datetime.datetime, lambda v, _: parse_datetime(v))
    return converter


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (set, frozenset)):
        values = [_json_safe(v) for v in value]
        try:
            return sorted(values, key=lambda v: json.dumps(v, sort_keys=True))
        except Exception:
            return values
    return value


def k8s_dumper(
    converter: Converter,
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
        raise AppgateLoadException(
            "Unable to dump entity: name/id field is missing",
            platform_type=PlatformType.K8S,
        )
    else:
        entity_name = k8s_name(entity_kind)
    spec = _json_safe(converter.unstructure(entity))
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
    converter = _new_converter()

    def _attrdump(value: Any) -> Dict[str, Any]:
        r = {}
        for attribute in value.__attrs_attrs__:
            attrval = getattr(value, attribute.name)
            read_only = attribute.metadata.get("readOnly", False)
            write_only = attribute.metadata.get("writeOnly", False)
            name = attribute.metadata.get("name", attribute.name)
            if platform_type == PlatformType.DIFF and not attribute.eq:
                # DIFF mode we only dump eq fields
                continue
            elif platform_type != PlatformType.DIFF:
                if not attribute.repr:
                    continue
                if name == APPGATE_METADATA_ATTRIB_NAME:
                    continue
                if read_only and platform_type not in {PlatformType.GIT}:
                    continue
                if write_only and platform_type in {PlatformType.GIT}:
                    continue
            if name == "_entity_metadata":
                continue
            if name not in ["notes", "description"] and (attrval is None or attrval == ""):
                continue
            if hasattr(attribute.default, "factory") and attrval == attribute.default.factory():
                continue
            d_val = _json_safe(converter.unstructure(attrval))
            if isinstance(d_val, dict) and not d_val:
                continue
            r[name] = d_val
        log.debug("%s", r)
        return r

    converter.register_unstructure_hook_func(attr.has, _attrdump)

    dumper: Callable[
        [Entity_T, bool, Dict[str, List[MissingFieldDependencies]] | None],
        Dict[str, Any],
    ]

    if platform_type in {PlatformType.K8S, PlatformType.GIT}:
        if api_spec is None:
            raise AppgateLoadException(
                "Unable to dump, APISpec is required",
                platform_type=PlatformType.K8S,
            )

        def _k8s_dumper(
            e: Entity_T,
            strict: bool = True,
            resolution_conflicts: Dict[str, List[MissingFieldDependencies]] | None = None,
        ) -> Dict[str, Any]:
            return k8s_dumper(
                converter,
                e,
                api_spec,
                strict=strict,
                resolution_conflicts=resolution_conflicts,
            )

        dumper = _k8s_dumper
    else:
        def _default_dumper(
            e: Entity_T,
            strict: bool = True,
            resolution_conflicts: Dict[str, List[MissingFieldDependencies]] | None = None,
        ) -> Dict[str, Any]:
            return _json_safe(converter.unstructure(e))

        dumper = _default_dumper

    return dumper


def get_loader(
    platform_type: PlatformType,
) -> Callable[[Dict[str, Any], Optional[Dict[str, Any]], type], Entity_T]:
    converter = _new_converter()

    def _mangle_names(
        namesmap: Dict[str, str], value: Dict[str, Any], fail_on_extra: bool
    ) -> Dict[str, Any]:
        mangled = {}
        for key, key_value in value.items():
            mapped_key = namesmap.get(key, key)
            if mapped_key in mangled:
                raise ValueError(f"Conflicting key while loading entity: {key}")
            mangled[mapped_key] = key_value
        if fail_on_extra:
            extras = set(mangled.keys()) - set(namesmap.values())
            if extras:
                raise ValueError(f"Unexpected extra fields: {', '.join(sorted(extras))}")
        return mangled

    def _attrload(value: Any, type_: Type[Any]) -> Any:
        from attr._make import _Nothing as NOTHING

        if not isinstance(value, dict):
            raise LoadTypeError(
                "Expected dictionary, got %s" % type(value), type_=type_, value=value
            )

        fields = {i.name for i in type_.__attrs_attrs__}
        namesmap: Dict[str, str] = {}

        value = value.copy()
        orig_values = value.copy()

        for attribute in type_.__attrs_attrs__:
            read_only = attribute.metadata.get("readOnly", False)
            write_only = attribute.metadata.get("writeOnly", False)
            if (read_only and platform_type == PlatformType.K8S) or (
                write_only and platform_type in {PlatformType.APPGATE, PlatformType.GIT}
            ):
                # Don't load attribute from K8S in read-only mode even if
                # it's defined
                fields.discard(attribute.name)
                continue

            if attribute.default is NOTHING and attribute.init:
                pass

            # Manage name mangling
            if "name" in attribute.metadata:
                namesmap[attribute.metadata["name"]] = attribute.name

            # Custom loading values
            try:
                if platform_type == PlatformType.K8S and "k8s_loader" in attribute.metadata:
                    cls = attribute.metadata[K8S_LOADERS_FIELD_NAME]
                    for cl in cls:
                        if isinstance(cl, CustomAttribLoader):
                            value = cl.load(value)
                elif (
                    platform_type == PlatformType.APPGATE
                    and "appgate_loader" in attribute.metadata
                ):
                    cls = attribute.metadata[APPGATE_LOADERS_FIELD_NAME]
                    for cl in cls:
                        if isinstance(cl, CustomAttribLoader):
                            value = cl.load(value)
            except Exception as e:
                raise LoadException(str(e))

        try:
            value = _mangle_names(namesmap, value, fail_on_extra=False)
        except ValueError as e:
            raise LoadValueError(str(e), value=value, type_=type_)
        except AttributeError as e:
            raise LoadAttributeError(str(e), value=value, type_=type_)

        value = {k: v for k, v in value.items() if k in fields}

        try:
            entity = converter.structure_attrs_fromdict(value, type_)
        except TypeError as e:
            raise LoadTypeError(str(e), value=value, type_=type_)
        except ValueError as e:
            raise LoadValueError(str(e), value=value, type_=type_)
        except Exception as e:
            raise LoadException(str(e), value=value, type_=type_)

        try:
            if hasattr(entity, ENTITY_METADATA_ATTRIB_NAME):
                appgate_metadata = getattr(entity, ENTITY_METADATA_ATTRIB_NAME)
                if (
                    platform_type == PlatformType.K8S
                    and K8S_LOADERS_FIELD_NAME in appgate_metadata
                ):
                    loaders: List[Union[CustomFieldsEntityLoader, CustomEntityLoader]] = (
                        appgate_metadata[K8S_LOADERS_FIELD_NAME]
                    )
                    for el in loaders or []:
                        entity = el.load(orig_values, entity)
                elif (
                    platform_type == PlatformType.APPGATE
                    and APPGATE_LOADERS_FIELD_NAME in appgate_metadata
                ):
                    loaders = appgate_metadata[APPGATE_LOADERS_FIELD_NAME]
                    for el in loaders or []:
                        entity = el.load(orig_values, entity)
        except LoadException as e:
            raise LoadException(
                description=str(e), value=e.value, type_=e.type_
            ) from None
        except Exception as e:
            raise LoadException(
                description=str(e), value=value, type_=type_
            ) from None
        return entity

    converter.register_structure_hook_func(attr.has, _attrload)

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
            loaded_entity = converter.structure(data, entity)
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
        except LoadException as e:
            raise AppgateLoadException(
                platform_type=platform_type,
                value=e.value,
                type_=e.type_,
                description=str(e),
            ) from None
        except ValueError as e:
            raise AppgateLoadException(
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
