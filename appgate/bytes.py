import base64
import binascii
import datetime
import hashlib
import re
from typing import Optional, Any, Dict, List, Callable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.x509 import load_pem_x509_certificate

from appgate.customloaders import CustomFieldsEntityLoader
from appgate.openapi.attribmaker import AttribMaker
from appgate.openapi.types import (
    OpenApiDict,
    AttribType,
    AttributesDict,
    K8S_LOADERS_FIELD_NAME,
    EntityClassGeneratorConfig,
    Entity_T,
    LoaderFunc,
)

__all__ = [
    "checksum_attrib_maker",
    "size_attrib_maker",
    "certificate_attrib_maker",
]


def datetime_utc(d: datetime.datetime) -> datetime.datetime:
    if not d.utcoffset():
        return d.astimezone()
    return d


def create_certificate_loader(
    loader: LoaderFunc, entity_type: type
) -> Callable[..., Any]:
    def certificate_bytes(value: Any, data: str) -> Entity_T:
        """
        Creates an Entity_T with the details of a PEM certificate.
        NOTE: Entity_T must be compatible with the fields in the dict returned here
        NOTE: We need to increase version one since:
           Version  ::=  INTEGER  {  v1(0), v2(1), v3(2)  }
        """
        cert = load_pem_x509_certificate(data.encode())
        valid_from = re.sub(
            r"\+\d\d:\d\d",
            "Z",
            datetime_utc(cert.not_valid_before).isoformat(timespec="milliseconds"),
        )
        valid_to = re.sub(
            r"\+\d\d:\d\d",
            "Z",
            datetime_utc(cert.not_valid_after).isoformat(timespec="milliseconds"),
        )
        public_key = (
            cert.public_key()
            .public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
            .decode()
            .splitlines()
        )
        del public_key[0]
        del public_key[-1]
        cert_data = {
            "version": cert.version.value + 1,
            "serial": str(cert.serial_number),
            "issuer": ", ".join(cert.issuer.rfc4514_string().split(",")),
            "subject": ", ".join(cert.subject.rfc4514_string().split(",")),
            "validFrom": valid_from,
            "validTo": valid_to,
            "fingerprint": binascii.hexlify(cert.fingerprint(hashes.SHA256())).decode(),
            "certificate": base64.b64encode(cert.public_bytes(Encoding.PEM)).decode(),
            "subjectPublicKey": "".join(public_key),
        }
        return loader(cert_data, None, entity_type)

    return certificate_bytes


def checksum_bytes(value: Any, data: str) -> str:
    bytes_decoded: bytes = base64.b64decode(data)
    return hashlib.sha256(bytes_decoded).hexdigest()


def size_bytes(value: Any, data: str) -> int:
    bytes_decoded: bytes = base64.b64decode(data)
    return len(bytes_decoded)


class BytesFieldAttribMaker(AttribMaker):
    def __init__(
        self,
        name: str,
        tpe: type,
        base_tpe: type,
        default: Optional[AttribType],
        factory: Optional[type],
        definition: OpenApiDict,
        source_field: str,
        loader: Callable[..., Any],
    ) -> None:
        super().__init__(name, tpe, base_tpe, default, factory, definition)
        self.source_field = source_field
        self.loader = loader

    def values(
        self,
        attributes: Dict[str, "AttribMaker"],
        required_fields: List[str],
        instance_maker_config: "EntityClassGeneratorConfig",
    ) -> AttributesDict:
        values = super().values(attributes, required_fields, instance_maker_config)
        values["eq"] = True
        if "metadata" not in values:
            values["metadata"] = {}
        values["metadata"][K8S_LOADERS_FIELD_NAME] = [
            CustomFieldsEntityLoader(
                loader=self.loader,
                dependencies=[self.source_field],
                field=self.name,
            )
        ]
        return values


def checksum_attrib_maker(
    name: str,
    tpe: type,
    base_tpe: type,
    default: Optional[AttribType],
    factory: Optional[type],
    definition: OpenApiDict,
    source_field: str,
) -> BytesFieldAttribMaker:
    return BytesFieldAttribMaker(
        name, tpe, base_tpe, default, factory, definition, source_field, checksum_bytes
    )


def size_attrib_maker(
    name: str,
    tpe: type,
    base_tpe: type,
    default: Optional[AttribType],
    factory: Optional[type],
    definition: OpenApiDict,
    source_field: str,
) -> BytesFieldAttribMaker:
    return BytesFieldAttribMaker(
        name, tpe, base_tpe, default, factory, definition, source_field, size_bytes
    )


def certificate_attrib_maker(
    name: str,
    tpe: type,
    base_tpe: type,
    default: Optional[AttribType],
    factory: Optional[type],
    definition: OpenApiDict,
    source_field: str,
    loader: LoaderFunc,
) -> BytesFieldAttribMaker:
    return BytesFieldAttribMaker(
        name,
        tpe,
        base_tpe,
        default,
        factory,
        definition,
        source_field,
        create_certificate_loader(loader, base_tpe),
    )
