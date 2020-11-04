import asyncio
import datetime
import uuid
from typing import Dict, Any, Optional, List, Callable
import aiohttp
from aiohttp import InvalidURL
from kubernetes.client import CoreV1Api, V1ConfigMap, V1ObjectMeta

from appgate.attrs import APPGATE_DUMPER, APPGATE_LOADER, parse_datetime, dump_datetime
from appgate.logger import log
from appgate.openapi.types import Entity_T
from appgate.types import LatestEntityGeneration


__all__ = [
    'AppgateClient',
    'EntityClient',
    'K8SConfigMapClient',
    'entity_unique_id'
]


class AppgateException(Exception):
    pass


class EntityClient:
    def __init__(self, path: str, appgate_client: 'AppgateClient',
                 singleton: bool,
                 load: Callable[[Dict[str, Any]], Entity_T],
                 dump: Callable[[Entity_T], Dict[str, Any]]) -> None:
        self._client = appgate_client
        self.path = path
        self.load = load
        self.dump = dump
        self.singleton = singleton

    async def get(self) -> Optional[List[Entity_T]]:
        data = await self._client.get(self.path)
        if not data:
            log.error('[aggpate-client] GET %s :: Expecting a response but we got empty data',
                      self.path)
            return None
        # TODO: We should discover this from the api spec
        if 'data' in data:
            return [self.load(e) for e in data['data']]
        else:
            return [self.load(data)]

    async def post(self, entity: Entity_T) -> Optional[Entity_T]:
        log.info('[appgate-client/%s] POST %s [%s]', entity.__class__.__name__, entity.name,
                 entity.id)
        body = self.dump(entity)
        body['id'] = entity.id
        data = await self._client.post(self.path,
                                       body=body)
        if not data:
            log.error('[aggpate-client] POST %s :: Expecting a response but we got empty data',
                      self.path)
            return None
        return self.load(data)  # type: ignore

    async def put(self, entity: Entity_T) -> Optional[Entity_T]:
        log.info('[appgate-client/%s] PUT %s [%s]', entity.__class__.__name__, entity.name,
                 entity.id)
        path = f'{self.path}/{entity.id}'
        if self.singleton:
            path = self.path
        data = await self._client.put(path, body=self.dump(entity))
        if not data:
            return None
        return self.load(data)  # type: ignore

    async def delete(self, id: str) -> bool:
        if not await self._client.delete(f'{self.path}/{id}'):
            return False
        return True


def load_latest_entity_generation(key: str, v: Any) -> LatestEntityGeneration:
    if isinstance(v, str):
        try:
            generation, modified = v.split(',', maxsplit=2)
            return LatestEntityGeneration(generation=int(generation),
                                          modified=parse_datetime(modified))
        except Exception:
            log.error('Error getting entry from configmap entry %s, defaulting to generation 0',
                      key)
            return LatestEntityGeneration()
    else:
        return LatestEntityGeneration()


def dump_latest_entity_generation(entry: LatestEntityGeneration) -> str:
    return f'{entry.generation},{dump_datetime(entry.modified)}'


def entity_unique_id(entity_type: str, name: str) -> str:
    name = name.replace(' ','').lower()
    return f'{entity_type}-{name}'


class K8SConfigMapClient:
    def __init__(self, namespace: str, name: str) -> None:
        self._v1 = CoreV1Api()
        self._configmap_mt: Optional[V1ObjectMeta] = None
        self._entries: Dict[str, LatestEntityGeneration] = {}
        self.namespace = namespace
        self.name = name

    async def init(self) -> None:
        log.info('[k8s-configmap-client/%s/%s] Initializing config-map %s', self.name, self.namespace,
                 self.name)
        configmap = await asyncio.to_thread(  # type: ignore
            self._v1.read_namespaced_config_map,
            name=self.name,
            namespace=self.namespace
        )
        self._configmap_mt = configmap.metadata
        self._entries = {
            k: load_latest_entity_generation(k, v) for k, v in (configmap.data or {}).items()
        }

    def read(self, key: str) -> Optional[LatestEntityGeneration]:
        entry = self._entries.get(key)
        log.info('[k8s-configmap-client/%s/%s] Reading %s: %s', self.name, self.namespace,
                 key, dump_latest_entity_generation(entry) if entry else 'not found')
        return entry

    async def update(self, key: str, generation: Optional[int]) -> Optional[LatestEntityGeneration]:
        if not self._configmap_mt:
            await self.init()
        prev_entry = self._entries.get(key) or LatestEntityGeneration()
        self._entries[key] = LatestEntityGeneration(
            generation=generation or (prev_entry.generation + 1),
            modified=datetime.datetime.now().astimezone())
        gen = dump_latest_entity_generation(self._entries[key])
        body = V1ConfigMap(api_version='v1', kind='ConfigMap', data={
            key: gen
        })
        log.info('[k8s-configmap-client/%s/%s] Updating entry %s -> %s', self.name, self.namespace,
                 key, gen)
        new_configmap = await asyncio.to_thread(  # type: ignore
            self._v1.patch_namespaced_config_map,
            name=self.name,
            namespace=self.namespace,
            body=body
        )
        self._configmap_mt = new_configmap.metadata
        return self._entries[key]

    async def delete(self, key: str) -> Optional[LatestEntityGeneration]:
        if not self._configmap_mt:
            await self.init()
        if key not in self._entries:
            return None
        entry = self._entries[key]
        del self._entries[key]
        body = V1ConfigMap(api_version='v1', kind='ConfigMap', data={
            key: None
        })
        log.info('[k8s-configmap-client/%s/%s] Deleting entry %s', self.name, self.namespace, key)
        new_configmap = await asyncio.to_thread(  # type: ignore
            self._v1.patch_namespaced_config_map,
            name=self.name,
            namespace=self.namespace,
            body=body,
        )
        self._configmap_mt = new_configmap.metadata
        return entry


class AppgateClient:
    def __init__(self, controller: str, user: str, password: str, version: int,
                 no_verify: bool = False) -> None:
        self.controller = controller
        self.user = user
        self.password = password
        self._session = aiohttp.ClientSession()
        self.device_id = str(uuid.uuid4())
        self._token = None
        self.version = version
        self.no_verify = no_verify


    async def close(self) -> None:
        await self._session.close()

    async def __aenter__(self) -> 'AppgateClient':
        await self.login()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def auth_header(self) -> Optional[str]:
        if self._token:
            return f'Bearer {self._token}'
        return None

    async def request(self, verb: str, path: str,
                      data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        verbs = {
            'POST': self._session.post,
            'DELETE': self._session.delete,
            'PUT': self._session.put,
            'GET': self._session.get,
        }
        method = verbs.get(verb)
        if not method:
            raise Exception(f'Unknown HTTP method: {verb}')
        headers = {
            'Accept': f'application/vnd.appgate.peer-v{self.version}+json',
            'Content-Type': 'application/json'
        }
        auth_header = self.auth_header()
        if auth_header:
            headers['Authorization'] = auth_header
        url = f'{self.controller}/{path}'
        try:
            async with method(url=url,  # type: ignore
                              headers=headers,
                              json=data,
                              ssl=not self.no_verify) as resp:
                status_code = resp.status // 100
                if status_code == 2:
                    if resp.status == 204:
                        return {}
                    else:
                        return await resp.json()
                else:
                    error_data = await resp.text()
                    log.error('[aggpate-client] %s :: %s: %s', url, resp.status,
                              error_data)
                    if data:
                        log.error('[appgate-client] payload :: %s', data)
                    raise AppgateException(f'Error: [{method} {url} {resp.status}] {error_data}')
        except InvalidURL:
            log.error('[appgate-client] Error preforming query: %s', url)
            raise AppgateException(f'Error: [{method} {url}] InvalidURL')

    async def post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        return await self.request('POST', path=path, data=body)

    async def get(self, path: str) -> Optional[Dict[str, Any]]:
        return await self.request('GET', path=path)

    async def put(self, path: str, body: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        return await self.request('PUT', path=path, data=body)

    async def delete(self, path: str, body: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        return await self.request('DELETE', path=path, data=body)

    async def login(self) -> None:
        body = {
            'providerName': 'local',
            'username': self.user,
            'password': self.password,
            'deviceId': self.device_id
        }
        resp = await self.post('/admin/login', body=body)
        if resp:
            self._token = resp['token']

    @property
    def authenticated(self) -> bool:
        return self._token is not None

    def entity_client(self, entity: type, api_path: str, singleton: bool) -> EntityClient:
        dumper = APPGATE_DUMPER
        return EntityClient(appgate_client=self, path=f'/admin/{api_path}',
                            singleton=singleton,
                            load=lambda d: APPGATE_LOADER.load(d, None, entity),
                            dump=lambda e: dumper.dump(e))
