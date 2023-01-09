import base64
import os
import requests  # type: ignore
from typing import Optional, Dict, List

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

    @staticmethod
    def isinstance() -> bool:
        raise NotImplementedError()


class AppgateGenericFile(AppgateFile):
    def load_file(self) -> str:
        file_key = f"{self.entity_name.lower()}-{self.api_version}/{self.value.get('filename')}"
        address = os.getenv("APPGATE_FILE_GENERIC_ADDRESS")
        file_url = f"{address}/{file_key}"
        response = requests.get(file_url)
        return base64.b64encode(response.content).decode()

    @staticmethod
    def isinstance() -> bool:
        return os.getenv("APPGATE_FILE_SOURCE", "") == "generic"


def get_appgate_file(value: Dict, entity_name: str) -> AppgateFile:
    if AppgateGenericFile.isinstance():
        return AppgateGenericFile(value, entity_name)
    raise AppgateFileException("Unable to create an AppgateFile")


def appgate_file_load(value: OpenApiDict, entity_name: str) -> str:
    appgate_file = get_appgate_file(value, entity_name)
    return appgate_file.load_file()


class FileAttribMaker(AttribMaker):
    def values(
        self,
        attributes: Dict[str, "AttribMaker"],
        required_fields: List[str],
        instance_maker_config: EntityClassGeneratorConfig,
    ) -> AttributesDict:
        values = super().values(attributes, required_fields, instance_maker_config)
        values["eq"] = False
        if "metadata" not in values:
            values["metadata"] = {}
        values["metadata"][K8S_LOADERS_FIELD_NAME] = [
            FileAttribLoader(
                loader=lambda v: appgate_file_load(
                    v, instance_maker_config.entity_name
                ),
                field=self.name,
                load_external="APPGATE_FILE_SOURCE" in os.environ,
            )
        ]
        return values


def file_attrib_maker(
    name: str,
    tpe: type,
    base_tpe: type,
    default: Optional[AttribType],
    factory: Optional[type],
    definition: OpenApiDict,
) -> FileAttribMaker:
    return FileAttribMaker(
        name,
        tpe,
        base_tpe,
        default,
        factory,
        definition,
    )
