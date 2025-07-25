import asyncio
import datetime
import functools
import ssl
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Type
from urllib.parse import urljoin

import aiohttp
from aiohttp import InvalidURL, ClientConnectorCertificateError, ClientConnectorError
from kubernetes.client import (
    CoreV1Api,
    V1ConfigMap,
    V1ObjectMeta,
    CustomObjectsApi,
)
from kubernetes.client.exceptions import ApiException

from attr import attrib, attrs

from appgate.attrs import (
    APPGATE_DUMPER,
    APPGATE_LOADER,
    parse_datetime,
    dump_datetime,
    K8S_DUMPER,
    k8s_name,
)
from appgate.logger import log
from appgate.openapi.types import Entity_T, AppgateException, APISpec, EntityDumper
from appgate.types import (
    LatestEntityGeneration,
    EntityClient,
    crd_domain,
)

__all__ = [
    "AppgateClient",
    "AppgateEntityClient",
    "K8SConfigMapClient",
    "entity_unique_id",
    "K8sEntityClient",
]


def get_plural(kind: str) -> str:
    entity_name = kind.lower()
    if entity_name.endswith("y"):
        return f"{entity_name[:-1]}ies"
    else:
        return f"{entity_name}s"


@functools.cache
def plural(kind):
    return get_plural(kind)


@attrs(frozen=True)
class K8sEntityClient(EntityClient):
    k8s_api: CustomObjectsApi = attrib()
    api_spec: APISpec = attrib(hash=False)
    crd_version: str = attrib()
    namespace: str = attrib()
    kind: str = attrib()

    @functools.cache
    def crd_domain(self) -> str:
        return crd_domain(self.api_spec.api_version)

    @functools.cache
    def dumper(self) -> EntityDumper:
        return K8S_DUMPER(self.api_spec)

    async def create(self, e: Entity_T) -> EntityClient:
        log.info("[k8s-entity-client/%s] Creating k8s entity %s", self.kind, e.name)
        self.k8s_api.create_namespaced_custom_object(  # type: ignore
            self.crd_domain(),
            self.crd_version,
            self.namespace,
            plural(self.kind),
            self.dumper().dump(e, True, None),
        )
        return self

    async def delete(self, e: Entity_T) -> EntityClient:
        log.info("[k8s-entity-client/%s] Deleting k8s entity %s", self.kind, e.name)
        self.k8s_api.delete_namespaced_custom_object(
            self.crd_domain(),
            self.crd_version,
            self.namespace,
            plural(self.kind),
            k8s_name(e.name),
        )
        return self

    async def modify(self, e: Entity_T) -> EntityClient:
        log.info("[k8s-entity-client/%s] Updating k8s entity %s", self.kind, e.name)
        data = self.dumper().dump(e, True, None)
        self.k8s_api.patch_namespaced_custom_object(  # type: ignore
            self.crd_domain(),
            self.crd_version,
            self.namespace,
            plural(self.kind),
            k8s_name(e.name),
            data,
        )
        return self


class AppgateEntityClient(EntityClient):
    def __init__(
        self,
        path: str,
        appgate_client: "AppgateClient",
        singleton: bool,
        load: Callable[[Dict[str, Any]], Entity_T],
        dump: Callable[[Entity_T], Dict[str, Any]],
        kind: str,
        magic_entities: Optional[List[Entity_T]] = None,
        dry_run: bool = False,
    ) -> None:
        self._client = appgate_client
        self.path = path
        self.load = load
        self.dump = dump
        self.singleton = singleton
        self.magic_entities = magic_entities
        self.dry_run = dry_run
        self.kind = kind

    async def get(self) -> Optional[List[Entity_T]]:
        data = await self._client.get(self.path)
        if not data:
            log.error(
                "[aggpate-client] GET %s :: Expecting a response but we got empty data",
                self.path,
            )
            return None
        # TODO: We should discover this from the api spec
        entities = None
        if "data" in data:
            entities = [self.load(e) for e in data["data"]]
        else:
            entities = [self.load(data)]
        if self.magic_entities:
            return entities + self.magic_entities
        return entities

    async def create(self, entity: Entity_T) -> EntityClient:
        await self.post(entity)
        return self

    async def post(self, entity: Entity_T) -> Optional[Entity_T]:
        log.info(
            "[appgate-client/%s] POST %s [%s]",
            self.kind,
            entity.name,
            entity.id,
        )
        if self.dry_run:
            return None
        body = self.dump(entity)
        body["id"] = entity.id
        data = await self._client.post(self.path, body=body)
        if not data:
            log.error(
                "[aggpate-client] POST %s :: Expecting a response but we got empty data",
                self.path,
            )
            return None
        return self.load(data)

    async def modify(self, entity: Entity_T) -> EntityClient:
        await self.put(entity)
        return self

    async def put(self, entity: Entity_T) -> Optional[Entity_T]:
        log.info(
            "[appgate-client/%s] PUT %s [%s]",
            self.kind,
            entity.name,
            entity.id,
        )
        if self.dry_run:
            return None
        path = f"{self.path}/{entity.id}"
        if self.singleton:
            path = self.path
        data = await self._client.put(path, body=self.dump(entity))
        if not data:
            return None
        return self.load(data)

    async def delete(self, e: Entity_T) -> EntityClient:
        log.info(
            "[appgate-client/%s] DELETE [%s]",
            self.kind,
            e.id,
        )
        if self.dry_run:
            return self
        await self._client.delete(f"{self.path}/{e.id}")
        return self


def load_latest_entity_generation(key: str, value: str) -> LatestEntityGeneration:
    try:
        generation, modified = value.split(",", maxsplit=2)
        return LatestEntityGeneration(
            generation=int(generation), modified=parse_datetime(modified)
        )
    except Exception:
        log.error(
            "Error getting entry from configmap entry %s, defaulting to generation 0",
            key,
        )
        return LatestEntityGeneration()


def dump_latest_entity_generation(entry: LatestEntityGeneration) -> str:
    return f"{entry.generation},{dump_datetime(entry.modified)}"


def entity_unique_id(entity_type: str, name: str) -> str:
    name = name.replace(" ", "").lower()
    return f"{entity_type}-{name}"


class K8SConfigMapClient:
    def __init__(self, namespace: str, name: str) -> None:
        self._v1 = CoreV1Api()
        self._configmap_mt: Optional[V1ObjectMeta] = None
        self.namespace = namespace
        self.name = name
        # Store configmap data locally as a key-value store of strings,
        # convert to and from higher level types at the boundaries.
        self._data: Dict[str, str] = {}

    async def init(self) -> None:
        log.info(
            "[k8s-configmap-client/%s/%s] Initializing config-map %s",
            self.name,
            self.namespace,
            self.name,
        )

        def get_configmap() -> Optional[V1ConfigMap]:
            try:
                return self._v1.read_namespaced_config_map(
                    name=self.name, namespace=self.namespace
                )
            except ApiException as e:
                if e.status == 404:  # type: ignore
                    return None
                raise e

        def initialize_configmap() -> V1ConfigMap:
            configmap = get_configmap()
            if configmap is None:
                body = V1ConfigMap(
                    api_version="v1",
                    kind="ConfigMap",
                    metadata=V1ObjectMeta(name=self.name, namespace=self.namespace),  # type: ignore
                    data={},
                )
                log.info(
                    "[k8s-configmap-client/%s] Creating configmap %s",
                    self.namespace,
                    self.name,
                )
                return self._v1.create_namespaced_config_map(  # type: ignore
                    body=body, namespace=self.namespace
                )
            return configmap

        try:
            configmap = await asyncio.to_thread(initialize_configmap)
            self._configmap_mt = configmap.metadata
            self._data = configmap.data or {}
        except ApiException as e:
            raise AppgateException(f"Error initializing configmap: {e.body}")

    @staticmethod
    def _entry_key(key: str) -> str:
        return f"entry.{key}"

    @staticmethod
    def _device_id_key() -> str:
        return "device-id"

    async def _patch_key(
        self, key: str, value: Optional[str]
    ) -> Optional[V1ObjectMeta]:
        body = V1ConfigMap(
            api_version="v1",
            kind="ConfigMap",
            data={
                key: value,
            },
        )
        configmap = await asyncio.to_thread(
            self._v1.patch_namespaced_config_map,
            name=self.name,
            namespace=self.namespace,
            body=body,
        )
        return configmap.metadata

    async def _update_key(self, key: str, value: str) -> Optional[V1ObjectMeta]:
        return await self._patch_key(key, value)

    async def _delete_key(self, key: str) -> Optional[V1ObjectMeta]:
        return await self._patch_key(key, None)

    async def ensure_device_id(self) -> str:
        """
        Try to get the device id from the config map.
        If that fails, generate one and store it in the configmap.
        """
        try:
            return self._data[self._device_id_key()]
        except KeyError:
            device_id = str(uuid.uuid4())
            self._data[self._device_id_key()] = device_id

        log.info(
            "[k8s-configmap-client/%s/%s] Saving device id: %s",
            self.name,
            self.namespace,
            device_id,
        )
        self._configmap_mt = await self._update_key("device-id", device_id)
        return device_id

    def get_entity_generation(self, key: str) -> Optional[LatestEntityGeneration]:
        entry_key = self._entry_key(key)
        if (value := self._data.get(entry_key)) is None:
            return None
        return load_latest_entity_generation(key, value)

    def read_entity_generation(self, key: str) -> Optional[LatestEntityGeneration]:
        entry = self.get_entity_generation(key)
        log.warning(
            "[k8s-configmap-client/%s/%s] Reading entity generation %s: %s",
            self.name,
            self.namespace,
            key,
            dump_latest_entity_generation(entry) if entry else "not found",
        )
        return entry

    async def update_entity_generation(
        self, key: str, generation: Optional[int]
    ) -> Optional[LatestEntityGeneration]:
        if not self._configmap_mt:
            await self.init()
        prev_entry = self.get_entity_generation(key) or LatestEntityGeneration()
        entry = LatestEntityGeneration(
            generation=generation or (prev_entry.generation + 1),
            modified=datetime.datetime.now().astimezone(),
        )
        gen = dump_latest_entity_generation(entry)
        entry_key = self._entry_key(key)
        self._data[entry_key] = gen
        log.info(
            "[k8s-configmap-client/%s/%s] Updating entity generation %s -> %s",
            self.name,
            self.namespace,
            key,
            gen,
        )
        self._configmap_mt = await self._update_key(entry_key, gen)
        return entry

    async def delete_entity_generation(
        self, key: str
    ) -> Optional[LatestEntityGeneration]:
        if not self._configmap_mt:
            await self.init()
        entry_key = self._entry_key(key)
        if entry_key not in self._data:
            return None
        entry = self.get_entity_generation(key)
        del self._data[entry_key]
        log.info(
            "[k8s-configmap-client/%s/%s] Deleting entity generation %s",
            self.name,
            self.namespace,
            key,
        )
        self._configmap_mt = await self._delete_key(entry_key)
        return entry


class AppgateClient:
    def __init__(
        self,
        controller: str,
        user: str,
        password: str,
        provider: str,
        version: int,
        device_id: str,
        dry_run: bool,
        expiration_time_delta: int,
        no_verify: bool = False,
        cafile: Optional[Path] = None,
    ) -> None:
        self.controller = controller
        self.user = user
        self.password = password
        self.provider = provider
        self._session = aiohttp.ClientSession()
        self.device_id = device_id
        self._token = None
        self._expiration_time: float | None = None
        self.version = version
        self.no_verify = no_verify
        self.ssl_context = (
            ssl.create_default_context(cafile=str(cafile)) if cafile else None
        )
        self._expiration_time_delta = expiration_time_delta
        self.dry_run = dry_run

    async def close(self) -> None:
        await self._session.close()

    async def __aenter__(self) -> "AppgateClient":
        try:
            await self.login()
        except Exception as e:
            await self.close()
            raise e
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def auth_header(self) -> Optional[str]:
        if (
            self._expiration_time
            and datetime.datetime.now().timestamp() >= self._expiration_time
        ):
            log.info("[appgate-client] Renewing auth token")
            await self.login()
        if self._token:
            return f"Bearer {self._token}"
        return None

    async def request(
        self,
        verb: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        should_retry: bool = True,
    ) -> Optional[Dict[str, Any]]:
        verbs = {
            "POST": self._session.post,
            "DELETE": self._session.delete,
            "PUT": self._session.put,
            "GET": self._session.get,
        }
        method = verbs.get(verb)
        if not method:
            raise AppgateException(f"Unknown HTTP method: {verb}")
        headers = {
            "Accept": f"application/vnd.appgate.peer-v{self.version}+json",
            "Content-Type": "application/json",
        }
        auth_header = await self.auth_header()
        if auth_header:
            headers["Authorization"] = auth_header
        url = urljoin(self.controller.rstrip("/") + "/", path.lstrip("/"))
        try:
            async with method(
                url=url,  # type: ignore
                headers=headers,
                json=data,
                ssl=self.ssl_context,  # type: ignore
                verify_ssl=not self.no_verify,
            ) as resp:
                status_code = resp.status // 100
                if status_code == 2:
                    if resp.status == 204:
                        return {}
                    else:
                        return await resp.json()
                else:
                    error_data = await resp.text()
                    log.error(
                        "[aggpate-client] %s :: %s: %s", url, resp.status, error_data
                    )
                    if resp.status in [401, 403]:
                        # Renew the token and retry again if needed
                        if should_retry:
                            await self.login()
                            return await self.request(
                                verb=verb, path=path, data=data, should_retry=False
                            )
                    raise AppgateException(
                        f"Error: [{method} {url} {resp.status}] {error_data}"
                    )
        except InvalidURL:
            log.error("[appgate-client] Error preforming query: %s", url)
            raise AppgateException(f"Error: [{method} {url}] InvalidURL")
        except ClientConnectorCertificateError as e:
            log.error(
                "[appgate-client] Certificate error when connecting to %s: %s",
                e.host,
                e.certificate_error,
            )
            raise AppgateException(f"Error: {e.certificate_error}")
        except ClientConnectorError as e:
            log.error(
                "[appgate-client] Error establishing connection with %s: %s",
                e.host,
                e.strerror,
            )
            raise AppgateException(f"Error: {e.strerror}")

    async def post(
        self, path: str, body: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        return await self.request("POST", path=path, data=body)

    async def get(self, path: str) -> Optional[Dict[str, Any]]:
        return await self.request("GET", path=path)

    async def put(
        self, path: str, body: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        return await self.request("PUT", path=path, data=body)

    async def delete(
        self, path: str, body: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        return await self.request("DELETE", path=path, data=body)

    async def login(self) -> None:
        body = {
            "providerName": self.provider,
            "username": self.user,
            "password": self.password,
            "deviceId": self.device_id,
        }
        resp = await self.post("admin/login", body=body)
        if resp:
            self._token = resp["token"]
            self._expiration_time = (
                datetime.datetime.strptime(
                    resp["expires"].split(".")[0], "%Y-%m-%dT%H:%M:%S"
                ).timestamp()
                - self._expiration_time_delta
            )

    @property
    def authenticated(self) -> bool:
        return self._token is not None

    def entity_client(
        self,
        entity: Type[Entity_T],
        api_path: str,
        singleton: bool,
        magic_entities: Optional[List[Entity_T]],
    ) -> AppgateEntityClient:
        dumper = APPGATE_DUMPER
        return AppgateEntityClient(
            appgate_client=self,
            path=f"/admin/{api_path}",
            singleton=singleton,
            load=lambda d: APPGATE_LOADER.load(d, None, entity),
            dump=lambda e: dumper.dump(e, True, None),
            magic_entities=magic_entities,
            kind=entity.__qualname__,
            dry_run=self.dry_run,
        )
