import base64
import os
import requests
from typing import Optional, Dict, List

from minio import Minio  # type: ignore

from appgate.appgate import OperatorMode
from appgate.customloaders import FileAttribLoader
from appgate.openapi.attribmaker import AttribMaker
from appgate.openapi.types import (
    AttribType,
    OpenApiDict,
    EntityClassGeneratorConfig,
    AttributesDict,
    K8S_LOADERS_FIELD_NAME,
)


class AppgateFileException(Exception):
    pass


class AppgateFile:
    """
    AppgateFile base abstract class. Every file field in an entity will
    be an AppgateFile instance that will be able to load its value
    """

    def __init__(self, value: Dict, entity_name: str) -> None:
        self.value = value
        self.entity_name = entity_name
        self.api_version = os.getenv("APPGATE_API_VERSION")

    def load_file(self) -> str:
        raise NotImplementedError()


class AppgateHttpFile(AppgateFile):
    def load_file(self) -> str:
        file_key = f"{self.entity_name.lower()}-{self.api_version}/{self.value.get('filename')}"
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
        object_key = f"{self.entity_name.lower()}-{self.api_version}/{self.value.get('filename')}"

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


def get_appgate_file(value: Dict, entity_name: str) -> AppgateFile:
    match os.getenv("APPGATE_FILE_SOURCE", ""):
        case "http":
            return AppgateHttpFile(value, entity_name)
        case "s3":
            return AppgateS3File(value, entity_name)
        case _:
            raise AppgateFileException("Unable to create an AppgateFile")


def appgate_file_load(value: OpenApiDict, entity_name: str) -> str:
    appgate_file = get_appgate_file(value, entity_name)
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
        operator_mode: OperatorMode,
    ) -> None:
        super().__init__(name, tpe, base_tpe, default, factory, definition)
        self.operator_mode = operator_mode

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
                    v, instance_maker_config.entity_name
                ),
                field=self.name,
                load_external=should_load_file(self.operator_mode),
            )
        ]
        return values
