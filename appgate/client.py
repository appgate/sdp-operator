import uuid
from typing import Dict, Any, Optional, List, Callable
import aiohttp
import typedload
from aiohttp import InvalidURL

from appgate.logger import log
from appgate.types import AppgateEntity, Policy, Entitlement, Condition

__all__ = [
    'AppgateClient',
    'EntityClient',
]


class EntityClient:
    def __init__(self, path: str, appgate_client: 'AppgateClient',
                 loader: Callable[[Dict[str, Any]], AppgateEntity]) -> None:
        self._client = appgate_client
        self.path = path
        self.loader = loader

    async def get(self) -> Optional[List[AppgateEntity]]:
        data = await self._client.get(self.path)
        if not data:
            return None
        return [self.loader(e) for e in data['data']]

    async def post(self, entity: AppgateEntity) -> Optional[AppgateEntity]:
        data = await self._client.post(self.path,
                                       body=typedload.dump(entity))
        if not data:
            return None
        return self.loader(data)  # type: ignore

    async def put(self, entity: AppgateEntity) -> Optional[AppgateEntity]:
        data = await self._client.put(f'{self.path}/{entity.id}',
                                      body=typedload.dump(entity))
        if not data:
            return None
        return self.loader(data)  # type: ignore

    async def delete(self, id: str) -> bool:
        if not await self._client.delete(f'{self.path}/{id}'):
            return False
        return True


class AppgateClient:
    def __init__(self, controller: str, user: str, password: str) -> None:
        self.controller = controller
        self.user = user
        self.password = password
        self._session = aiohttp.ClientSession()
        self.device_id = str(uuid.uuid4())
        self._token = None

    async def close(self) -> None:
        await self._session.close()

    def auth_header(self) -> Optional[str]:
        if self._token:
            return f'Bearer {self._token}'
        return None

    async def request(self, verb: str, path:str,
                      data: Optional[Dict[str, Any]] = None,
                      empty_response: bool = False) -> Optional[Dict[str, Any]]:
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
            'Accept': 'application/vnd.appgate.peer-v13+json',
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
                    # For some reason controller on DELETES returns nothing :O
                    if empty_response:
                        return {}
                    else:
                        return await resp.json()
                else:
                    data = await resp.text()
                    if data:
                        log.error('[aggpate-client] %s :: %s: %s', url, resp.status,
                                  data)
                    else:
                        log.error('[aggpate-client] %s :: %s', url, resp.status)
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
        return await self.request('DELETE', path=path, data=body, empty_response=True)

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

    @property
    def policies(self) -> EntityClient:
        return EntityClient(appgate_client=self, path='/admin/policies',
                            loader=lambda e: typedload.load(e, Policy))

    @property
    def entitlements(self) -> EntityClient:
        return EntityClient(appgate_client=self, path='/admin/entitlements',
                            loader=lambda e: typedload.load(e, Entitlement))

    @property
    def conditions(self) -> EntityClient:
        return EntityClient(appgate_client=self, path='/admin/conditions',
                            loader=lambda e: typedload.load(e, Condition))

