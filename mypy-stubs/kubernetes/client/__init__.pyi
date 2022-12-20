from typing import Dict, Optional


class CustomObjectsApi:
    def list_namespaced_custom_object(self) -> None: ...
    def delete_namespaced_custom_object(self, group: str, version: str, namespace: str, plural: str, name: str) -> V1ConfigMap: ...

class V1Secret:
    data: Dict[str, str]


class V1ObjectMeta:
    pass


class V1ConfigMap:
    def __init__(self, kind: str, api_version: str, data: Dict[str, Optional[str]],
                 metadata: Optional[V1ObjectMeta] = None) -> None: ...
    kind: str
    api_version: str
    metadata: Optional[V1ObjectMeta]
    data: Dict[str, str]


class CoreV1Api:
    def read_namespaced_secret(self, name: str, namespace: str) -> V1Secret: ...
    def read_namespaced_config_map(self, name: str, namespace: str) -> V1ConfigMap: ...
    def patch_namespaced_config_map(self, name: str, namespace: str, body: V1ConfigMap) -> V1ConfigMap: ...
