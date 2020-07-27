import uuid

from attr import attrib, attrs, evolve
from typing import List, Dict, Any, Optional, FrozenSet, TypeVar, Generic, Union
from typedload import load

__all__ = [
    'K8SEvent',
    'EventObject',
    'AppShortcuts',
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
    def id(self) -> str:
        raise NotImplementedError()

    @property
    def tags(self) -> FrozenSet[str]:
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
class AppShortcuts:
    name: str = attrib()
    url: str = attrib()
    color_code: int = attrib(metadata={
        'name': 'colorCode'
    })


@attrs(slots=True, frozen=True)
class Entitlement(Entity_T):
    name: str = attrib()
    site: str = attrib()
    conditions: FrozenSet[str] = attrib(factory=frozenset)
    actions: FrozenSet[Action] = attrib(factory=frozenset)
    notes: Optional[str] = attrib(default='')
    tags: FrozenSet[str] = attrib(factory=frozenset)
    condition_logic: Optional[str] = attrib(metadata={
        'name': 'conditionLogic'
    }, default="and")
    app_shortcuts: FrozenSet[AppShortcuts] = attrib(metadata={
        'name': 'appShortcuts'
    }, factory=frozenset)
    app_shortcut_scripts: FrozenSet[str] = attrib(metadata={
        'name': 'appShortcutScripts'
    }, factory=frozenset)
    disabled: Optional[bool] = attrib(default=False)
    id: str = attrib(default=str(uuid.uuid4()), eq=False)


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
    tags: FrozenSet[str] = attrib(default=None)
    entitlements: FrozenSet[str] = attrib(factory=frozenset)
    entitlement_links: FrozenSet[str] = attrib(metadata={
        'name': 'entitlementLinks'
    }, factory=frozenset)
    ringfence_rules: FrozenSet[str] = attrib(metadata={
        'name': 'ringfenceRules'
    }, factory=frozenset)
    ringfence_rule_links: FrozenSet[str] = attrib(metadata={
        'name': 'ringfenceRuleLinks'
    }, factory=frozenset)
    administrative_roles: FrozenSet[str] = attrib(metadata={
        'name': 'administrativeRoles'
    }, factory=frozenset)
    disabled: bool = attrib(default=False)
    tamper_proofing: bool = attrib(metadata={
        'name': 'tamperProofing'
    }, default=True)
    id: str = attrib(factory=lambda: str(uuid.uuid4()), eq=False)


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
    tags: FrozenSet[str] = attrib(factory=frozenset)
    repeat_schedules: FrozenSet[str] = attrib(metadata={
        'name': 'repeatSchedules'
    }, factory=frozenset)
    remedy_methods: FrozenSet[RemedyMethod] = attrib(metadata={
        'name': 'remedyMethods'
    }, factory=frozenset)
    id: str = attrib(default=str(uuid.uuid4()), eq=False)


def condition_load(data: Dict[str, Any]) -> Condition:
    return load(data, Condition)


AppgateEntity = Union[Entitlement, Policy, Condition]


@attrs(slots=True, frozen=True)
class AppgateEvent:
    op: str = attrib()
    entity: AppgateEntity = attrib()
