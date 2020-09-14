import base64
import hashlib
from typing import Optional, Any, Dict, List, Callable

from appgate.customloaders import CustomFieldsEntityLoader
from appgate.openapi.attribmaker import SimpleAttribMaker
from appgate.openapi.types import OpenApiDict, AttribType, AttributesDict, K8S_LOADERS_FIELD_NAME, InstanceMakerConfig


__all__ = [
    'checksum_attrib_maker',
    'size_attrib_maker'
]


def checksum_bytes(value: Any, data: str) -> str:
    bytes_decoded: bytes = base64.b64decode(data)
    return hashlib.sha256(bytes_decoded).hexdigest()


def size_bytes(value: Any, data: str) -> int:
    bytes_decoded: bytes = base64.b64decode(data)
    return len(bytes_decoded)


class BytesFieldAttribMaker(SimpleAttribMaker):
    def __init__(self, name: str, tpe: type, base_tpe: type, default: Optional[AttribType],
                 factory: Optional[type], definition: OpenApiDict,
                 source_field: str,
                 loader: Callable[..., Any]) -> None:
        super().__init__(name, tpe, base_tpe, default, factory, definition)
        self.source_field = source_field
        self.loader = loader

    def values(self, attributes: Dict[str, 'SimpleAttribMaker'], required_fields: List[str],
               instance_maker_config: 'InstanceMakerConfig') -> AttributesDict:
        values = super().values(attributes, required_fields, instance_maker_config)
        values['eq'] = True
        if 'metadata' not in values:
            values['metadata'] = {}
        values['metadata'][K8S_LOADERS_FIELD_NAME] = [CustomFieldsEntityLoader(
            loader=self.loader,
            dependencies=[self.source_field],
            field=self.name,
        )]
        return values


def checksum_attrib_maker(name: str, tpe: type, base_tpe: type, default: Optional[AttribType],
                          factory: Optional[type], definition: OpenApiDict,
                          source_field: str) -> BytesFieldAttribMaker:
    return BytesFieldAttribMaker(name, tpe, base_tpe, default, factory, definition, source_field,
                                 checksum_bytes)


def size_attrib_maker(name: str, tpe: type, base_tpe: type, default: Optional[AttribType],
                      factory: Optional[type], definition: OpenApiDict,
                      source_field: str) -> BytesFieldAttribMaker:
    return BytesFieldAttribMaker(name, tpe, base_tpe, default, factory, definition, source_field,
                                 size_bytes)
