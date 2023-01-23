from pathlib import Path
from typing import Dict, Optional, Tuple, Type, Callable, Sequence, List

import attrs
import yaml

from apischema import settings
from apischema.json_schema import deserialization_schema
from apischema.json_schema.types import JsonType
from apischema.objects import ObjectField, AliasedStr

from appgate.client import AppgateClient, AppgateEntityClient
from appgate.logger import log
from appgate.openapi.parser import is_compound, Parser, ParserContext
from appgate.openapi.types import (
    APISpec,
    OpenApiParserException,
    SPEC_ENTITIES,
    K8S_APPGATE_DOMAIN,
    K8S_APPGATE_VERSION,
    GeneratedEntity,
    APPGATE_METADATA_ATTRIB_NAME,
    ENTITY_METADATA_ATTRIB_NAME,
)

__all__ = [
    "parse_files",
    "SPEC_DIR",
    "generate_crd",
    "entity_names",
    "generate_api_spec",
    "generate_api_spec_clients",
]

from appgate.types import EntityClient

# Always set the default API version to latest released version
SPEC_DIR = "api_specs/v18"
K8S_API_VERSION = "apiextensions.k8s.io/v1"
K8S_CRD_KIND = "CustomResourceDefinition"
LIST_PROPERTIES = {"range", "data", "query", "orderBy", "descending", "filterBy"}


def parse_files(
    spec_entities: Dict[str, str],
    operator_mode: str,
    spec_directory: Optional[Path] = None,
    spec_file: str = "api_specs.yml",
    k8s_get_secret: Optional[Callable[[str, str], str]] = None,
    secrets_key: Optional[str] = None,
) -> APISpec:
    parser_context = ParserContext(
        spec_entities=spec_entities,
        spec_api_path=spec_directory or Path(SPEC_DIR),
        secrets_key=secrets_key,
        k8s_get_secret=k8s_get_secret,
        operator_mode=operator_mode,
    )
    parser = Parser(parser_context, spec_file)
    # First parse those paths we are interested in
    for path, v in parser.data["paths"].items():
        if not parser_context.get_entity_name(path):
            continue
        entity_name = spec_entities[path]
        log.info("Generating entity %s for path %s", entity_name, path)
        keys = ["requestBody", "content", "application/json", "schema"]
        # Check if path returns a singleton or a list of entities
        get_schema = parser.get_keys(
            keys=[
                "paths",
                path,
                "get",
                "responses",
                "200",
                "content",
                "application/json",
                "schema",
            ]
        )
        if isinstance(get_schema, dict) and is_compound(get_schema):
            # TODO: when data.items is a compound method the references are not resolved.
            parsed_schema = parser.parse_all_of(get_schema["allOf"])
        elif isinstance(get_schema, dict):
            parsed_schema = get_schema
        else:
            parsed_schema = {}
        singleton = not all(
            map(lambda f: f in parsed_schema.get("properties", {}), LIST_PROPERTIES)
        )
        parser.parse_definition(
            entity_name=entity_name,
            keys=[["paths", path] + ["post"] + keys, ["paths", path] + ["put"] + keys],
            singleton=singleton,
        )

    return APISpec(entities=parser_context.entities, api_version=parser.api_version())


def entity_names(
    entity: type, short_names: Dict[str, str]
) -> Tuple[str, str, str, str]:
    name = entity.__name__
    short_name = name[0:3].lower()
    if short_name in short_names:
        conflicting_name_prefix = short_names[short_name][0:2]
        # Another CRD has the same short name, iterate letters until one is free
        for i in range(len(name) - 3):
            short_name = f"{conflicting_name_prefix}{name[i]}".lower()
            if short_name not in short_names:
                continue
        if short_name in short_names:
            raise OpenApiParserException(
                "Unable to generate short name for entity %s", name
            )
    short_names[short_name] = name
    singular_name = name.lower()
    if singular_name.endswith("y"):
        plural_name = f"{singular_name[:-1]}ies"
    else:
        plural_name = f"{singular_name}s"

    return name, singular_name, plural_name, short_name


def generate_crd(entity: Type, short_names: Dict[str, str], api_version: str) -> str:
    prev_default_object_fields = settings.default_object_fields

    def attrs_fields(cls: type) -> Optional[Sequence[ObjectField]]:
        """
        Custom attribute getter for apischema. It ignores the Appgate and Entity metadata attributes
        and read-only attributes.
        """
        if attrs.has(cls):
            obj: List[ObjectField] = []
            for a in attrs.fields(cls):
                # Ignore these internal attributes from the schema deserialization
                if (
                    a.name == APPGATE_METADATA_ATTRIB_NAME
                    or a.name == ENTITY_METADATA_ATTRIB_NAME
                ):
                    continue
                # Ignore readOnly attributes from schema deserialization
                if "readOnly" in a.metadata.keys() and a.metadata["readOnly"]:
                    continue

                obj.append(
                    ObjectField(
                        a.name,
                        a.type,
                        required=a.default == attrs.NOTHING,
                        default=a.default,
                    )
                )
            return obj
        else:
            return prev_default_object_fields(cls)

    settings.default_object_fields = attrs_fields

    name, singular_name, plural_name, short_name = entity_names(entity, short_names)
    schema = deserialization_schema(entity)

    def replace_nullable_type(obj: dict) -> dict:
        """
        Recursively remove JsonType.NULL from type. When the apischema deserializer encounters
        a nullable property, it produces [JsonType.*, JsonType.NULL].
        """
        for k, v in obj.items():
            if isinstance(v, dict):
                obj[k] = replace_nullable_type(v)
        if (
            "type" in obj.keys()
            and isinstance(obj["type"], list)
            and len(obj["type"]) > 1
        ):
            obj["type"] = obj["type"][0]
        return obj

    schema = replace_nullable_type(dict(schema))

    def remove_keys(obj: dict, key_to_del: str) -> dict:
        """
        Recursively remove '$schema' 'uniqueItems' and 'additionalProperties' keys from the schema
        to comply with the OpenAPI v4 schema validated by x-kubernetes-validation.

        See https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/_print/#validation
        """
        if isinstance(obj, dict):
            obj = {
                key: remove_keys(value, key_to_del)
                for key, value in obj.items()
                if key not in key_to_del
            }
        return obj

    schema = remove_keys(schema, "$schema")
    schema = remove_keys(schema, "uniqueItems")
    schema = remove_keys(schema, "additionalProperties")

    def add_items_key_to_tags(obj: dict) -> dict:
        """
        Recursively add 'items' key for schemas containing tags. When the deserializer encounters a schema
        that has a tag attribute made from BUILTIN_TAGS, it cannot determine the type. YAML dumper does not
        like JsonType.NULL.
        """
        for k, v in obj.items():
            if isinstance(v, dict):
                obj[k] = add_items_key_to_tags(v)
        if "tags" in obj.keys() and "items" not in obj["tags"].keys():
            obj["tags"]["items"] = {"type": "string"}
        return obj

    schema = add_items_key_to_tags(schema)

    def replace_underscore(obj: dict) -> dict:
        """
        Recursively replace underscore with period in the keys of a dictionary object. When the apischema
        deserializer encounters a key with a period, it replaces it with an underscore. We want to revert that.
        """
        for k, v in obj.items():
            if isinstance(v, dict):
                obj[k] = replace_underscore(v)
        for key in obj.keys():
            if "_" in key:
                new_key = key.replace("_", ".")
                obj[new_key] = obj.pop(key)
        return obj

    schema = replace_underscore(schema)

    domain = f"{api_version}.{K8S_APPGATE_DOMAIN}"

    crd = {
        "apiVersion": K8S_API_VERSION,
        "kind": K8S_CRD_KIND,
        "metadata": {
            "name": f"{plural_name}.{domain}",
        },
        "spec": {
            "group": domain,
            "versions": [
                {
                    "name": K8S_APPGATE_VERSION,
                    "served": True,
                    "storage": True,
                    "schema": {
                        "openAPIV3Schema": {
                            "type": "object",
                            "properties": {"spec": schema},
                        }
                    },
                }
            ],
            "scope": "Namespaced",
            "names": {
                "singular": singular_name,
                "plural": plural_name,
                "kind": name,
                "shortNames": [short_name],
            },
        },
    }

    def str_representer(dumper, data):
        """
        Register representers for types unknown to YAML safe dumper.
        """
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    yaml.SafeDumper.add_representer(AliasedStr, str_representer)
    yaml.SafeDumper.add_representer(JsonType, str_representer)

    return yaml.safe_dump(crd)


def generate_api_spec(
    spec_directory: Optional[Path] = None,
    secrets_key: Optional[str] = None,
    k8s_get_secret: Optional[Callable[[str, str], str]] = None,
    operator_mode: str = "appgate-operator",
) -> APISpec:
    """
    Parses openapi yaml files and generates the ApiSpec.
    """
    return parse_files(
        SPEC_ENTITIES,
        spec_directory=spec_directory,
        secrets_key=secrets_key,
        k8s_get_secret=k8s_get_secret,
        operator_mode=operator_mode,
    )


MAGIC_ENTITIES = {
    "Site": [
        # Use '6f6fa9d9-17b2-4157-9f68-e97662acccdf' to collect logs
        # from all the appliances
        "6f6fa9d9-17b2-4157-9f68-e97662acccdf",
        # Use '6263435b-c9f6-4b7f-99f8-37e2e6b006a9' to collect logs
        # from appliances without a site.
        "6263435b-c9f6-4b7f-99f8-37e2e6b006a9",
    ]
}


def generate_api_spec_clients(
    api_spec: APISpec, appgate_client: AppgateClient
) -> Dict[str, EntityClient | None]:
    def _entity_client(e_name: str, e: GeneratedEntity) -> AppgateEntityClient:
        magic_entities = None
        # We filter the None's in the caller anyway
        assert e.api_path is not None
        if e_name in MAGIC_ENTITIES:
            magic_entities = [
                e.cls(
                    name=magic_instance, id=magic_instance, tags=frozenset({"builtin"})
                )
                for magic_instance in MAGIC_ENTITIES[e_name]
            ]
        return appgate_client.entity_client(
            e.cls, e.api_path, singleton=e.singleton, magic_entities=magic_entities
        )

    return {n: _entity_client(n, e) for n, e in api_spec.entities.items() if e.api_path}
