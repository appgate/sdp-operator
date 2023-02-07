import datetime
import functools
import os
from copy import deepcopy
from pathlib import Path
from typing import (
    Dict,
    Any,
    FrozenSet,
    Optional,
    List,
    Set,
    Literal,
    Union,
    Tuple,
    TypeAlias,
)
from attr import attrib, attrs, evolve

from appgate.openapi.types import (
    Entity_T,
    APISpec,
    AppgateException,
    K8S_APPGATE_DOMAIN,
    is_singleton,
)
from appgate.openapi.utils import is_entity_t

__all__ = [
    "K8SEvent",
    "EventObject",
    "AppgateEvent",
    "AppgateEventError",
    "AppgateEventSuccess",
    "EntityWrapper",
    "has_tag",
    "is_target",
    "EntitiesSet",
    "LatestEntityGeneration",
    "AppgateOperatorArguments",
    "GitOperatorArguments",
    "AppgateOperatorContext",
    "GitOperatorContext",
    "BUILTIN_TAGS",
    "EntityFieldDependency",
    "APPGATE_LOG_LEVEL",
    "USER_ENV",
    "PASSWORD_ENV",
    "PROVIDER_ENV",
    "DEVICE_ID_ENV",
    "TIMEOUT_ENV",
    "HOST_ENV",
    "DRY_RUN_ENV",
    "CLEANUP_ENV",
    "NAMESPACE_ENV",
    "TWO_WAY_SYNC_ENV",
    "SPEC_DIR_ENV",
    "APPGATE_SECRETS_KEY",
    "APPGATE_MT_CONFIGMAP_ENV",
    "APPGATE_SSL_CACERT",
    "APPGATE_SSL_NO_VERIFY",
    "APPGATE_EXCLUDE_TAGS_ENV",
    "APPGATE_TARGET_TAGS_ENV",
    "APPGATE_BUILTIN_TAGS_ENV",
    "get_tags",
    "get_dry_run",
    "ensure_env",
    "GIT_REPOSITORY_ENV",
    "GIT_VENDOR_ENV",
    "GIT_BASE_BRANCH_ENV",
    "GIT_DUMP_DIR",
    "GIT_REPOSITORY_FORK_ENV",
    "GITHUB_TOKEN_ENV",
    "GIT_SSH_KEY_PATH",
    "EntityClient",
    "GitCommitState",
    "crd_domain",
    "APPGATE_OPERATOR_PR_LABEL_NAME",
    "APPGATE_OPERATOR_PR_LABEL_COLOR",
    "APPGATE_OPERATOR_PR_LABEL_DESC",
    "GIT_REPOSITORY_MAIN_BRANCH",
    "GIT_REPOSITORY_MAIN_BRANCH_ENV",
]

from appgate.syncer.git import GitVendor

BUILTIN_TAGS = frozenset({"builtin"})
APPGATE_LOG_LEVEL = "APPGATE_OPERATOR_LOG_LEVEL"
USER_ENV = "APPGATE_OPERATOR_USER"
PASSWORD_ENV = "APPGATE_OPERATOR_PASSWORD"
PROVIDER_ENV = "APPGATE_OPERATOR_PROVIDER"
DEVICE_ID_ENV = "APPGATE_OPERATOR_DEVICE_ID"
TIMEOUT_ENV = "APPGATE_OPERATOR_TIMEOUT"
HOST_ENV = "APPGATE_OPERATOR_HOST"
DRY_RUN_ENV = "APPGATE_OPERATOR_DRY_RUN"
CLEANUP_ENV = "APPGATE_OPERATOR_CLEANUP"
NAMESPACE_ENV = "APPGATE_OPERATOR_NAMESPACE"
TWO_WAY_SYNC_ENV = "APPGATE_OPERATOR_TWO_WAY_SYNC"
SPEC_DIR_ENV = "APPGATE_OPERATOR_SPEC_DIRECTORY"
APPGATE_SECRETS_KEY = "APPGATE_OPERATOR_FERNET_KEY"
APPGATE_MT_CONFIGMAP_ENV = "APPGATE_OPERATOR_CONFIG_MAP"
APPGATE_SSL_NO_VERIFY = "APPGATE_OPERATOR_SSL_NO_VERIFY"
APPGATE_SSL_CACERT = "APPGATE_OPERATOR_CACERT"
APPGATE_EXCLUDE_TAGS_ENV = "APPGATE_OPERATOR_EXCLUDE_TAGS"
APPGATE_TARGET_TAGS_ENV = "APPGATE_OPERATOR_TARGET_TAGS"
APPGATE_BUILTIN_TAGS_ENV = "APPGATE_OPERATOR_BUILTIN_TAGS"

GIT_REPOSITORY_MAIN_BRANCH_ENV = "GIT_MAIN_BRANCH"
GIT_REPOSITORY_MAIN_BRANCH = "master"
GIT_REPOSITORY_ENV = "GIT_REPOSITORY"
GIT_REPOSITORY_FORK_ENV = "GIT_REPOSITORY_FORK"
GIT_BASE_BRANCH_ENV = "GIT_BASE_BRANCH"
GIT_VENDOR_ENV = "GIT_VENDOR"
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
GITLAB_TOKEN_ENV = "GITLAB_TOKEN"

GIT_DUMP_DIR: Path = Path("/entities")

GIT_SSH_KEY_PATH = Path("/opt/git-operator/k8s/deployment.key")

APPGATE_OPERATOR_PR_LABEL_NAME = "sdp-operator"
APPGATE_OPERATOR_PR_LABEL_COLOR = "f213e3"
APPGATE_OPERATOR_PR_LABEL_DESC = "Pullrequest created by sdp-operator"


GitCommitState = Literal["ADD", "DELETE", "MODIFY"]


class EntityClient:
    async def init(self) -> "EntityClient":
        return self

    async def create(self, e: Entity_T) -> "EntityClient":
        raise NotImplementedError

    async def delete(self, e: Entity_T) -> "EntityClient":
        raise NotImplementedError

    async def modify(self, e: Entity_T) -> "EntityClient":
        raise NotImplementedError

    async def commit(self) -> Tuple["EntityClient", List[Tuple[str, GitCommitState]]]:
        return self, []


@attrs(slots=True, frozen=True)
class AppgateOperatorArguments:
    namespace: Optional[str] = attrib(default=None)
    spec_directory: Optional[str] = attrib(default=None)
    no_dry_run: bool = attrib(default=False)
    host: Optional[str] = attrib(default=None)
    user: Optional[str] = attrib(default=None)
    password: Optional[str] = attrib(default=None)
    provider: str = attrib(default="local")
    no_two_way_sync: bool = attrib(default=False)
    timeout: str = attrib(default="30")
    no_cleanup: bool = attrib(default=False)
    target_tags: List[str] = attrib(factory=list)
    builtin_tags: List[str] = attrib(factory=list)
    exclude_tags: List[str] = attrib(factory=list)
    metadata_configmap: Optional[str] = attrib(default=None)
    no_verify: bool = attrib(default=False)
    cafile: Optional[Path] = attrib(default=None)
    device_id: Optional[str] = attrib(default=None)
    reverse_mode: bool = attrib(default=False)


@attrs(slots=True, frozen=True)
class GitOperatorArguments:
    namespace: Optional[str] = attrib(default=None)
    spec_directory: Optional[str] = attrib(default=None)
    no_dry_run: bool = attrib(default=False)
    timeout: str = attrib(default="30")
    target_tags: List[str] = attrib(factory=list)


@attrs(slots=True, frozen=True)
class EventObject:
    spec: Dict[str, Any] = attrib()
    metadata: Dict[str, Any] = attrib()
    kind: str = attrib()


@attrs(slots=True, frozen=True)
class K8SEvent:
    type: Literal["ADDED", "DELETED", "MODIFIED"] = attrib()
    object: EventObject = attrib()


@attrs(slots=True, frozen=True)
class AppgateEventError:
    name: str = attrib()
    kind: str = attrib()
    error: str = attrib()


@attrs(slots=True, frozen=True)
class AppgateEventSuccess:
    op: Literal["ADDED", "DELETED", "MODIFIED"] = attrib()
    entity: Entity_T = attrib()


AppgateEvent = Union[AppgateEventError, AppgateEventSuccess]


class EntityWrapper:
    def __init__(self, entity: Entity_T) -> None:
        self.value = entity

    @property
    def name(self) -> str:
        return self.value.name

    @property
    def id(self) -> str:
        return self.value.id

    @property
    def tags(self) -> FrozenSet[str]:
        return self.value.tags

    def with_id(self, id: str) -> "EntityWrapper":
        return EntityWrapper(evolve(self.value, id=id))

    def changed_generation(self) -> bool:
        mt = self.value.appgate_metadata
        if mt.current_generation > mt.latest_generation:
            return True
        return False

    def updated(self, other: object) -> bool:
        assert isinstance(other, self.__class__)
        mt = self.value.appgate_metadata
        if getattr(other.value, "updated", None) is not None:
            return mt.modified > (other.value.updated + datetime.timedelta(seconds=2))
        return False

    def needs_update(self, other: object) -> bool:
        if self.changed_generation():
            return True
        if self.updated(other):
            return True
        return False

    def is_singleton(self) -> bool:
        return is_singleton(self.value)

    def has_secrets(self) -> bool:
        # We have passwords use modified/created
        entity_mt = self.value._entity_metadata
        return len(entity_mt.get("passwords", {})) > 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            raise Exception(f"Wrong other argument {other}")
        if not self.has_secrets():
            return self.value == other.value
        if (
            self.value.appgate_metadata.from_appgate
            and not other.value.appgate_metadata.from_appgate
        ):
            if other.needs_update(self):
                return False
        elif (
            not self.value.appgate_metadata.from_appgate
            and other.value.appgate_metadata.from_appgate
        ):
            if self.needs_update(other):
                return False
        return self.value == other.value

    def __hash__(self) -> int:
        return self.value.__hash__()

    def __repr__(self):
        return self.value.__repr__()


def has_tag(entity: EntityWrapper, tags: Optional[FrozenSet[str]] = None) -> bool:
    """
    Predicate that return true if entity has any tag in the set tags
    """
    return tags is not None and any(
        map(lambda t: t in (entity.tags or frozenset()), tags)
    )


def is_target(
    entity: EntityWrapper, target_tags: Optional[FrozenSet[str]] = None
) -> bool:
    """
    Predicate that return true if entity is member of the target set.
    An entity is member of the target set if target is not defined at all or if it has
    any tag that belongs to the set of target_tags
    """
    return target_tags is None or has_tag(entity, target_tags)


class EntitiesSet:
    def __init__(
        self,
        entities: Optional[Set[EntityWrapper]] = None,
        entities_by_name: Optional[Dict[str, EntityWrapper]] = None,
        entities_by_id: Optional[Dict[str, EntityWrapper]] = None,
    ) -> None:
        self.entities: Set[EntityWrapper] = entities or set()
        if entities_by_name:
            self.entities_by_name = entities_by_name
        else:
            self.entities_by_name = {}
            for e in self.entities:
                if is_entity_t(e):
                    self.entities_by_name[e.name] = e
        if entities_by_id:
            self.entities_by_id = entities_by_id
        else:
            self.entities_by_id = {}
            for e in self.entities:
                if is_entity_t(e):
                    self.entities_by_id[e.id] = e

    def __str__(self) -> str:
        return str(self.entities)

    def __copy__(self) -> "EntitiesSet":
        return EntitiesSet(
            entities=deepcopy(self.entities),
            entities_by_name=deepcopy(self.entities_by_name),
            entities_by_id=deepcopy(self.entities_by_id),
        )

    def entities_with_tags(self, tags: FrozenSet[str]) -> "EntitiesSet":
        return EntitiesSet(entities={e for e in self.entities if has_tag(e, tags)})

    def add(self, entity: EntityWrapper) -> None:
        if entity.name in self.entities_by_name:
            # Entity is already registered, so this is in the best case a modification
            return self.modify(entity)
        self.entities.add(entity)
        # Register it in the maps of ids and names
        self.entities_by_name[entity.name] = entity
        self.entities_by_id[entity.id] = entity

    def delete(self, entity: EntityWrapper) -> None:
        if entity in self.entities:
            self.entities.remove(entity)
        if entity.name in self.entities_by_name:
            registered_id = self.entities_by_name[entity.name].id
            del self.entities_by_name[entity.name]
            del self.entities_by_id[registered_id]
        if entity.id in self.entities_by_id:
            del self.entities_by_id[entity.id]

    def modify(self, entity: EntityWrapper) -> None:
        if entity.name not in self.entities_by_name:
            # Not yet in the system, register it with its own id
            return self.add(entity)
        # All the entities expect the one being modified
        self.entities = {e for e in self.entities if e.name != entity.name}
        # Replace always the id with the one registered in the system
        self.entities.add(entity.with_id(id=self.entities_by_name[entity.name].id))

    def extend(self, other: "EntitiesSet") -> None:
        """
        Extends current entity set with other
        """
        for entity in other.entities:
            self.modify(entity)


@attrs(slots=True, frozen=True)
class LatestEntityGeneration:
    generation: int = attrib(default=0)
    modified: datetime.datetime = attrib(default=datetime.datetime.now().astimezone())


@attrs()
class AppgateOperatorContext:
    namespace: str = attrib()
    user: str = attrib()
    password: str = attrib()
    provider: str = attrib()
    controller: str = attrib()
    two_way_sync: bool = attrib()
    timeout: int = attrib()
    dry_run_mode: bool = attrib()
    cleanup_mode: bool = attrib()
    api_spec: APISpec = attrib()
    metadata_configmap: str = attrib()
    reverse_mode: bool = attrib()
    # target tags if specified tells which entities do we want to work on
    target_tags: Optional[FrozenSet[str]] = attrib(default=None)
    # builtin tags are the entities that we consider builtin
    builtin_tags: FrozenSet[str] = attrib(default=BUILTIN_TAGS)
    # exclude tags if specified tells which entities do we want to exclude
    exclude_tags: Optional[FrozenSet[str]] = attrib(default=None)
    no_verify: bool = attrib(default=True)
    cafile: Optional[Path] = attrib(default=None)
    device_id: Optional[str] = attrib(default=None)


@attrs()
class GitOperatorContext:
    namespace: str = attrib()
    api_spec: APISpec = attrib()
    timeout: int = attrib()
    log_level: str = attrib()
    git_repository: str = attrib()
    git_repository_fork: str | None = attrib()
    git_vendor: GitVendor = attrib()
    git_base_branch: str = attrib()
    target_tags: FrozenSet[str] | None = attrib(default=None)
    dry_run: bool = attrib(default=True)
    main_branch: str = attrib(default=GIT_REPOSITORY_MAIN_BRANCH)


@attrs(slots=True, frozen=True)
class EntityFieldDependency:
    """
    Class used to store information about field dependencies for an entity:
     - entity_name :: is the name of the entity for which we know
       the dependencies
     - field_path :: is the field (field1.field2 ...) where the
       entity has a dependency
     - known_entities :: is an EntitySet of known entities that match the
       field where the entity has a dependency on.
    """

    entity_name: str = attrib()
    field_path: str = attrib()
    known_entities: EntitiesSet = attrib(factory=EntitiesSet)


def get_tags(tags: List[str], env_tags: str | None) -> FrozenSet[str]:
    xs = frozenset(tags)
    if env_tags:
        return xs.union(env_tags.split(","))
    return xs


def get_dry_run(no_dry_run_arg: bool) -> bool:
    env_dry_run = os.getenv(DRY_RUN_ENV)
    return to_bool(env_dry_run) if env_dry_run is not None else not no_dry_run_arg


def to_bool(value: Optional[str]) -> bool:
    if value:
        # Helm JSON schema validation ensures that the input is true/false string
        bool_map = {"true": True, "false": False}
        return bool_map[value.lower()]
    return False


def ensure_env(env_name: str) -> str:
    v = os.getenv(env_name)
    if not v:
        raise AppgateException(f"Environment Variable {env_name} is not defined!")
    return v


@functools.lru_cache
def crd_domain(api_version: int) -> str:
    return f"v{api_version}.{K8S_APPGATE_DOMAIN}"


OperatorMode: TypeAlias = Literal[
    "appgate-operator", "appgate-reverse-operator", "git-operator"
]


def get_operator_mode(reverse_mode: bool) -> OperatorMode:
    if reverse_mode:
        return "appgate-reverse-operator"
    else:
        return "appgate-operator"
