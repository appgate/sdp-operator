import uuid
from typing import Dict, Any, Optional, List, Callable
import aiohttp
from aiohttp import InvalidURL

from appgate.attrs import APPGATE_DUMPER, APPGATE_LOADER, APPGATE_DUMPER_WITH_SECRETS
from appgate.logger import log


__all__ = [
    'AppgateClient',
    'EntityClient',
]

from appgate.openapi.types import Entity_T


class EntityClient:
    def __init__(self, path: str, appgate_client: 'AppgateClient',
                 load: Callable[[Dict[str, Any]], Entity_T],
                 dump: Callable[[Entity_T], Dict[str, Any]]) -> None:
        self._client = appgate_client
        self.path = path
        self.load = load
        self.dump = dump

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
        data = await self._client.put(f'{self.path}/{entity.id}',
                                      body=self.dump(entity))
        if not data:
            log.error('[aggpate-client] PUT %s :: Expecting a response but we got empty data',
                      self.path)
            return None
        return self.load(data)  # type: ignore

    async def delete(self, id: str) -> bool:
        if not await self._client.delete(f'{self.path}/{id}'):
            return False
        return True


class AppgateClient:
    def __init__(self, controller: str, user: str, password: str, version: int) -> None:
        self.controller = controller
        self.user = user
        self.password = password
        self._session = aiohttp.ClientSession()
        self.device_id = str(uuid.uuid4())
        self._token = None
        self.version = version

    async def close(self) -> None:
        await self._session.close()

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
                              ssl=False) as resp:
                status_code = resp.status // 100
                if status_code == 2:
                    if resp.status == 204:
                        return {}
                    else:
                        return await resp.json()
                else:
                    error_data = await resp.text()
                    if data:
                        log.error('[aggpate-client] %s :: %s: %s', url, resp.status,
                                  error_data)
                        log.error('[appgate-client] payload :: %s', data)
                    else:
                        log.error('[aggpate-client] %s :: %s', url, resp.status)
                        log.error('[appgate-client] payload :: %s', data)
                    return None
        except InvalidURL:
            log.error('[appgate-client] Error preforming query: %s', url)
            return None

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

    def entity_client(self, entity: type, api_path: str, dump_secrets: bool) -> EntityClient:
        dumper = APPGATE_DUMPER_WITH_SECRETS if dump_secrets else APPGATE_DUMPER
        return EntityClient(appgate_client=self, path=f'/admin/{api_path}',
                            load=lambda d: APPGATE_LOADER.load(d, None, entity),
                            dump=lambda e: dumper.dump(e))
