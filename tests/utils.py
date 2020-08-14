from typing import List, Optional

from appgate.types import generate_entities
entities = generate_entities()

Policy = entities['Policy'][0]
Entitlement = entities['Entitlement'][0]
Condition = entities['Condition'][0]
IdentityProvider = entities['IdentityProvider'][0]


def entitlement(name: str, id: str = None, site: str = 'site-example',
                conditions: Optional[List[str]] = None,
                displayName: Optional[str] = None) -> Entitlement:
    return Entitlement(id=id,
                       name=name,
                       site=site,
                       displayName=displayName or 'some-name',
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
