import difflib
import itertools
import json
import re
import sys
import datetime
import time
from functools import cached_property
from pathlib import Path
from typing import (
    Set,
    Dict,
    Optional,
    Tuple,
    Literal,
    Any,
    Iterable,
    List,
    FrozenSet,
    Iterator,
)

import yaml
from attr import attrib, attrs, evolve

from appgate.logger import is_debug
from appgate.attrs import K8S_DUMPER, DIFF_DUMPER, dump_datetime
from appgate.client import AppgateEntityClient, K8SConfigMapClient, entity_unique_id, K8sEntityClient
from appgate.logger import log
from appgate.openapi.parser import ENTITY_METADATA_ATTRIB_NAME
from appgate.openapi.types import (
    Entity_T,
    APISpec,
    PYTHON_TYPES,
    K8S_APPGATE_DOMAIN,
    K8S_APPGATE_VERSION,
    APPGATE_METADATA_ATTRIB_NAME,
    APPGATE_METADATA_PASSWORD_FIELDS_FIELD,
    AppgateException,
)
from appgate.types import (
    EntityWrapper,
    EntitiesSet,
    EntityFieldDependency,
    MissingFieldDependencies,
    has_tag,
    is_target, AppgateEventSuccess,
)
from appgate.openapi.utils import has_name


__all__ = [
    "AppgateState",
    "AppgatePlan",
    "EntitiesSet",
    "create_appgate_plan",
    "appgate_plan_apply",
    "entities_conflict_summary",
    "appgate_plan_apply",
    "resolve_field_entity",
    "resolve_field_entities",
    "resolve_appgate_state",
    "compare_entities",
    "compute_diff",
    "exclude_appgate_entities",
    "exclude_appgate_entity",
    "update_entity",
    "update_entities"
]


def exclude_appgate_entity(
    entity: EntityWrapper,
    target_tags: Optional[FrozenSet[str]],
    exclude_tags: Optional[FrozenSet[str]],
) -> bool:
    return is_target(entity, target_tags) and not has_tag(entity, exclude_tags)


def exclude_appgate_entities(
    entities: Iterable[EntityWrapper],
    target_tags: Optional[FrozenSet[str]],
    exclude_tags: Optional[FrozenSet[str]],
) -> Set[EntityWrapper]:
    """
    Filter out entities according to target_tags and exclude_tags
    Returns the entities that are member of target_tags (all entities if None)
    but not member of exclude_tags
    """
    return set(
        filter(
            lambda e: exclude_appgate_entity(
                e, target_tags=target_tags, exclude_tags=exclude_tags
            ),
            entities,
        )
    )


def entities_op(
    entity_set: EntitiesSet,
    entity: EntityWrapper,
    op: Literal["ADDED", "DELETED", "MODIFIED"],
    current_entities: EntitiesSet,
) -> None:
    # Current state should always contain the real id!!
    cached_entity = current_entities.entities_by_name.get(entity.name)
    if cached_entity:
        entity = entity.with_id(id=cached_entity.id)
    if op == "ADDED":
        entity_set.add(entity)
    elif op == "DELETED":
        entity_set.delete(entity)
    elif op == "MODIFIED":
        entity_set.modify(entity)


def k8s_name(name: str) -> str:
    # This is ugly but we need to go from a bigger set of strings
    # into a smaller one :(
    return re.sub("[^a-z0-9-.]+", "-", name.strip().lower())


def update_entity(appgate_event: AppgateEventSuccess) -> None:
    """
    Re-conciliate entity from event with the current version on k8s
    """
    pass


def update_entities(entity_type: str, entities: EntitiesSet) -> None:
    """
    Re-conciliate entities the current versions on k8s
    """
    pass


def dump_entity(
    entity: EntityWrapper, entity_type: str, version_suffix: str
) -> Dict[str, Any]:
    r"""
    name should match this regexp:
       '[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*'
    """
    entity_name = k8s_name(entity.name) if has_name(entity) else k8s_name(entity_type)
    entity_mt = getattr(entity.value, ENTITY_METADATA_ATTRIB_NAME, {})
    singleton = entity_mt.get("singleton", False)
    if not singleton:
        entity.value = evolve(
            entity.value,
            appgate_metadata=evolve(entity.value.appgate_metadata, uuid=entity.id),
        )
    return {
        "apiVersion": f"{K8S_APPGATE_DOMAIN}/{K8S_APPGATE_VERSION}",
        "kind": f"{entity_type}-{version_suffix}",
        "metadata": {
            "name": entity_name if entity.is_singleton() else k8s_name(entity.name)
        },
        "spec": K8S_DUMPER.dump(entity.value),
    }


def dump_entities(
    entities: Iterable[EntityWrapper],
    version_suffix: str,
    dump_file: Optional[Path],
    entity_type: str,
) -> Optional[List[str]]:
    """
    Dump entities into a yaml file or stdout.
    """
    entity_passwords = None
    if not entities:
        log.debug(f"No entities of type %s found", entity_type)
        return None
    log.info(f"Dumping entities of type %s", entity_type)
    dumped_entities: List[str] = []
    for i, e in enumerate(entities):
        dumped_entity = dump_entity(e, entity_type, version_suffix)
        if not dumped_entity.get("spec"):
            continue
        appgate_metadata = dumped_entity["spec"].get(APPGATE_METADATA_ATTRIB_NAME)
        if appgate_metadata:
            entity_passwords = appgate_metadata.get(
                APPGATE_METADATA_PASSWORD_FIELDS_FIELD
            )
        dumped_entities.append(yaml.safe_dump(dumped_entity, default_flow_style=False))
    if not dumped_entities:
        return None
    f = dump_file.open("w") if dump_file else sys.stdout
    for i, de in enumerate(dumped_entities):
        if i > 0:
            f.write("---\n")
        f.write(de)
    if dump_file:
        f.close()
    return entity_passwords


@attrs()
class AppgateState:
    """
    Class to maintain the state of the Appgate system in memory.
    The state is stored in a dictionary that maps: EntityType -> EntitiesSet
    """

    entities_set: Dict[str, EntitiesSet] = attrib(factory=EntitiesSet)

    def with_entity(
        self,
        entity: EntityWrapper,
        op: Literal["ADDED", "DELETED", "MODIFIED"],
        current_appgate_state: "AppgateState",
    ) -> None:
        """
        Get the entity with op and register in the current state
        These entities are coming from k8s so they don't have any id
        """
        entities_fn = lambda state: state.entities_set.get(type(entity.value).__name__)
        entities = entities_fn(self)
        current_entities = entities_fn(current_appgate_state)
        if not entities or not current_entities:
            log.error("[appgate-operator] Unknown entity type: %s", type(entity))
            return
        entities_op(entities, entity, op, current_entities)

    def sync_generations(self) -> "AppgateState":
        return AppgateState(
            entities_set={
                k: EntitiesSet({entity_sync_generation(e) for e in v.entities})
                for k, v in self.entities_set.items()
            }
        )

    def copy(self, entities_set: Dict[str, EntitiesSet]) -> "AppgateState":
        new_entities_set = {}
        for k, v in self.entities_set.items():
            if k in entities_set:
                new_entities_set[k] = entities_set[k]
            else:
                new_entities_set[k] = v
        return AppgateState(new_entities_set)

    def dump(
        self,
        api_version: str,
        output_dir: Optional[Path] = None,
        stdout: bool = False,
        target_tags: Optional[FrozenSet[str]] = None,
        exclude_tags: Optional[FrozenSet[str]] = None,
    ) -> None:
        dump_dir = None
        if not stdout:
            output_dir_format = (
                f'{str(datetime.date.today())}_{time.strftime("%H-%M")}-entities'
            )
            dump_dir = output_dir or Path(output_dir_format)
            dump_dir.mkdir(exist_ok=True)
        password_fields = {}
        for (i, (k, v)) in enumerate(self.entities_set.items()):
            if stdout and i > 0:
                print("---\n")
            p = dump_dir / f"{k.lower()}.yaml" if dump_dir else None
            entities_to_dump = exclude_appgate_entities(
                entities=self.entities_set[k].entities,
                target_tags=target_tags,
                exclude_tags=exclude_tags,
            )
            entity_password_fields = dump_entities(entities_to_dump, api_version, p, k)
            if entity_password_fields:
                password_fields[k] = entity_password_fields
        if len(password_fields) > 0:
            print("Passwords found in entities:")
            for entity_name, pwd_fields in password_fields.items():
                print(f"+ Entity: {entity_name}")
                for password_field in pwd_fields:
                    print(f"  - {password_field}")


def entity_sync_generation(entity_wrapper: EntityWrapper) -> EntityWrapper:
    """
    Syncs current generation to latest.
    """
    entity = entity_wrapper.value
    appgate_metadata = evolve(
        entity.appgate_metadata,
        latest_generation=entity.appgate_metadata.current_generation,
    )
    return EntityWrapper(evolve(entity, appgate_metadata=appgate_metadata))


def merge_entities(
    share: EntitiesSet,
    create: EntitiesSet,
    modify: EntitiesSet,
    errors: Optional[Set[str]] = None,
) -> EntitiesSet:
    entities = set()
    errors = errors or set()
    entities.update(share.entities)
    entities.update(
        {entity_sync_generation(e) for e in modify.entities if e.id not in errors}
    )
    entities.update({e for e in create.entities if e.id not in errors})
    return EntitiesSet(entities)


@attrs
class Plan:
    share: EntitiesSet = attrib(factory=EntitiesSet)
    delete: EntitiesSet = attrib(factory=EntitiesSet)
    not_to_delete: EntitiesSet = attrib(factory=EntitiesSet)
    create: EntitiesSet = attrib(factory=EntitiesSet)
    not_to_create: EntitiesSet = attrib(factory=EntitiesSet)
    modify: EntitiesSet = attrib(factory=EntitiesSet)
    not_to_modify: EntitiesSet = attrib(factory=EntitiesSet)
    modifications_diff: Dict[str, List[str]] = attrib(factory=dict)
    errors: Optional[Set[str]] = attrib(default=None)

    @cached_property
    def expected_entities(self) -> EntitiesSet:
        """
        Set with all the names in the system in this plan
        """
        return merge_entities(self.share, self.create, self.modify)

    @cached_property
    def entities(self) -> EntitiesSet:
        entities = merge_entities(
            share=self.share, create=self.create, modify=self.modify, errors=self.errors
        )
        entities.entities.update(
            {e for e in self.delete.entities if e.id in (self.errors or set())}
        )
        return entities

    @cached_property
    def expected_names(self) -> Dict[str, str]:
        """
        Set with all the names in the system in this plan
        """
        return {k: v.id for k, v in self.expected_entities.entities_by_name.items()}

    @cached_property
    def expected_ids(self) -> Set[str]:
        """
        Set with all the ids in the system in this plan
        """
        return set(self.expected_entities.entities_by_id.keys())

    @cached_property
    def needs_apply(self) -> bool:
        return (
            len(self.delete.entities or self.create.entities or self.modify.entities)
            > 0
        )


# TODO: Save the kind info the wrapper
async def plan_apply(
    plan: Plan,
    namespace: str,
    k8s_configmap_client: K8SConfigMapClient,
    appgate_entity_client: Optional[AppgateEntityClient] = None,
    k8s_entity_client: Optional[K8sEntityClient] = None,
) -> Plan:
    errors = set()
    for e in plan.create.entities:
        log.info(
            "[appgate-operator/%s] + %s: %s [%s]",
            namespace,
            type(e.value),
            e.name,
            e.id,
        )
        if appgate_entity_client:
            try:
                await appgate_entity_client.post(e.value)
                name = (
                    "singleton"
                    if e.value._entity_metadata.get("singleton", False)
                    else e.name
                )
                await k8s_configmap_client.update_entity_generation(
                    key=entity_unique_id(e.value.__class__.__name__, name),
                    generation=e.value.appgate_metadata.current_generation,
                )
            except Exception as err:
                errors.add(f"{e.name} [{e.id}]: {str(err)}")
        elif k8s_entity_client:
            try:
                await k8s_entity_client.create()
            except Exception as err:
                errors.add(f"{e.name} [{e.id}]: {str(err)}")
    if is_debug():
        for e in plan.not_to_create.entities:
            log.debug(
                "[appgate-operator/%s] !+ %s: %s [%s]",
                namespace,
                e.value.__class__.__name__,
                e.name,
                e.id,
            )

    for e in plan.modify.entities:
        log.info(
            "[appgate-operator/%s] * %s: %s [%s]",
            namespace,
            e.value.__class__.__name__,
            e.name,
            e.id,
        )
        diff = plan.modifications_diff.get(e.name)
        if diff:
            log.info("[appgate-operator/%s]    DIFF for %s:", namespace, e.name)
            for d in diff:
                log.info("%s", d.rstrip())
        if appgate_entity_client:
            try:
                await appgate_entity_client.put(e.value)
                name = (
                    "singleton"
                    if e.value._entity_metadata.get("singleton", False)
                    else e.name
                )
                await k8s_configmap_client.update_entity_generation(
                    key=entity_unique_id(e.value.__class__.__name__, name),
                    generation=e.value.appgate_metadata.current_generation,
                )
            except Exception as err:
                errors.add(f"{e.name} [{e.id}]: {str(err)}")
        elif k8s_entity_client:
            try:
                await k8s_entity_client.modify()
            except Exception as err:
                errors.add(f"{e.name} [{e.id}]: {str(err)}")
    if is_debug():
        for e in plan.not_to_modify.entities:
            log.debug(
                "[appgate-operator/%s] !* %s: %s [%s]",
                namespace,
                e.value.__class__.__name__,
                e.name,
                e.id,
            )

    for e in plan.delete.entities:
        log.info(
            "[appgate-operator/%s] - %s: %s [%s]",
            namespace,
            e.value.__class__.__name__,
            e.name,
            e.id,
        )
        if appgate_entity_client:
            try:
                await appgate_entity_client.delete(e.id)
                name = (
                    "singleton"
                    if e.value._entity_metadata.get("singleton", False)
                    else e.name
                )
                await k8s_configmap_client.delete_entity_generation(
                    entity_unique_id(e.value.__class__.__name__, name)
                )
            except Exception as err:
                errors.add(f"{e.name} [{e.id}]: {str(err)}")
        elif k8s_entity_client:
            try:
                await k8s_entity_client.delete()
            except Exception as err:
                errors.add(f"{e.name} [{e.id}]: {str(err)}")
    if is_debug():
        for e in plan.not_to_delete.entities:
            log.debug(
                "[appgate-operator/%s] !- %s: %s [%s]",
                namespace,
                e.value.__class__.__name__,
                e.name,
                e.id,
            )

    for e in plan.share.entities:
        log.debug(
            "[appgate-operator/%s] = %s: %s [%s]",
            namespace,
            e.value.__class__.__name__,
            e.name,
            e.id,
        )

    has_errors = len(errors) > 0
    return Plan(
        create=plan.create,
        not_to_create=plan.not_to_create,
        share=plan.share,
        delete=plan.delete,
        not_to_delete=plan.not_to_delete,
        modify=plan.modify,
        not_to_modify=plan.not_to_modify,
        modifications_diff=plan.modifications_diff,
        errors=errors if has_errors else None,
    )


@attrs
class AppgatePlan:
    entities_plan: Dict[str, Plan] = attrib()

    @cached_property
    def appgate_state(self) -> AppgateState:
        """
        Return an AppgateState from the AppgatePlan
        It will synchronized the current and latest generation since this is called
        once a plan has been applied properly.
        """
        return AppgateState({k: v.entities for k, v in self.entities_plan.items()})

    @cached_property
    def needs_apply(self) -> bool:
        return any(v.needs_apply for v in self.entities_plan.values())

    def ordered_entities_plan(self, api_spec: APISpec) -> Iterator[Tuple[str, Plan]]:
        return map(lambda k: (k, self.entities_plan[k]), api_spec.entities_sorted)

    @cached_property
    def errors(self) -> List[str]:
        maybe_errors = filter(
            None, map(lambda p: p.errors, self.entities_plan.values())
        )
        errors = list(
            filter(lambda s: len(s) > 0, itertools.chain.from_iterable(maybe_errors))
        )
        return errors


async def appgate_plan_apply(
    appgate_plan: AppgatePlan,
    namespace: str,
    entity_clients: Dict[str, AppgateEntityClient],
    k8s_configmap_client: K8SConfigMapClient,
    api_spec: APISpec,
) -> AppgatePlan:
    log.info("[appgate-operator/%s] AppgatePlan Summary:", namespace)
    entities_plan = {
        k: await plan_apply(
            v,
            namespace=namespace,
            appgate_entity_client=entity_clients.get(k),
            k8s_configmap_client=k8s_configmap_client,
        )
        for k, v in appgate_plan.ordered_entities_plan(api_spec)
    }
    return AppgatePlan(entities_plan=entities_plan)


def entities_conflict_summary(
    conflicts: Dict[str, List[MissingFieldDependencies]], namespace: str
) -> None:
    for entity_name, missing_field_deps in conflicts.items():
        for missing_field_dep in missing_field_deps:
            p1 = "they are" if len(missing_field_dep.dependencies) > 1 else "it is"
            missing_deps_str = ",".join(missing_field_dep.dependencies)
            log.error(
                "[appgate-operator/%s] Entity: %s [%s] references %s (field %s), but %s not defined "
                "in the system.",
                namespace,
                missing_field_dep.parent_name,
                missing_field_dep.parent_type,
                missing_deps_str,
                missing_field_dep.field_path,
                p1,
            )


def compute_diff(e1: EntityWrapper, e2: EntityWrapper) -> List[str]:
    """
    Computes a list with differences between e1 and e2.
    e1 is current entity
    e2 is expected entity
    """
    e1_dump = DIFF_DUMPER.dump(e1.value)
    e2_dump = DIFF_DUMPER.dump(e2.value)
    if e2.has_secrets() and e2.changed_generation():
        e1_dump["generation"] = e2.value.appgate_metadata.latest_generation
        e2_dump["generation"] = e2.value.appgate_metadata.current_generation
    elif e2.has_secrets() and e2.updated(e1):
        updated_field = getattr(e1.value, "updated", None)
        if updated_field:
            e1_dump["updated"] = dump_datetime(updated_field)
            e2_dump["updated"] = dump_datetime(e2.value.appgate_metadata.modified)
    diff = list(
        difflib.unified_diff(
            json.dumps(e1_dump, indent=4).splitlines(keepends=True),
            json.dumps(e2_dump, indent=4).splitlines(keepends=True),
            n=1,
        )
    )
    return diff


def compare_entities(
    current: EntitiesSet,
    expected: EntitiesSet,
    builtin_tags: FrozenSet[str],
    target_tags: Optional[FrozenSet[str]],
    excluded_tags: Optional[FrozenSet[str]] = None,
) -> Plan:
    current_entities = {e for e in current.entities if is_target(e, target_tags)}
    current_names = {e.name for e in current_entities}
    expected_entities = {e for e in expected.entities if is_target(e, target_tags)}
    expected_names = {e.name for e in expected_entities}
    shared_names = current_names.intersection(expected_names)

    ignore_tags = builtin_tags.union(excluded_tags or frozenset())

    def _to_delete_filter(e: EntityWrapper) -> bool:
        return e.name not in expected_names and not has_tag(e, ignore_tags)

    def _to_create_filter(e: EntityWrapper) -> bool:
        return e.name not in current_names and e.name not in shared_names

    def _to_modify_filter(e: EntityWrapper) -> bool:
        return e.name in shared_names and e not in current_entities

    def _to_share_filter(e: EntityWrapper) -> bool:
        return e.name in shared_names and e in current_entities

    # Compute the set of entities to delete
    #  - Don't delete builtin entities
    #  - Don't delete entities that are not in target (if target set is
    #    not defined, all entities are in target)
    xs, ys = itertools.tee(current_entities)
    to_delete = EntitiesSet(set(filter(_to_delete_filter, xs)))
    not_to_delete = EntitiesSet(set(itertools.filterfalse(_to_delete_filter, ys)))

    # Compute the set of entities to create
    xs, ys = itertools.tee(expected_entities)
    to_create = EntitiesSet(set(filter(_to_create_filter, xs)))
    not_to_create = EntitiesSet(set(itertools.filterfalse(_to_create_filter, ys)))

    # Compute the set of entities to modify
    #  - Don't modify entities that are not in target (if target set is
    #    not defined, all entities are in target)
    xs, ys = itertools.tee(expected_entities)
    to_modify = EntitiesSet(set(filter(_to_modify_filter, xs)))
    not_to_modify = EntitiesSet(set(itertools.filterfalse(_to_modify_filter, ys)))

    modifications_diff = {}
    for e in to_modify.entities:
        current_entity = current.entities_by_name.get(e.name)
        if not current_entity:
            log.warning(
                f"Trying to compute diff for entity %s [%s] but not registered",
                e.name,
                e.id,
            )
            continue
        diff = compute_diff(current_entity, e)
        if diff:
            modifications_diff[e.name] = diff
    to_share = EntitiesSet(set(filter(_to_share_filter, expected_entities)))

    return Plan(
        delete=to_delete,
        not_to_delete=not_to_delete,
        create=to_create,
        not_to_create=not_to_create,
        modify=to_modify,
        not_to_modify=not_to_modify,
        modifications_diff=modifications_diff,
        share=to_share,
    )


def entity_t_attribute_names(entity: Entity_T) -> Iterable[str]:
    return map(lambda a: a.name, getattr(entity, "__attrs_attrs__", []))


def get_field(
    entity: Entity_T, paths: List[str]
) -> Tuple[Optional[Any], Optional[str]]:
    f: Any = entity
    for i, p in enumerate(paths):
        log.trace("Getting field %s in %s", p, list(entity_t_attribute_names(f)))
        if isinstance(f, frozenset):
            return f, ".".join(paths[i:])
        f = getattr(f, p, None)
        if f is None:
            if len(paths[i:]):
                # Last field is None, it could an optional field (should be checked here)
                return frozenset(), p
            else:
                return None, ".".join(paths[i:])
    return f, None


def evolve_rec(entity: Entity_T, path: List[str], value: Any) -> Entity_T:
    if len(path) == 1:
        return evolve(entity, **{path[0]: value})
    field = getattr(entity, path[0], None)
    if field and type(field) not in PYTHON_TYPES:
        return evolve(entity, **{path[0]: evolve_rec(field, path[1:], value)})
    raise Exception(f"Field {path[0]} not found in {entity}")


def resolve_field_entity(
    entity: Entity_T,
    field: str,
    parent_dependency: Entity_T,
    names: Dict[str, EntityWrapper],
    ids: Dict[str, EntityWrapper],
    missing_dependencies: Dict[str, List[MissingFieldDependencies]],
    reverse: bool = False,
) -> Optional[EntityWrapper]:
    ident_level = 4
    new_dependencies = set()
    missing_dependencies_set = set()
    log.trace(
        f"[appgate-state] %s getting field %s in entity %s",
        " " * (ident_level + 2),
        field,
        entity.__class__.__name__,
    )
    dependencies, rest_fields = get_field(entity, field.split("."))
    if dependencies is None:
        raise Exception(f"Object {entity} has not field {field}.")
    is_iterable = isinstance(dependencies, frozenset)
    if not is_iterable:
        dependencies = frozenset({dependencies})
    if dependencies and not rest_fields:
        log.debug(
            "[appgate-state] %s dependencies: %s",
            " " * ident_level,
            ",".join(dependencies),
        )
    # Iterate over all the items in the field
    for dependency in dependencies:
        if type(dependency) not in PYTHON_TYPES and rest_fields:
            log.trace(
                "[appgate-state] %s dependency %s and rest_fields %s",
                " " * ident_level,
                dependency.__class__.__name__,
                rest_fields,
            )
            res = resolve_field_entity(
                dependency,
                rest_fields,
                parent_dependency,
                names,
                ids,
                missing_dependencies,
                reverse,
            )
            if res:
                continue
        elif dependency in ids:
            # dependency is an id
            log.debug("[appgate-state] %s found id %s", " " * ident_level, dependency)
            if reverse:
                new_dependencies.add(ids[dependency].name)
            else:
                new_dependencies.add(dependency)
            continue
        elif dependency in names and names[dependency].id:
            log.debug("[appgate-state] %s found name %s", " " * ident_level, dependency)
            # dependency is a name
            if reverse:
                new_dependencies.add(dependency)
            else:
                new_dependencies.add(names[dependency].id)
            continue
        else:
            if is_debug():
                log.error(
                    "[appgate-state] %s MISSING %s", " " * ident_level, dependency
                )
            missing_dependencies_set.add(dependency)
    if missing_dependencies_set:
        if parent_dependency.name not in missing_dependencies:
            missing_dependencies[parent_dependency.name] = []
        missing_dependencies[parent_dependency.name].append(
            MissingFieldDependencies(
                field_path=field,
                parent_name=parent_dependency.name,
                parent_type=parent_dependency.__class__.__qualname__,
                dependencies=frozenset(missing_dependencies_set),
            )
        )
    # Only return resolved dependencies if all of them were resolved!
    if new_dependencies and len(new_dependencies) == len(dependencies):
        if not is_iterable:
            return EntityWrapper(
                evolve_rec(entity, field.split("."), list(new_dependencies)[0])
            )
        else:
            return EntityWrapper(
                evolve_rec(entity, field.split("."), frozenset(new_dependencies))
            )
    return None


def resolve_field_entities(
    e1: EntitiesSet, dependencies: List[EntityFieldDependency], reverse: bool = False
) -> Tuple[EntitiesSet, Optional[Dict[str, List[MissingFieldDependencies]]]]:
    """
    resolve entity dependencies for entities in the EntitiesSet e1.
    Dependencies is a list of EntityFieldDependency.

    """
    indent_level = 2
    to_remove = set()
    to_add = set()
    missing_entities: Dict[str, List[MissingFieldDependencies]] = {}
    e1_set = e1.entities.copy()
    field_path = None
    names = {}
    ids = {}
    for dep in dependencies:
        if field_path is not None and field_path != dep.field_path:
            raise AppgateException(
                "Fatal error, found different fields when resolving entities"
            )
        else:
            field_path = dep.field_path
        names.update(dep.known_entities.entities_by_name)
        ids.update(dep.known_entities.entities_by_id)

    # Not found field_path, so nothing to resolve
    if not field_path:
        return EntitiesSet(e1_set), None
    if is_debug():
        for k, v in names.items():
            log.debug(
                "[appgate-state] %s + available %s [%s | %s]",
                " " * indent_level,
                v.value.__class__.__name__,
                k,
                v.id,
            )
    for e in e1_set:
        log.debug(
            "[appgate-state] %s - check %s [%s | %s]",
            " " * indent_level,
            e.value.__class__.__name__,
            e.name,
            e.id,
        )
        new_e = None
        new_e = resolve_field_entity(
            (new_e or e).value,
            field_path,
            (new_e or e).value,
            names,
            ids,
            missing_entities,
            reverse,
        )
        if new_e:
            to_remove.add(e)
            to_add.add(new_e)
    e1_set.difference_update(to_remove)
    e1_set.update(to_add)
    if len(missing_entities) > 0:
        return (
            EntitiesSet(e1_set),
            missing_entities,
        )
    return EntitiesSet(e1_set), None


def resolve_appgate_state(
    expected_state: AppgateState,
    total_appgate_state: AppgateState,
    api_spec: APISpec,
    reverse: bool = False,
) -> Dict[str, List[MissingFieldDependencies]]:
    entities = api_spec.entities
    entities_sorted = api_spec.entities_sorted
    total_conflicts: Dict[str, List[MissingFieldDependencies]] = {}
    log.info("[appgate-state] Validating expected state entities")
    log.info("[appgate-state] Resolving dependencies in order: %s", entities_sorted)
    # Iterate over all known entities in the API
    for entity_name in entities_sorted:
        if entity_name not in expected_state.entities_set:
            # We don't have entities of this type so try the next entity.
            continue
        # Each generated entity can have several field that describe dependencies
        # to another entities. Iterate over each field describing a dependency.
        for field_dependency in entities[entity_name].dependencies:
            log.debug(
                "[appgate-state] Checking dependencies for %s.%s => %s",
                entity_name,
                field_dependency.field_path,
                ",".join(field_dependency.dependencies),
            )
            dependencies: List[EntityFieldDependency] = []
            # Finally, each field can reference 1 or more entities.
            # For example, we could have a field `myId` that could contain
            # references for EntityA or EntityB
            for d in field_dependency.dependencies:
                known_entities = EntitiesSet()
                known_entities.extend(
                    total_appgate_state.entities_set.get(d, EntitiesSet())
                )
                known_entities.extend(expected_state.entities_set.get(d, EntitiesSet()))
                dependencies.append(
                    EntityFieldDependency(
                        entity_name=entity_name,
                        field_path=field_dependency.field_path,
                        known_entities=known_entities,
                    )
                )
            e1 = expected_state.entities_set.get(entity_name, EntitiesSet())
            new_e1, conflicts = resolve_field_entities(e1, dependencies, reverse)
            # Merge new conflicts
            if conflicts:
                for e, ds in conflicts.items():
                    if e in total_conflicts:
                        total_conflicts[e] = total_conflicts[e] + ds
                    else:
                        total_conflicts[e] = ds

            expected_state.entities_set[entity_name] = new_e1
    return total_conflicts


def create_appgate_plan(
    current_state: AppgateState,
    expected_state: AppgateState,
    builtin_tags: FrozenSet[str],
    target_tags: Optional[FrozenSet[str]],
    excluded_tags: Optional[FrozenSet[str]],
) -> AppgatePlan:
    """
    Creates a new AppgatePlan to apply
    """
    entities_plan = {
        k: compare_entities(
            current_state.entities_set[k], v, builtin_tags, target_tags, excluded_tags
        )
        for k, v in expected_state.entities_set.items()
    }
    return AppgatePlan(entities_plan=entities_plan)
