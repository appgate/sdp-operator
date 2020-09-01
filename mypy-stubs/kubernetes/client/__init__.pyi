class CustomObjectsApi:
    def list_namespaced_custom_object(self) -> None: ...


class CoreV1ApiResponse:
    data: str


class CoreV1Api:
    def read_namespaced_secret(self, secret: str, key: str) -> CoreV1ApiResponse: ...
