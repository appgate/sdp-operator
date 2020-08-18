from typing import List, Optional

from appgate.types import generate_api_spec

api_spec = generate_api_spec()
entities = api_spec.entities

Policy = entities['Policy'].cls
Entitlement = entities['Entitlement'].cls
Condition = entities['Condition'].cls
IdentityProvider = entities['IdentityProvider'].cls


def entitlement(name: str, id: str = None, site: str = 'site-example',
                conditions: Optional[List[str]] = None,
                display_name: Optional[str] = None) -> Entitlement:
    return Entitlement(id=id,
                       name=name,
                       site=site,
                       displayName=display_name or 'some-name',
                       conditions=frozenset(conditions) if conditions else frozenset())


def condition(name: str, id: str = None, expression: Optional[str] = None) -> Condition:
    return Condition(id=id,
                     name=name,
                     expression=expression or 'expression-test')


def policy(name: str, id: str = None, entitlements: Optional[List[str]] = None) -> Policy:
    return Policy(name=name,
                  id=id,
                  entitlements=frozenset(entitlements) if entitlements else frozenset(),
                  expression='expression-test')
