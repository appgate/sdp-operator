from attr import attrib, attrs
from typing import List, Dict, Any, Optional
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
    'condition_load'
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


@attrs(slots=True, frozen=True)
class Action:
    subtype: str = attrib()
    action: str = attrib()
    types: str = attrib()
    hosts: List[str] = attrib()
    ports: List[str] = attrib()
    monitor: ActionMonitor = attrib()


@attrs(slots=True, frozen=True)
class AppShortcut:
    name: str = attrib()
    url: str = attrib()
    color_mode: str = attrib(metadata={
        'name': 'colorMode'
    })


@attrs(slots=True, frozen=True)
class Entitlement:
    id: Optional[str] = attrib()
    name: str = attrib()
    site: str = attrib()
    conditions: List[str] = attrib()
    actions: List[Action] = attrib()
    notes: Optional[str] = attrib()
    tags: Optional[List[str]] = attrib()
    site_name: str = attrib(metadata={
        'name': 'siteName'
    })
    condition_logic: Optional[str] = attrib(metadata={
        'name': 'conditionLogic'
    })
    app_shortcut: Optional[AppShortcut] = attrib(metadata={
        'name': 'appShortcut'
    })
    app_shortcut_scripts: Optional[List[str]] = attrib()
    disabled: Optional[bool] = attrib(default=False)


def entitlement_load(data: Dict[str, Any]) -> Entitlement:
    return load(data, Entitlement)


@attrs(slots=True, frozen=True)
class Policy:
    name: str = attrib()
    expression: str = attrib()
    notes: Optional[str] = attrib(default=None)
    override_site: Optional[str] = attrib(metadata={
        'name': 'overrideSite'
    }, default=None)
    tags: Optional[List[str]] = attrib(default=None)
    entitlements: Optional[List[str]] = attrib(default=None)
    entitlement_links: Optional[List[str]] = attrib(metadata={
        'name': 'entitlementLinks'
    }, default=None)
    ringfence_rules: Optional[List[str]] = attrib(metadata={
        'name': 'ringfenceRules'
    }, default=None)
    ringfence_rule_links: Optional[List[str]] = attrib(metadata={
        'name': 'ringfenceRuleLinks'
    }, default=None)
    administrative_roles: Optional[List[str]] = attrib(metadata={
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
class Condition:
    id: Optional[str] = attrib()
    name: str = attrib()
    expression: str = attrib()
    notes: Optional[str] = attrib()
    tags: Optional[List[str]] = attrib()
    repeat_schedules: Optional[List[str]] = attrib(metadata={
        'name': 'repeatSchedules'
    })
    remedy_methods: Optional[List[RemedyMethod]] = attrib(metadata={
        'name': 'remedyMethods'
    })


def condition_load(data: Dict[str, Any]) -> Condition:
    return load(data, Condition)
