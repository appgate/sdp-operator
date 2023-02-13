import base64
import os
import requests
from typing import Optional, Dict, List

from minio import Minio  # type: ignore

from appgate.customloaders import FileAttribLoader
from appgate.openapi.attribmaker import AttribMaker
from appgate.openapi.types import (
    AttribType,
    OpenApiDict,
    EntityClassGeneratorConfig,
    AttributesDict,
    K8S_LOADERS_FIELD_NAME,
)
from appgate.types import OperatorMode


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
        target_field: Optional[str],
    ) -> None:
        self.value = value
        self.entity_name = entity_name
        self.field_name = field_name
        self.target_field = target_field
        self.api_version = os.getenv("APPGATE_API_VERSION")

    def load_file(self) -> str:
        raise NotImplementedError()


def url_file_path(
    value: Dict, field_name: str, entity_name: str, target_field: Optional[str]
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
    if (v := value.get(field_name)) is not None:
        return v
    elif target_field is not None and (v := value.get(target_field)) is not None:
        return v
    elif value.get("name"):
        return f"{value['name']}/{field_name}"
    elif value.get("id"):
        return f"{value['id']}/{field_name}"
    else:
        raise AppgateFileException(
            f"Unable to generate url to get fetch file for field {field_name} for entity {entity_name}"
        )


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
            raise AppgateFileException("Bucket sdp does not exist on %s", address)

        try:
            response = client.get_object(bucket, object_key)
            try:
                return base64.b64encode(response.data).decode()
            finally:
                response.close()
                response.release_conn()
        except Exception as e:
            raise AppgateFileException(
                "Unable to fetch the file contents for %s: %s", e
            )


def get_appgate_file(
    value: Dict, entity_name: str, field_name: str, target_field: Optional[str]
) -> AppgateFile:
    match os.getenv("APPGATE_FILE_SOURCE", ""):
        case "http":
            return AppgateHttpFile(value, entity_name, field_name, target_field)
        case "s3":
            return AppgateS3File(value, entity_name, field_name, target_field)
        case _:
            raise AppgateFileException("Unable to create an AppgateFile")


def appgate_file_load(
    value: OpenApiDict, entity_name: str, field_name: str, target_field: Optional[str]
) -> str:
    appgate_file = get_appgate_file(
        value, entity_name, field_name=field_name, target_field=target_field
    )
    return appgate_file.load_file()


def should_load_file(operator_mode: OperatorMode) -> bool:
    return "APPGATE_FILE_SOURCE" in os.environ and operator_mode == "appgate-operator"


class FileAttribMaker(AttribMaker):
    def __init__(
        self,
        name: str,
        tpe: type,
        base_tpe: type,
        default: Optional[AttribType],
        factory: Optional[type],
        definition: OpenApiDict,
        target_field: Optional[str],
        operator_mode: OperatorMode,
    ) -> None:
        super().__init__(name, tpe, base_tpe, default, factory, definition)
        self.operator_mode = operator_mode
        self.target_field = target_field

    def values(
        self,
        attributes: Dict[str, "AttribMaker"],
        required_fields: List[str],
        instance_maker_config: EntityClassGeneratorConfig,
    ) -> AttributesDict:
        values = super().values(attributes, required_fields, instance_maker_config)
        if "metadata" not in values:
            values["metadata"] = {}
        values["metadata"][K8S_LOADERS_FIELD_NAME] = [
            FileAttribLoader(
                loader=lambda v: appgate_file_load(
                    v,
                    instance_maker_config.entity_name,
                    field_name=self.name,
                    target_field=self.target_field,
                ),
                error=lambda v: AppgateFileException(
                    f"Unable to load field {self.name} with value {instance_maker_config.name or 'unknown value'}"
                ),
                field=self.name,
                load_external=should_load_file(self.operator_mode),
            )
        ]
        return values
