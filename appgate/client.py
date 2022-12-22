import asyncio
import datetime
import functools
import ssl
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
import aiohttp
from aiohttp import InvalidURL, ClientConnectorCertificateError, ClientConnectorError
from kubernetes.client import CoreV1Api, V1ConfigMap, V1ObjectMeta, CustomObjectsApi
from kubernetes.client.exceptions import ApiException

from attr import attrib, attrs

from appgate.attrs import APPGATE_DUMPER, APPGATE_LOADER, parse_datetime, dump_datetime
from appgate.logger import log
from appgate.openapi.types import Entity_T, AppgateException
from appgate.types import LatestEntityGeneration, EntityWrapper, dump_entity, k8s_name

__all__ = [
    "AppgateClient",
    "AppgateEntityClient",
    "K8SConfigMapClient",
    "entity_unique_id",
    "K8sEntityClient",
]


def get_plural(kind: str) -> str:
    entity = kind.lower().split("-")
    name = entity[0]
    if name.endswith("y"):
        return f"{name[:-1]}ies-{entity[1]}"
    else:
        return f"{name}s-{entity[1]}"


@functools.cache
def plural(kind):
    return get_plural(kind)


@attrs()
class K8sEntityClient:
    api: CustomObjectsApi = attrib()
    domain: str = attrib()
    version: str = attrib()
    namespace: str = attrib()
    kind: str = attrib()

    async def create(self, e: Entity_T) -> None:
        log.info("Creating k8s entity %s", e.name)
        data = dump_entity(EntityWrapper(e), self.kind, None)
        self.api.create_namespaced_custom_object(  # type: ignore
            self.domain,
            self.version,
            self.namespace,
            plural(self.kind),
            data,
        )

    async def delete(self, name: str) -> None:
        log.info("Deleting k8s entity %s", name)
        self.api.delete_namespaced_custom_object(
            self.domain,
            self.version,
            self.namespace,
            plural(self.kind),
            k8s_name(name),
        )

    async def modify(self, e: Entity_T) -> None:
        log.info("Updating k8s entity %s", e.name)
        data = dump_entity(EntityWrapper(e), self.kind, f"v{self.version}")
        self.api.patch_namespaced_custom_object(  # type: ignore
            self.domain,
            self.version,
            self.namespace,
            plural(self.kind),
            k8s_name(data["name"]),
            data,
        )


class AppgateEntityClient:
    def __init__(
        self,
        path: str,
        appgate_client: "AppgateClient",
        singleton: bool,
        load: Callable[[Dict[str, Any]], Entity_T],
        dump: Callable[[Entity_T], Dict[str, Any]],
        magic_entities: Optional[List[Entity_T]] = None,
    ) -> None:
        self._client = appgate_client
        self.path = path
        self.load = load
        self.dump = dump
        self.singleton = singleton
        self.magic_entities = magic_entities

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

    async def post(self, entity: Entity_T) -> Optional[Entity_T]:
        log.info(
            "[appgate-client/%s] POST %s [%s]",
            entity.__class__.__name__,
            entity.name,
            entity.id,
        )
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

    async def put(self, entity: Entity_T) -> Optional[Entity_T]:
        log.info(
            "[appgate-client/%s] PUT %s [%s]",
            entity.__class__.__name__,
            entity.name,
            entity.id,
        )
        path = f"{self.path}/{entity.id}"
        if self.singleton:
            path = self.path
        data = await self._client.put(path, body=self.dump(entity))
        if not data:
            return None
        return self.load(data)

    async def delete(self, id: str) -> bool:
        if not await self._client.delete(f"{self.path}/{id}"):
            return False
        return True


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
        try:
            configmap = await asyncio.to_thread(
                self._v1.read_namespaced_config_map,
                name=self.name,
                namespace=self.namespace,
            )
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
        self.version = version
        self.no_verify = no_verify
        self.ssl_context = (
            ssl.create_default_context(cafile=str(cafile)) if cafile else None
        )

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

    def auth_header(self) -> Optional[str]:
        if self._token:
            return f"Bearer {self._token}"
        return None

    async def request(
        self, verb: str, path: str, data: Optional[Dict[str, Any]] = None
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
        auth_header = self.auth_header()
        if auth_header:
            headers["Authorization"] = auth_header
        url = f"{self.controller}/{path}"
        try:
            async with method(
                url=url,  # type: ignore
                headers=headers,
                json=data,
                ssl=self.ssl_context,
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

    @property
    def authenticated(self) -> bool:
        return self._token is not None

    def entity_client(
        self,
        entity: type,
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
            dump=lambda e: dumper.dump(e),
            magic_entities=magic_entities,
        )
