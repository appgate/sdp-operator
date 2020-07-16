import uuid
from typing import Dict, Any, Optional, List, TypeVar
import aiohttp
import typedload
from appgate.types import Policy, Entitlement, Condition, Entity_T

__all__ = [
    'AppgateClient',
]


T = TypeVar('T', bound=Entity_T)


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

    async def request(self, verb: str, path:str,
                      data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        async with method(url=f'{self.controller}/{path}',
                          headers=headers,
                          json=data,
                          ssl=False) as resp:
            return await resp.json()

    async def post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.request('POST', path=path, data=body)

    async def get(self, path: str) -> Dict[str, Any]:
        return await self.request('GET', path=path)

    async def put(self, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.request('PUT', path=path, data=body)

    async def delete(self, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.request('DELETE', path=path, data=body)

    async def login(self) -> None:
        body = {
            'providerName': 'local',
            'username': self.user,
            'password': self.password,
            'deviceId': self.device_id
        }
        resp = await self.post('/admin/login', body=body)
        self._token = resp['token']

    async def get_policies(self) -> List[Policy]:
        policies = await self.get('/admin/policies')
        return typedload.load(policies['data'], List[Policy])

    async def get_entitlements(self) -> List[Entitlement]:
        entitlements = await self.get('/admin/entitlements')
        return typedload.load(entitlements['data'], List[Entitlement])

    async def get_conditions(self) -> List[Condition]:
        conditions = await self.get('/admin/conditions')
        return typedload.load(conditions['data'], List[Condition])
