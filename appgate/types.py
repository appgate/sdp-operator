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


@attrs(slots=True)
class ActionMonitor:
    enabled: bool = attrib()
    timeout: int = attrib()


@attrs(slots=True)
class Action:
    subtype: str = attrib()
    action: str = attrib()
    types: str = attrib()
    hosts: List[str] = attrib()
    ports: List[str] = attrib()
    monitor: ActionMonitor = attrib()


@attrs(slots=True)
class AppShortcut:
    name: str = attrib()
    url: str = attrib()
    color_mode: str = attrib(metadata={
        'name': 'colorMode'
    })


@attrs(slots=True)
class Entitlement:
    name: str = attrib()
    notes: str = attrib()
    create: str = attrib()
    updated: str = attrib()
    tags: List[str] = attrib()
    disabled: bool = attrib()
    site: str = attrib()
    site_name: str = attrib(metadata={
        'name': 'siteName'
    })
    condition_logic: str = attrib(metadata={
        'name': 'conditionLogic'
    })
    conditions: List[str] = attrib()
    actions: List[Action] = attrib()
    app_shortcut: AppShortcut = attrib(metadata={
        'name': 'appShortcut'
    })
    app_shortcut_scripts: List[str] = attrib()


def entitlement_load(data: Dict[str, Any]) -> Entitlement:
    return load(data, Entitlement)


@attrs(slots=True)
class Policy:
    name: str = attrib()
    notes: str = attrib()
    create: Optional[str] = attrib()
    updated: Optional[str] = attrib()
    tags: List[str] = attrib()
    disabled: bool = attrib()
    expression: str = attrib()
    entitlements: List[str] = attrib()
    entitlement_links: List[str] = attrib(metadata={
        'name': 'entitlementLinks'
    })
    ringfence_rules: List[str] = attrib(metadata={
        'name': 'ringfenceRules'
    })
    ringfence_rule_links: List[str] = attrib(metadata={
        'name': 'ringfenceRuleLinks'
    })
    tamper_proofing: bool = attrib(metadata={
        'name': 'tamperProofing'
    })
    override_site: str = attrib(metadata={
        'name': 'overrideSite'
    })
    administrative_roles: List[str] = attrib(metadata={
        'name': 'administrativeRoles'
    })


def policy_load(data: Dict[str, Any]) -> Policy:
    return load(data, Policy)


@attrs(slots=True)
class RemedyMethod:
    type: str = attrib()
    message: str = attrib()
    claim_suffix: str = attrib(metadata={
        'name': 'claimSuffix'
    })
    provider_id: str = attrib(metadata={
        'name': 'providerId'
    })


@attrs(slots=True)
class Condition:
    name: str = attrib()
    notes: str = attrib()
    create: str = attrib()
    updated: str = attrib()
    tags: List[str] = attrib()
    expression: str = attrib()
    repeat_schedules: List[str] = attrib(metadata={
        'name': 'repeatSchedules'
    })
    remedy_methods: List[RemedyMethod] = attrib(metadata={
        'name': 'remedyMethods'
    })


def condition_load(data: Dict[str, Any]) -> Condition:
    return load(data, Condition)
