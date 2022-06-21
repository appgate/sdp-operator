from uuid import uuid4
from typing import Optional, Dict, Any, List

from appgate.openapi.types import (
    OpenApiDict,
    AttribType,
    AttributesDict,
    IGNORED_EQ_ATTRIBUTES,
    OpenApiParserException,
    EntityClassGeneratorConfig,
    UUID_REFERENCE_FIELD,
)

write_only_formats = {"password"}


class AttribMaker:
    """
    This class represents how to create a basic attribute in a final EntityClassGenerated.
    """

    def __init__(
        self,
        name: str,
        tpe: type,
        base_tpe: type,
        default: Optional[AttribType],
        factory: Optional[type],
        definition: OpenApiDict,
        repr: bool = True,
        read_only: Optional[bool] = None,
        write_only: Optional[bool] = None,
    ) -> None:
        self.base_tpe = base_tpe
        self.name = name
        self.tpe = tpe
        self.default = default
        self.factory = factory
        self.repr = repr
        self.definition = definition
        self.read_only = read_only
        self.write_only = write_only

    @property
    def metadata(self) -> Dict[str, Any]:
        """
        Return the metadata for this attribute
        """
        return self.definition.get("metadata", {})

    @property
    def is_password(self) -> bool:
        """
        Predicate to check if attrs is a password
        """
        return False

    @property
    def has_default(self) -> bool:
        """
        Predicate to check if attrs as a default field value
        """
        return self.factory is not None or self.default is not None

    def values(
        self,
        attributes: Dict[str, "AttribMaker"],
        required_fields: List[str],
        instance_maker_config: EntityClassGeneratorConfig,
    ) -> AttributesDict:
        """
        Return the dictionary of values for this attribute. This will be used later
        to create entity classes.
        """
        required = self.name in required_fields
        nullable = self.definition.get("nullable", False)
        definition = self.definition
        if self.read_only:
            read_only = self.read_only
        else:
            read_only = definition.get("readOnly", False)
        format = definition.get("format")
        if self.write_only:
            write_only = self.write_only
        elif type(format) is not dict and format in write_only_formats:
            write_only = True
        else:
            write_only = definition.get("writeOnly", False)
        if instance_maker_config.level == 0 and self.name == "id":
            # We dont want to save id on k8s
            read_only = True

        attribs: AttributesDict = {}
        attribs["metadata"] = {
            "name": self.name,
            "readOnly": read_only,
            "writeOnly": write_only,
            "format": format,
            "base_type": self.base_tpe,
        }
        if "description" in definition:
            attribs["metadata"]["description"] = definition["description"]
        if "example" in definition:
            if isinstance(definition["example"], List):
                attribs["metadata"]["example"] = frozenset(definition["example"])
            else:
                attribs["metadata"]["example"] = definition["example"]
        if UUID_REFERENCE_FIELD in definition:
            attribs["metadata"][UUID_REFERENCE_FIELD] = definition[UUID_REFERENCE_FIELD]

        if self.name in IGNORED_EQ_ATTRIBUTES or write_only or read_only:
            attribs["eq"] = False

        # Set type
        if (not required and nullable) or read_only or write_only:
            attribs["type"] = Optional[self.tpe]
            attribs["metadata"]["type"] = str(Optional[self.tpe])
        elif required and (read_only or write_only):
            raise OpenApiParserException(
                f"readOnly/writeOnly attribute {self.name} " "can not be required"
            )
        else:
            attribs["type"] = self.tpe
            attribs["metadata"]["type"] = str(self.tpe)

        if instance_maker_config.level == 0 and self.name == "id":
            attribs["factory"] = lambda: str(uuid4())
        elif self.factory and not (read_only or write_only):
            attribs["factory"] = self.factory
        elif not required or read_only or write_only:
            attribs["default"] = definition.get(
                "default", None if (read_only or write_only) else self.default
            )
        attribs["repr"] = self.repr
        return attribs


class DeprecatedAttribMaker(AttribMaker):
    pass


class DefaultAttribMaker(AttribMaker):
    def values(
        self,
        attributes: Dict[str, "AttribMaker"],
        required_fields: List[str],
        instance_maker_config: EntityClassGeneratorConfig,
    ) -> AttributesDict:
        vs = {
            "type": Optional[self.tpe],
            "eq": False,
            "metadata": {
                "base_type": self.tpe,
                "name": self.name,
            },
            "repr": self.repr,
        }
        if self.read_only and "metadata" in vs:
            vs["metadata"]["readOnly"] = self.read_only
        if self.write_only and "metadata" in vs:
            vs["metadata"]["writeOnly"] = self.write_only
        if self.default:
            vs["default"] = self.default
            vs["type"] = self.tpe
        elif self.factory:
            vs["factory"] = self.factory
            vs["type"] = self.tpe
        return vs


def create_default_attrib(
    name: str, attrib_value: Any, write_only: bool = False, read_only: bool = False
) -> DefaultAttribMaker:
    return DefaultAttribMaker(
        tpe=type(attrib_value),
        base_tpe=type(attrib_value),
        name=name,
        default=attrib_value,
        factory=None,
        definition={},
        read_only=read_only,
        write_only=write_only,
    )
