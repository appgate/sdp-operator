from typing import Dict


class CustomObjectsApi:
    def list_namespaced_custom_object(self) -> None: ...


class V1Secret:
    data: Dict[str, str]


class CoreV1Api:
    def read_namespaced_secret(self, secret: str, key: str) -> V1Secret: ...
