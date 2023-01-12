import datetime
import functools
from pathlib import Path
from typing import Optional, Dict, Set, Any, List, Type, FrozenSet, cast, Callable

import yaml
from attr import attrib, make_class
from cryptography.fernet import Fernet

from appgate.attrs import K8S_LOADER
from appgate.bytes import (
    size_attrib_maker,
    checksum_attrib_maker,
    certificate_attrib_maker,
)
from appgate.customloaders import CustomFieldsEntityLoader, CustomEntityLoader
from appgate.discriminator import (
    get_discriminator_maker_config,
    DiscriminatorAttribMaker,
)
from appgate.files import FileAttribMaker
from appgate.logger import log
from appgate.openapi.attribmaker import (
    AttribMaker,
    create_default_attrib,
    DeprecatedAttribMaker,
    UUID_REFERENCE_FIELD,
    DefaultAttribMaker,
)
from appgate.openapi.types import (
    OpenApiDict,
    OpenApiParserException,
    GeneratedEntityFieldDependency,
    GeneratedEntity,
    AttributesDict,
    AttribType,
    EntityClassGeneratorConfig,
    AttribMakerConfig,
    AppgateMetadata,
    K8S_LOADERS_FIELD_NAME,
    APPGATE_LOADERS_FIELD_NAME,
    ENTITY_METADATA_ATTRIB_NAME,
    APPGATE_METADATA_ATTRIB_NAME,
)
from appgate.openapi.utils import (
    has_default,
    join,
    make_explicit_references,
    is_compound,
    is_object,
    is_ref,
    is_array,
    is_mapping,
    is_discriminator,
)
from appgate.secrets import PasswordAttribMaker
from appgate.types import BUILTIN_TAGS

TYPES_MAP: Dict[str, Type] = {
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": int,
}
DEFAULT_MAP: Dict[str, AttribType] = {
    "string": "",
    "array": frozenset,
}


class EntityClassGenerator:
    """
    Class used to generate Entity classes dynamically
    """

    def __init__(self, name: str, attributes: Dict[str, AttribMaker]) -> None:
        self.name = name
        self.attributes = attributes

    @property
    def attributes_with_default(self) -> Dict[str, AttribMaker]:
        return {k: v for k, v in self.attributes.items() if v.has_default}

    @property
    def attributes_without_default(self) -> Dict[str, AttribMaker]:
        return {k: v for k, v in self.attributes.items() if not v.has_default}

    @property
    def password_attributes(self) -> Dict[str, AttribMaker]:
        return {k: v for k, v in self.attributes.items() if v.is_password}

    @property
    def dependencies(self) -> Set[GeneratedEntityFieldDependency]:
        dependencies: Set[GeneratedEntityFieldDependency] = set()
        for attrib_name, attrib_attrs in self.attributes.items():
            dependency = attrib_attrs.definition.get(UUID_REFERENCE_FIELD)
            if dependency and isinstance(dependency, list):
                dependencies.add(
                    GeneratedEntityFieldDependency(
                        field_path=attrib_name, dependencies=frozenset(dependency)
                    )
                )
            elif dependency:
                dependencies.add(
                    GeneratedEntityFieldDependency(
                        field_path=attrib_name, dependencies=frozenset({dependency})
                    )
                )
        return dependencies

    def generate(
        self, instance_maker_config: EntityClassGeneratorConfig
    ) -> GeneratedEntity:
        """
        Generate a new Entity class (GeneratedEntity) from the instance_maker_config.
        """
        # Add attributes if needed after instance level
        if "name" not in self.attributes and instance_maker_config.singleton:
            # This field is included by the operator so never load/dump it
            self.attributes["name"] = create_default_attrib(
                "name", self.name, read_only=True, write_only=True
            )
        if "id" not in self.attributes and instance_maker_config.singleton:
            # This field is included by the operator so never load/dump it
            self.attributes["id"] = create_default_attrib(
                "id", self.name, read_only=True, write_only=True
            )
        if "tags" not in self.attributes and instance_maker_config.singleton:
            # This field is included by the operator so never load/dump it
            self.attributes["tags"] = create_default_attrib(
                "tags", BUILTIN_TAGS, read_only=True, write_only=True
            )

        # Get values from attrib makers
        values = dict(
            map(
                lambda kv: (
                    kv[0],
                    kv[1].values(
                        self.attributes,
                        instance_maker_config.definition.get("required", {}),
                        instance_maker_config,
                    ),
                ),
                filter(
                    lambda kv: not isinstance(kv[1], DeprecatedAttribMaker),
                    self.attributes.items(),
                ),
            )
        )
        log.trace(
            "Creating new instance %s with values %s [required fields: %s]",
            self.name,
            values,
            instance_maker_config.definition.get("required", {}),
        )
        # Add custom entity loaders if needed
        k8s_custom_entity_loaders = []
        appgate_custom_entity_loaders = []
        for n, v in values.items():
            if "metadata" not in v:
                continue
            k8s_loaders = v["metadata"].get(K8S_LOADERS_FIELD_NAME, [])
            custom_k8s_attrib_loaders = []
            for k8s_loader in k8s_loaders:
                if any(
                    map(
                        lambda el: isinstance(k8s_loader, el),
                        {CustomFieldsEntityLoader, CustomEntityLoader},
                    )
                ):
                    k8s_custom_entity_loaders.append(k8s_loader)
                else:
                    custom_k8s_attrib_loaders.append(k8s_loader)
            v["metadata"][K8S_LOADERS_FIELD_NAME] = custom_k8s_attrib_loaders
            appgate_loaders = v["metadata"].get(APPGATE_LOADERS_FIELD_NAME, [])
            custom_appgate_attrib_loaders = []
            for appgate_loader in appgate_loaders:
                if any(
                    map(
                        lambda el: isinstance(k8s_loader, el),
                        {CustomFieldsEntityLoader, CustomEntityLoader},
                    )
                ):
                    appgate_custom_entity_loaders.append(appgate_loader)
                else:
                    custom_appgate_attrib_loaders.append(appgate_loader)
            v["metadata"][APPGATE_LOADERS_FIELD_NAME] = custom_appgate_attrib_loaders

        # Build the dictionary of attribs
        attrs = {}
        # First attributes with no default values
        for k, v in filter(lambda p: not has_default(p[1]), values.items()):
            attrs[k] = attrib(**v)
        # Now attributes with default values
        for k, v in filter(lambda p: has_default(p[1]), values.items()):
            attrs[k] = attrib(**v)

        # Create attribute to store entity metadata
        entity_metadata_attrib = create_default_attrib(
            ENTITY_METADATA_ATTRIB_NAME,
            {
                "singleton": instance_maker_config.singleton,
                K8S_LOADERS_FIELD_NAME: k8s_custom_entity_loaders or None,
                APPGATE_LOADERS_FIELD_NAME: appgate_custom_entity_loaders or None,
                "passwords": self.password_attributes,
                "dependencies": self.dependencies,
            },
        )
        attrs[ENTITY_METADATA_ATTRIB_NAME] = attrib(
            **entity_metadata_attrib.values(
                self.attributes,
                instance_maker_config.definition.get("required", {}),
                instance_maker_config,
            )
        )

        # Create attribute to store instance metadata
        appgate_metadata_attrib = DefaultAttribMaker(
            tpe=AppgateMetadata,
            base_tpe=AppgateMetadata,
            name=APPGATE_METADATA_ATTRIB_NAME,
            default=None,
            factory=AppgateMetadata,
            definition={},
            repr=True,
        )
        attrs[APPGATE_METADATA_ATTRIB_NAME] = attrib(
            **appgate_metadata_attrib.values(
                self.attributes,
                instance_maker_config.definition.get("required", {}),
                instance_maker_config,
            )
        )
        cls = make_class(self.name, attrs, slots=True, frozen=True)
        return GeneratedEntity(
            cls=cls,
            api_path=instance_maker_config.api_path,
            singleton=instance_maker_config.singleton,
        )


class ParserContext:
    def __init__(
        self,
        spec_entities: Dict[str, str],
        spec_api_path: Path,
        secrets_key: Optional[str],
        k8s_get_secret: Optional[Callable[[str, str], str]],
    ) -> None:
        self.secrets_cipher = Fernet(secrets_key.encode()) if secrets_key else None
        self.entities: Dict[str, GeneratedEntity] = {}
        self.data: OpenApiDict = {}
        self.spec_api_path: Path = spec_api_path
        self.entity_name_by_path: Dict[str, str] = spec_entities
        self.entity_path_by_name: Dict[str, str] = {
            v: k for k, v in spec_entities.items()
        }
        self.k8s_get_secret = k8s_get_secret

    def get_entity_path(self, entity_name: str) -> Optional[str]:
        return self.entity_path_by_name.get(entity_name)

    def get_entity_name(self, entity_path: str) -> Optional[str]:
        return self.entity_name_by_path.get(entity_path)

    def register_entity(
        self, entity_name: str, entity: GeneratedEntity
    ) -> GeneratedEntity:
        log.trace(f"Registering new class {entity_name}")
        if entity_name in self.entities:
            log.debug(f"Entity %s already registered, ignoring it", entity_name)
        else:
            self.entities[entity_name] = entity
        return self.entities[entity_name]

    def load_namespace(self, namespace: str) -> Dict[str, Any]:
        path = self.spec_api_path / namespace
        if path.name in self.data:
            log.trace("Using cached namespace %s", path)
            return self.data[path.name]
        with path.open("r") as f:
            log.trace("Loading namespace %s from disk", path)
            self.data[path.name] = yaml.safe_load(f.read())
        return self.data[path.name]


class Parser:
    def __init__(self, parser_context: ParserContext, namespace: str) -> None:
        self.namespace = namespace
        self.previous_namespaces: Set[str] = set()
        self.parser_context = parser_context
        self.data: Dict[str, Any] = parser_context.load_namespace(namespace)

    @functools.cache
    def api_version(self) -> int:
        api_version_str = self.get_keys(["info", "version"])
        if not api_version_str:
            raise OpenApiParserException("Unable to find Appgate API version")
        try:
            api_version = api_version_str.split(" ")[2].split(".")[0]
        except IndexError:
            raise OpenApiParserException("Unable to find Appgate API version")
        return api_version

    def resolve_reference(self, reference: str, keys: List[str]) -> Dict[str, Any]:
        path, ref = reference.split("#", maxsplit=2)
        new_keys = [x for x in ref.split("/") if x] + keys
        key_copy = new_keys.copy()
        if not path:
            # Resolve in current namespace
            log.trace(
                "Resolving reference %s in current namespace: %s",
                join(".", new_keys),
                self.namespace,
            )
            resolved_ref = self.get_keys(new_keys)
            if not resolved_ref:
                for previous in self.previous_namespaces:
                    keys = key_copy.copy()
                    resolved_ref = Parser(
                        self.parser_context, namespace=previous
                    ).get_keys(keys)
                    if resolved_ref or len(self.previous_namespaces) == 0:
                        break

        else:
            log.trace(
                "Resolving reference %s in %s namespace", join(".", new_keys), path
            )
            resolved_ref = Parser(self.parser_context, namespace=path).get_keys(
                new_keys
            )
            self.previous_namespaces.add(path)
        if not resolved_ref:
            raise OpenApiParserException(f"Unable to resolve reference {reference}")
        return resolved_ref

    def get_keys(self, keys: List[str]) -> Optional[Any]:
        keys_cp = keys.copy()
        data = self.data
        while True:
            try:
                log.trace("Trying %s in [%s]", join(".", keys), join(", ", data.keys()))
                k = keys.pop(0)
            except IndexError:
                log.trace("Keys not found %s", join(".", keys_cp))
                return None
            # Is the key there?
            if k in data:
                value = data[k]
                # this is a reference, solve it
                if "$ref" in value:
                    data = self.resolve_reference(value["$ref"], keys)
                    # If the resolution succeed that means it should have consumed
                    # all the keys
                    keys = []
                    value = data
                # More keys but we don't have a dict, fail
                elif keys and type(value) is not dict:
                    return None
                else:
                    # iterate
                    data = value

                # No more entries, return the value
                if not keys:
                    return make_explicit_references(value, self.namespace)
            else:
                # key not found
                log.trace("Key %s not found in [%s]", k, ", ".join(data.keys()))
                return None

    def resolve_definition(self, definition: OpenApiDict) -> OpenApiDict:
        if type(definition) is not dict:
            return definition
        if is_compound(definition):
            definition = self.parse_all_of(definition["allOf"])
        for k, v in definition.items():
            if is_ref(v):
                resolved = self.resolve_reference(v["$ref"], [])
                resolved = self.resolve_definition(resolved)
                definition[k] = resolved
            elif is_mapping(k, v):
                for mk, kv in v.items():
                    resolved = self.resolve_reference(kv, [])
                    if is_compound(resolved):
                        resolved = self.parse_all_of(resolved["allOf"])
                    resolved = self.resolve_definition(resolved)
                    definition[k][mk] = resolved
            else:
                definition[k] = self.resolve_definition(v)
        return definition

    def parse_all_of(self, definitions: List[OpenApiDict]) -> OpenApiDict:
        """
        Parse the allOf element in OpenAPI spec. Every element in the allOf is resolved
        and added back to the definition.
        """
        for i, d in enumerate(definitions):
            definitions[i] = self.resolve_definition({"to-resolve": d})["to-resolve"]
        new_definition: OpenApiDict = {
            "type": "object",
            "required": [],
            "properties": {},
            "discriminator": {},
            "description": "",
            "items": {"type": "object", "properties": {}},
        }
        descriptions = []
        for d in definitions:
            if d.get("type") == "array":
                new_definition["type"] = "array"
                items = d.get("items", {})
                new_definition["items"]["properties"].update(
                    items.get("properties", {})
                )
                if "description" in items:
                    descriptions.append(items["description"])
            else:
                new_definition["properties"].update(d.get("properties", {}))
                new_definition["required"].extend(d.get("required", {}))
                new_definition["discriminator"].update(d.get("discriminator", {}))
                if "description" in d:
                    descriptions.append(d["description"])
        new_definition["description"] = ".".join(descriptions)
        return new_definition

    def parse_discriminator(self, definition: OpenApiDict) -> OpenApiDict:
        """
        Parse the discriminator element in OpenAPI spec. Each reference in the mapping
        is fully resolved and added back to the definition.
        """
        new_definition: OpenApiDict = {
            "type": "object",
            "required": [],
            "properties": {},
            "discriminator": {},
            "description": "",
        }
        new_definition["required"].extend(definition.get("required", {}))
        new_definition["properties"].update(definition.get("properties", {}))

        discriminator = definition.get("discriminator")
        if discriminator:
            property_name = discriminator["propertyName"]
            mapping = discriminator["mapping"]

            new_mapping = {}
            for key, ref in mapping.items():
                if not isinstance(ref, dict):
                    ref = self.resolve_reference(ref, [])
                if is_compound(ref):
                    ref = self.parse_all_of(ref["allOf"])
                new_mapping.update({key: ref})

            new_definition["discriminator"]["propertyName"] = property_name
            new_definition["discriminator"]["mapping"] = new_mapping
            new_definition["description"] = definition.get("description", "")

        return new_definition

    def make_attrib_maker(self, attrib_maker_config: AttribMakerConfig) -> AttribMaker:
        """
        Parse an entity in yaml and recursively generate a AttribMaker.
        An AttribMaker represents how to build a specific attribute in an entity class.
        """
        definition = attrib_maker_config.definition
        entity_name = attrib_maker_config.instance_maker_config.entity_name
        attrib_name = attrib_maker_config.name
        tpe = definition.get("type")
        current_level = attrib_maker_config.instance_maker_config.level
        discriminator = attrib_maker_config.instance_maker_config.definition.get(
            "discriminator"
        )
        if is_compound(definition):
            definition = self.parse_all_of(definition["allOf"])
            instance_maker_config = EntityClassGeneratorConfig(
                name=attrib_name,
                entity_name=f"{entity_name}_{attrib_name.capitalize()}",
                definition=definition,
                singleton=attrib_maker_config.instance_maker_config.singleton,
                api_path=None,
                level=current_level + 1,
            )
            generated_entity = self.register_entity(
                entity_class_generator_config=instance_maker_config
            )
            log.trace(
                "Created new attribute %s.%s of type %s",
                entity_name,
                attrib_name,
                generated_entity.cls,
            )
            return AttribMaker(
                name=instance_maker_config.name,
                tpe=generated_entity.cls,
                base_tpe=generated_entity.cls,
                default=None,
                factory=None,
                definition=attrib_maker_config.definition,
            )
        elif not tpe:
            raise Exception("type field not found in %s", definition)
        elif tpe in TYPES_MAP:
            log.trace(
                "Creating new attribute %s.%s :: %s",
                entity_name,
                attrib_name,
                TYPES_MAP[tpe],
            )
            format = definition.get("format", None)
            if format == "password":
                return PasswordAttribMaker(
                    name=attrib_name,
                    tpe=TYPES_MAP[tpe],
                    base_tpe=TYPES_MAP[tpe],
                    default=DEFAULT_MAP.get(tpe),
                    factory=None,
                    definition=attrib_maker_config.definition,
                    secrets_cipher=self.parser_context.secrets_cipher,
                    k8s_get_client=self.parser_context.k8s_get_secret,
                )
            elif format == "date-time":
                return AttribMaker(
                    name=attrib_name,
                    tpe=datetime.datetime,
                    base_tpe=datetime.datetime,
                    default=None,
                    factory=None,
                    definition=attrib_maker_config.definition,
                )
            elif format == "byte":
                return FileAttribMaker(
                    name=attrib_name,
                    tpe=TYPES_MAP[tpe],
                    base_tpe=TYPES_MAP[tpe],
                    default=None,
                    factory=None,
                    definition=attrib_maker_config.definition,
                )
            elif (
                format == "checksum"
                and "x-checksum-source" in attrib_maker_config.definition
            ):
                return checksum_attrib_maker(
                    name=attrib_name,
                    tpe=TYPES_MAP[tpe],
                    base_tpe=TYPES_MAP[tpe],
                    default=DEFAULT_MAP.get(tpe),
                    factory=None,
                    definition=attrib_maker_config.definition,
                    source_field=attrib_maker_config.definition["x-checksum-source"],
                )
            elif format == "size" and "x-size-source" in attrib_maker_config.definition:
                return size_attrib_maker(
                    name=attrib_name,
                    tpe=TYPES_MAP[tpe],
                    base_tpe=TYPES_MAP[tpe],
                    default=DEFAULT_MAP.get(tpe),
                    factory=None,
                    definition=attrib_maker_config.definition,
                    source_field=attrib_maker_config.definition["x-size-source"],
                )
            elif attrib_name == "id":
                return AttribMaker(
                    name=attrib_name,
                    tpe=TYPES_MAP[tpe],
                    base_tpe=TYPES_MAP[tpe],
                    default=DEFAULT_MAP.get(tpe),
                    factory=None,
                    definition=attrib_maker_config.definition,
                )
            elif (
                discriminator
                and attrib_name == discriminator["propertyName"]
                and current_level == 0
            ):
                # If definition contains discriminator, current attribute equals
                # the value of discriminator.propertyName, and we are at the top level,
                # generate each discriminator mapping as an entity
                entity_map = {}
                definition_map = {}
                config_map = {}
                for config in get_discriminator_maker_config(
                    discriminator, attrib_maker_config, entity_name, attrib_name
                ):
                    generated_entity = self.register_entity(
                        entity_class_generator_config=config
                    )
                    entity_map.update({config.name: generated_entity})
                    definition_map.update({config.name: config.definition})
                    config_map.update({config.name: config})

                return DiscriminatorAttribMaker(
                    name=attrib_name,
                    tpe=TYPES_MAP[tpe],
                    base_tpe=TYPES_MAP[tpe],
                    default=None,
                    factory=None,
                    top_level_definition=attrib_maker_config.definition,
                    discriminator_property_name=discriminator["propertyName"],
                    entity_map=entity_map,
                    definition_map=definition_map,
                    config_map=config_map,
                )

            else:
                return AttribMaker(
                    name=attrib_name,
                    tpe=TYPES_MAP[tpe],
                    base_tpe=TYPES_MAP[tpe],
                    default=DEFAULT_MAP.get(tpe) if format != "uuid" else None,
                    factory=None,
                    definition=attrib_maker_config.definition,
                )
        elif is_array(definition):
            # Recursion here, we parse the items as a type
            log.trace(
                "Creating array type for entity %s and attribute %s",
                entity_name,
                attrib_name,
            )
            new_attrib_maker_config = attrib_maker_config.from_key("items")
            if not new_attrib_maker_config:
                raise OpenApiParserException(
                    "Unable to get items from array definition."
                )
            attr_maker = self.make_attrib_maker(new_attrib_maker_config)
            log.trace(
                "Creating new attribute %s.%s: FrozenSet[%s]",
                entity_name,
                attrib_name,
                attr_maker.tpe,
            )
            return AttribMaker(
                name=attr_maker.name,
                tpe=FrozenSet[attr_maker.tpe],  # type: ignore[name-defined]
                base_tpe=attr_maker.base_tpe,
                default=None,
                factory=frozenset,
                definition=new_attrib_maker_config.definition,
            )
        elif is_object(definition):
            # Indirect recursion here.
            # Those classes are never registered
            log.trace(
                "Creating object type for entity %s and attribute %s",
                entity_name,
                attrib_name,
            )
            current_level = attrib_maker_config.instance_maker_config.level
            instance_maker_config = EntityClassGeneratorConfig(
                name=attrib_name,
                entity_name=f"{entity_name}_{attrib_name.capitalize()}",
                definition=definition,
                singleton=attrib_maker_config.instance_maker_config.singleton,
                api_path=None,
                level=current_level + 1,
            )
            generated_entity = self.register_entity(
                entity_class_generator_config=instance_maker_config
            )
            log.trace(
                "Created new attribute %s.%s of type %s",
                entity_name,
                attrib_name,
                generated_entity.cls,
            )
            format = definition.get("format", None)
            if (
                format == "certificate"
                and "x-certificate-source" in attrib_maker_config.definition
            ):
                return certificate_attrib_maker(
                    name=instance_maker_config.name,
                    tpe=generated_entity.cls,
                    base_tpe=generated_entity.cls,
                    default=None,
                    factory=None,
                    definition=attrib_maker_config.definition,
                    source_field=attrib_maker_config.definition["x-certificate-source"],
                    loader=K8S_LOADER.load,
                )
            else:
                # if the object is not nullable and it does not have any required argument
                # create a factory for it.
                _factory: Optional[type] = generated_entity.cls
                if definition.get("nullable") or definition.get("required"):
                    _factory = None
                return AttribMaker(
                    name=instance_maker_config.name,
                    tpe=generated_entity.cls,
                    base_tpe=generated_entity.cls,
                    default=None,
                    factory=_factory,
                    definition=instance_maker_config.definition,
                )
        raise Exception(
            f"Unknown type for attribute {entity_name}.{attrib_name}: {definition}"
        )

    def attrib_maker(self, attrib_maker_config: AttribMakerConfig) -> AttribMaker:
        """
        Returns an attribs dictionary used later to call attrs.attrib
        """
        definition = attrib_maker_config.definition
        deprecated = definition.get("deprecated", False)
        attrib = self.make_attrib_maker(attrib_maker_config)

        if deprecated:
            required_items = attrib_maker_config.instance_maker_config.definition.get(
                "required"
            )
            required = required_items is not None and attrib.name in required_items
            if required:
                log.warning(
                    f"Attrib {attrib.name} is deprecated but required by openapi spec"
                )
                return attrib

            return DeprecatedAttribMaker(
                name=attrib.name,
                definition=attrib.definition,
                default=attrib.default,
                factory=attrib.factory,
                tpe=attrib.tpe,
                base_tpe=attrib.base_tpe,
            )

        return attrib

    def entity_class_generator(
        self, entity_class_generator_config: EntityClassGeneratorConfig
    ) -> EntityClassGenerator:
        generator = EntityClassGenerator(
            name=entity_class_generator_config.entity_name,
            attributes={
                nn: self.attrib_maker(
                    entity_class_generator_config.attrib_maker_config(n)
                )
                for n, nn in entity_class_generator_config.properties_names
            },
        )

        # Unpack definitions in discriminator and insert fields into top-level
        # entity. When loading the entity, DiscriminatorAttribMaker will perform a
        # check of the required fields of the type
        discriminator_attrs = {}
        for attrib_maker in generator.attributes.values():
            if isinstance(attrib_maker, DiscriminatorAttribMaker):
                for key, config in attrib_maker.config_map.items():
                    for name, normalized_name in config.properties_names:
                        attrib_config = AttribMakerConfig(
                            instance_maker_config=entity_class_generator_config,
                            name=name,
                            definition=config.definition["properties"][name],
                        )
                        attrib = self.attrib_maker(attrib_config)
                        discriminator_attrs.update({normalized_name: attrib})
        generator.attributes.update(discriminator_attrs)

        return generator

    def register_entity(
        self, entity_class_generator_config: EntityClassGeneratorConfig
    ) -> GeneratedEntity:
        entity_class_generator = self.entity_class_generator(
            entity_class_generator_config
        )
        generated_entity = entity_class_generator.generate(
            entity_class_generator_config
        )
        self.parser_context.register_entity(
            entity_name=entity_class_generator.name, entity=generated_entity
        )
        return generated_entity

    def parse_definition(
        self, keys: List[List[str]], entity_name: str, singleton: bool
    ) -> Optional[GeneratedEntity]:
        while True:
            errors: List[str] = []
            try:
                k: List[str] = keys.pop()
                definition = self.get_keys(k)
                break
            except OpenApiParserException as e:
                errors.append(str(e))
            except IndexError:
                raise OpenApiParserException(", ".join(errors))

        definition_to_use = None
        if is_compound(definition):
            definition_to_use = self.parse_all_of(cast(dict, definition)["allOf"])
        elif is_discriminator(definition):
            definition_to_use = self.parse_discriminator(cast(dict, definition))
        elif is_object(definition):
            definition_to_use = definition

        if not definition_to_use:
            log.error("Definition %s yet not supported", definition)
            return None
        api_path = self.parser_context.get_entity_path(entity_name)
        instance_maker_config = EntityClassGeneratorConfig(
            name=entity_name,
            entity_name=entity_name,
            definition=definition_to_use,
            singleton=singleton,
            api_path=api_path,
            level=0,
        )
        generated_entity = self.register_entity(
            entity_class_generator_config=instance_maker_config
        )
        return generated_entity
