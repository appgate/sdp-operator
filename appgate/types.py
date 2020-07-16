from attr import attrib, attrs
from typing import List, Dict, Any, Optional, FrozenSet
from typedload import load

__all__ = [
    'Event',
    'EventObject',
    'AppShortcut',
    'Action',
    'Entitlement',
    'entitlement_load',
    'Policy',
    'policy_load',
    'Condition',
    'condition_load',
    'Entity_T'
]


class EventObject:
    def __init__(self, data: Dict[str, Any]) -> None:
        self.kind = data['kind']
        self.api_version = data['apiVersion']
        self.metadata = data['metadata']
        self.spec = data['spec']


class Event:
    def __init__(self, data: Dict[str, Any]) -> None:
        self.type = data['type']
        self.object = EventObject(data['object'])


@attrs(slots=True, frozen=True)
class ActionMonitor:
    enabled: bool = attrib()
    timeout: int = attrib()


class Entity_T:
    @property
    def name(self) -> str:
        raise NotImplementedError()

    @property
    def id(self) -> Optional[str]:
        raise NotImplementedError()


@attrs(slots=True, frozen=True)
class Action:
    subtype: str = attrib()
    action: str = attrib()
    types: str = attrib()
    hosts: FrozenSet[str] = attrib()
    ports: FrozenSet[str] = attrib()
    monitor: ActionMonitor = attrib()


@attrs(slots=True, frozen=True)
class AppShortcut:
    name: str = attrib()
    url: str = attrib()
    color_mode: str = attrib(metadata={
        'name': 'colorMode'
    })


@attrs(slots=True, frozen=True)
class Entitlement(Entity_T):
    name: str = attrib()
    site: str = attrib()
    conditions: FrozenSet[str] = attrib(factory=frozenset)
    actions: FrozenSet[Action] = attrib(factory=frozenset)
    notes: Optional[str] = attrib(default=None)
    tags: Optional[FrozenSet[str]] = attrib(default=None)
    condition_logic: Optional[str] = attrib(metadata={
        'name': 'conditionLogic'
    }, default="and")
    app_shortcut: Optional[AppShortcut] = attrib(metadata={
        'name': 'appShortcut'
    }, default=None)
    app_shortcut_scripts: Optional[List[str]] = attrib(default=None)
    disabled: Optional[bool] = attrib(default=False)
    id: Optional[str] = attrib(default=None)


def entitlement_load(data: Dict[str, Any]) -> Entitlement:
    return load(data, Entitlement)


@attrs(slots=True, frozen=True)
class Policy(Entity_T):
    name: str = attrib()
    expression: str = attrib()
    notes: Optional[str] = attrib(default=None)
    override_site: Optional[str] = attrib(metadata={
        'name': 'overrideSite'
    }, default=None)
    tags: Optional[FrozenSet[str]] = attrib(default=None)
    entitlements: Optional[FrozenSet[str]] = attrib(default=None)
    entitlement_links: Optional[FrozenSet[str]] = attrib(metadata={
        'name': 'entitlementLinks'
    }, default=None)
    ringfence_rules: Optional[FrozenSet[str]] = attrib(metadata={
        'name': 'ringfenceRules'
    }, default=None)
    ringfence_rule_links: Optional[FrozenSet[str]] = attrib(metadata={
        'name': 'ringfenceRuleLinks'
    }, default=None)
    administrative_roles: Optional[FrozenSet[str]] = attrib(metadata={
        'name': 'administrativeRoles'
    }, default=None)
    disabled: bool = attrib(default=False)
    tamper_proofing: bool = attrib(metadata={
        'name': 'tamperProofing'
    }, default=True)
    id: Optional[str] = attrib(default=None, eq=False)


def policy_load(data: Dict[str, Any]) -> Policy:
    return load(data, Policy)


@attrs(slots=True, frozen=True)
class RemedyMethod:
    type: str = attrib()
    message: str = attrib()
    claim_suffix: str = attrib(metadata={
        'name': 'claimSuffix'
    })
    provider_id: str = attrib(metadata={
        'name': 'providerId'
    })


@attrs(slots=True, frozen=True)
class Condition(Entity_T):
    id: Optional[str] = attrib()
    name: str = attrib()
    expression: str = attrib()
    notes: Optional[str] = attrib(default=None)
    tags: Optional[FrozenSet[str]] = attrib(default=None)
    repeat_schedules: Optional[FrozenSet[str]] = attrib(metadata={
        'name': 'repeatSchedules'
    }, default=None)
    remedy_methods: Optional[List[RemedyMethod]] = attrib(metadata={
        'name': 'remedyMethods'
    }, default=None)


def condition_load(data: Dict[str, Any]) -> Condition:
    return load(data, Condition)
