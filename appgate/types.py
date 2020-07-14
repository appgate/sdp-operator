from attr import attrib, attrs
from typing import List, Dict, Any
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
class Action:
    subtype: str = attrib()
    action: str = attrib()
    types: str = attrib()
    hosts: List[str] = attrib()


@attrs(slots=True)
class AppShortcut:
    name: str = attrib()
    url: str = attrib()
    color_mode: str = attrib()


@attrs(slots=True)
class Entitlement:
    name: str = attrib()
    site: str = attrib()
    conditions: List[str] = attrib()
    disabled: bool = attrib()
    tags: List[str] = attrib()
    condition_logic: str = attrib()
    actions: List[Action] = attrib()
    app_shortcut: AppShortcut = attrib()


def entitlement_load(data: Dict[str, Any]) -> Entitlement:
    return load(data, Entitlement)


@attrs(slots=True)
class Policy:
    name: str = attrib()
    tags: List[str] = attrib()
    disabled: bool = attrib()
    expression: str = attrib()


def policy_load(data: Dict[str, Any]) -> Policy:
    return load(data, Policy)


@attrs(slots=True)
class Condition:
    name: str = attrib()
    tags: List[str] = attrib()
    expression: str = attrib()
    repeat_schedules: List[str]


def condition_load(data: Dict[str, Any]) -> Condition:
    return load(data, Condition)