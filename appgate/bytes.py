import base64
import datetime
import hashlib
from typing import Optional, Any, Dict, List, Callable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.x509 import load_pem_x509_certificate

from appgate.customloaders import CustomFieldsEntityLoader
from appgate.openapi.attribmaker import SimpleAttribMaker
from appgate.openapi.types import OpenApiDict, AttribType, AttributesDict, \
    K8S_LOADERS_FIELD_NAME, InstanceMakerConfig, Entity_T, LoaderFunc

__all__ = [
    'checksum_attrib_maker',
    'size_attrib_maker',
    'certificate_attrib_maker',
]


def datetime_utc(d: datetime.datetime) -> datetime.datetime:
    if not d.utcoffset():
        return d.astimezone()
    return d


def create_certificate_loader(loader: LoaderFunc, entity_type: type) -> Callable[..., Any]:

    def certificate_bytes(value: Any, data: str) -> Entity_T:
        cert = load_pem_x509_certificate(data.encode())  # type: ignore
        cert_data = {
            'version': cert.version.value,
            'serial': str(cert.serial_number),
            'issuer': cert.issuer.rfc4514_string(),
            'subject': cert.subject.rfc4514_string(),
            'validFrom': datetime_utc(cert.not_valid_before).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            'validTo': datetime_utc(cert.not_valid_after).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            'fingerprint': base64.b64encode(cert.fingerprint(hashes.SHA256())).decode(),
            'certificate': base64.b64encode(cert.public_bytes(Encoding.PEM)).decode(),
            'subjectPublicKey': base64.b64encode(cert.public_key().public_bytes(
                Encoding.PEM,
                PublicFormat.SubjectPublicKeyInfo)).decode(),
        }
        return loader(cert_data, None, entity_type)
    return certificate_bytes


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


def certificate_attrib_maker(name: str, tpe: type, base_tpe: type, default: Optional[AttribType],
                             factory: Optional[type], definition: OpenApiDict,
                             source_field: str,
                             loader: LoaderFunc) -> BytesFieldAttribMaker:
    return BytesFieldAttribMaker(name, tpe, base_tpe, default, factory, definition, source_field,
                                 create_certificate_loader(loader, base_tpe))
