from attr import attrib, attrs, evolve
from typing import List, Dict, Any, Optional, FrozenSet, TypeVar, Generic, Union
from typedload import load

__all__ = [
    'K8SEvent',
    'EventObject',
    'AppShortcut',
    'Action',
    'Entitlement',
    'entitlement_load',
    'Policy',
    'policy_load',
    'Condition',
    'condition_load',
    'Entity_T',
    'AppgateEvent',
    'AppgateEntity'
]


class EventObject:
    def __init__(self, data: Dict[str, Any]) -> None:
        self.kind = data['kind']
        self.api_version = data['apiVersion']
        self.metadata = data['metadata']
        self.spec = data['spec']


class K8SEvent:
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

    @property
    def tags(self) -> Optional[FrozenSet[str]]:
        raise NotImplementedError


@attrs(slots=True, frozen=True)
class Action:
    subtype: str = attrib()
    action: str = attrib()
    hosts: FrozenSet[str] = attrib()
    types: FrozenSet[str] = attrib(default=frozenset)
    ports: Optional[FrozenSet[str]] = attrib(default=None)
    monitor: Optional[ActionMonitor] = attrib(default=None)


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
    notes: Optional[str] = attrib(default='')
    tags: Optional[FrozenSet[str]] = attrib(factory=frozenset)
    condition_logic: Optional[str] = attrib(metadata={
        'name': 'conditionLogic'
    }, default="and")
    app_shortcut: Optional[AppShortcut] = attrib(metadata={
        'name': 'appShortcut'
    }, default=None)
    app_shortcut_scripts: Optional[FrozenSet[str]] = attrib(factory=frozenset)
    disabled: Optional[bool] = attrib(default=False)
    id: Optional[str] = attrib(default='')


def entitlement_load(data: Dict[str, Any]) -> Entitlement:
    return load(data, Entitlement)


@attrs(slots=True, frozen=True)
class Policy(Entity_T):
    name: str = attrib()
    expression: str = attrib()
    notes: Optional[str] = attrib(default='')
    override_site: Optional[str] = attrib(metadata={
        'name': 'overrideSite'
    }, default='')
    tags: Optional[FrozenSet[str]] = attrib(default=None)
    entitlements: Optional[FrozenSet[str]] = attrib(factory=frozenset)
    entitlement_links: Optional[FrozenSet[str]] = attrib(metadata={
        'name': 'entitlementLinks'
    }, factory=frozenset)
    ringfence_rules: Optional[FrozenSet[str]] = attrib(metadata={
        'name': 'ringfenceRules'
    }, factory=frozenset)
    ringfence_rule_links: Optional[FrozenSet[str]] = attrib(metadata={
        'name': 'ringfenceRuleLinks'
    }, factory=frozenset)
    administrative_roles: Optional[FrozenSet[str]] = attrib(metadata={
        'name': 'administrativeRoles'
    }, factory=frozenset)
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
    name: str = attrib()
    expression: str = attrib()
    notes: Optional[str] = attrib(default='')
    tags: Optional[FrozenSet[str]] = attrib(factory=frozenset)
    repeat_schedules: Optional[FrozenSet[str]] = attrib(metadata={
        'name': 'repeatSchedules'
    }, factory=frozenset)
    remedy_methods: Optional[FrozenSet[RemedyMethod]] = attrib(metadata={
        'name': 'remedyMethods'
    }, factory=frozenset)
    id: Optional[str] = attrib(default=None)


def condition_load(data: Dict[str, Any]) -> Condition:
    return load(data, Condition)


AppgateEntity = Union[Entitlement, Policy, Condition]


@attrs(slots=True, frozen=True)
class AppgateEvent:
    op: str = attrib()
    entity: AppgateEntity = attrib()
