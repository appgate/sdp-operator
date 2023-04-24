import base64
import os
import re
import uuid

import requests
from typing import Optional, Dict, List, Any, Tuple

from attr import evolve
from minio import Minio  # type: ignore

from appgate.customloaders import (
    FileAttribLoader,
    CustomEntityLoader,
)
from appgate.logger import log
from appgate.openapi.attribmaker import AttribMaker
from appgate.openapi.types import (
    AttribType,
    OpenApiDict,
    EntityClassGeneratorConfig,
    AttributesDict,
    K8S_LOADERS_FIELD_NAME,
    Entity_T,
)
from appgate.types import OperatorMode


FILE_NAME_REPLACE_REGEX_0 = re.compile(r"\s+")
FILE_NAME_REPLACE_REGEX_1 = re.compile(r"-+")


class AppgateFileException(Exception):
    pass


class AppgateFile:
    """
    AppgateFile base abstract class. Every file field in an entity will
    be an AppgateFile instance that will be able to load its value
    """

    def __init__(
        self,
        value: Dict,
        entity_name: str,
        field_name: str,
        target_fields: Tuple[str, ...],
    ) -> None:
        self.value = value
        self.entity_name = entity_name
        self.field_name = field_name
        self.target_field = target_fields
        self.api_version = os.getenv("APPGATE_API_VERSION")

    def load_file(self) -> str:
        raise NotImplementedError()


def normalize_url_file_path(url_path: str) -> str:
    return FILE_NAME_REPLACE_REGEX_1.sub(
        "-", FILE_NAME_REPLACE_REGEX_0.sub("-", url_path).replace("-+", "-")
    ).lower()


def url_file_path(
    value: Dict,
    field_name: str,
    entity_name: str,
    target_fields: Tuple[str, ...],
) -> str:
    """
    Function to compute the url from where to get the bytes.
    It supports:
    1. If the field contains some value, use it as the url path
    2. else if it has a target field (x-filename, x-checksum for now) use the contents
    3. else if the entity has a name, use it to compute the path url `name/fieldName`
    4. else if the entity has an id, use it to compute the path url `id/fieldName`
    5. else raise an exception
    """
    v = value.get(field_name)
    if v is not None and isinstance(v, str):
        return normalize_url_file_path(v)
    for field in target_fields:
        if v := value.get(field):
            return v
    if value.get("name"):
        return f"{normalize_url_file_path(value['name'])}/{field_name}"
    if value.get("id"):
        return f"{value['id']}/{field_name}"

    log.warning(
        f"Unable to generate url to get fetch file for field {field_name} for entity {entity_name}"
    )
    return str(uuid.uuid4())


class AppgateHttpFile(AppgateFile):
    def load_file(self) -> str:
        contents_field = url_file_path(
            self.value, self.field_name, self.entity_name, self.target_field
        )
        file_key = f"{self.entity_name.lower()}-{self.api_version}/{contents_field}"
        address = os.getenv("APPGATE_FILE_HTTP_ADDRESS")
        file_url = f"{address}/{file_key}"
        try:
            response = requests.get(file_url)
            response.raise_for_status()
            return base64.b64encode(response.content).decode()
        except Exception as e:
            raise AppgateFileException(
                "Unable to fetch the file contents for %s: %s", file_url, e
            )


class AppgateS3File(AppgateFile):
    def load_file(self) -> str:
        address = os.getenv("APPGATE_FILE_S3_ADDRESS", "localhost")
        access_key = os.getenv("APPGATE_S3_ACCESS_KEY")
        secret_key = os.getenv("APPGATE_S3_SECRET_KEY")
        secure = os.getenv("APPGATE_S3_SSL_NO_VERIFY") == "false"

        client = Minio(
            endpoint=address,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        bucket = "sdp"
        contents_field = url_file_path(
            self.value, self.field_name, self.entity_name, self.target_field
        )
        object_key = f"{self.entity_name.lower()}-{self.api_version}/{contents_field}"

        if not client.bucket_exists(bucket):
            raise AppgateFileException(f"Bucket sdp does not exist on {address}")

        try:
            response = client.get_object(bucket, object_key)
            try:
                return base64.b64encode(response.data).decode()
            finally:
                response.close()
                response.release_conn()
        except Exception as e:
            raise AppgateFileException(
                f"Unable to fetch the file contents for {bucket}/{object_key}: {e}"
            )


def get_appgate_file(
    value: Dict,
    entity_name: str,
    field_name: str,
    target_fields: Tuple[str, ...],
) -> AppgateFile:
    match os.getenv("APPGATE_FILE_SOURCE", ""):
        case "http":
            return AppgateHttpFile(value, entity_name, field_name, target_fields)
        case "s3":
            return AppgateS3File(value, entity_name, field_name, target_fields)
        case _:
            raise AppgateFileException("Unable to create an AppgateFile")


def appgate_file_load(
    value: OpenApiDict,
    entity_name: str,
    field_name: str,
    target_fields: Tuple[str, ...],
) -> str:
    appgate_file = get_appgate_file(
        value, entity_name, field_name=field_name, target_fields=target_fields
    )
    return appgate_file.load_file()


def should_load_file(operator_mode: OperatorMode) -> bool:
    return "APPGATE_FILE_SOURCE" in os.environ and operator_mode == "appgate-operator"


def set_appgate_file_metadata(
    value: OpenApiDict,
    entity: Entity_T,
    entity_name: str,
    field_name: str,
    target_fields: Tuple[str, ...],
) -> Entity_T:
    api_version = os.getenv("APPGATE_API_VERSION")
    contents_field = url_file_path(value, field_name, entity_name, target_fields)
    object_key = f"{entity_name.lower()}-{api_version}/{contents_field}"
    appgate_mt = entity.appgate_metadata.with_url_file_path(object_key)
    return evolve(entity, appgate_metadata=appgate_mt)


class FileAttribMaker(AttribMaker):
    def __init__(
        self,
        name: str,
        tpe: type,
        base_tpe: type,
        default: Optional[AttribType],
        factory: Optional[type],
        definition: OpenApiDict,
        target_fields: Tuple[str, ...],
        operator_mode: OperatorMode,
    ) -> None:
        super().__init__(name, tpe, base_tpe, default, factory, definition)
        self.operator_mode = operator_mode
        self.target_fields = target_fields

    def values(
        self,
        attributes: Dict[str, "AttribMaker"],
        required_fields: List[str],
        instance_maker_config: EntityClassGeneratorConfig,
    ) -> AttributesDict:
        def name_or_id(values: dict[str, Any]) -> str:
            if name := values.get("name"):
                return f" [{name}]"
            if id := values.get("id"):
                return f" [{id}]"
            return ""

        values = super().values(attributes, required_fields, instance_maker_config)
        if "metadata" not in values:
            values["metadata"] = {}
        values["metadata"][K8S_LOADERS_FIELD_NAME] = [
            FileAttribLoader(
                loader=lambda v: appgate_file_load(
                    v,
                    instance_maker_config.entity_name,
                    field_name=self.name,
                    target_fields=self.target_fields,
                ),
                error=lambda v: AppgateFileException(
                    f"Unable to load field {self.name} for entity {instance_maker_config.name}{name_or_id(v)}."
                ),
                field=self.name,
                is_appgate_operator_mode=self.operator_mode == "appgate-operator",
                is_external_store_configured="APPGATE_FILE_SOURCE" in os.environ,
            ),
            CustomEntityLoader(
                loader=lambda v, e: set_appgate_file_metadata(
                    v,
                    e,
                    entity_name=instance_maker_config.entity_name,
                    field_name=self.name,
                    target_fields=self.target_fields,
                ),
            ),
        ]
        return values
