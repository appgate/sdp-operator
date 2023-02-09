import asyncio
import os
import sys
import threading
from asyncio import Queue
from typing import Type, Any, Coroutine, Callable, Dict

from kubernetes.client import CustomObjectsApi
from kubernetes.config import (
    load_incluster_config,
    load_kube_config,
    list_kube_config_contexts,
)
from kubernetes.watch import Watch
from kubernetes.client.exceptions import ApiException

from appgate.attrs import K8S_LOADER, dump_datetime
from appgate.client import K8SConfigMapClient, entity_unique_id
from appgate.logger import log
from appgate.openapi.openapi import entity_names
from appgate.openapi.types import (
    AppgateException,
    Entity_T,
    APISpec,
    K8S_APPGATE_VERSION,
    APPGATE_METADATA_LATEST_GENERATION_FIELD,
    APPGATE_METADATA_MODIFICATION_FIELD,
    AppgateTypedloadException,
)
from appgate.types import (
    NAMESPACE_ENV,
    AppgateEvent,
    EventObject,
    K8SEvent,
    AppgateEventSuccess,
    AppgateEventError,
    crd_domain,
)


__all__ = [
    "init_kubernetes",
    "run_k8s",
    "get_crds",
    "start_entity_loop",
    "run_entity_loop",
]


crds: CustomObjectsApi | None = None


def init_kubernetes(namespace: str | None) -> str:
    if "KUBERNETES_PORT" in os.environ:
        load_incluster_config()
        # TODO: Discover it somehow
        # https://github.com/kubernetes-client/python/issues/363
        ns = namespace or os.getenv(NAMESPACE_ENV)
    else:
        load_kube_config()
        ns = (
            namespace
            or os.getenv(NAMESPACE_ENV)
            or list_kube_config_contexts()[1]["context"].get("namespace")
        )
    if not ns:
        raise AppgateException("Unable to discover namespace, please provide it.")
    return ns


async def start_entity_loop(
    namespace: str,
    crd: str,
    entity_type: Type[Entity_T],
    singleton: bool,
    queue: Queue[AppgateEvent],
    api_spec: APISpec,
    k8s_configmap_client: K8SConfigMapClient | None,
) -> None:
    log.debug(
        "[%s/%s] Starting loop event for entities on path: %s", crd, namespace, crd
    )

    def run(loop: asyncio.AbstractEventLoop) -> None:
        t = threading.Thread(
            target=run_entity_loop,
            args=(
                namespace,
                crd,
                loop,
                queue,
                K8S_LOADER.load,
                entity_type,
                singleton,
                api_spec,
                k8s_configmap_client,
            ),
            daemon=True,
        )
        t.start()

    await asyncio.to_thread(run, asyncio.get_event_loop())


def get_crds() -> CustomObjectsApi:
    global crds
    if not crds:
        crds = CustomObjectsApi()
    return crds


async def run_k8s(
    queue: Queue[AppgateEvent],
    namespace: str,
    api_spec: APISpec,
    k8s_configmap_client: K8SConfigMapClient | None,
    operator: Coroutine[Any, Any, None],
) -> None:
    tasks = [
        start_entity_loop(
            namespace=namespace,
            queue=queue,
            crd=entity_names(e.cls, {})[2],
            singleton=e.singleton,
            entity_type=e.cls,
            api_spec=api_spec,
            k8s_configmap_client=k8s_configmap_client,
        )
        for e in api_spec.entities.values()
        if e.api_path
    ] + [operator]

    await asyncio.gather(*tasks)


def run_entity_loop(
    namespace: str,
    crd: str,
    loop: asyncio.AbstractEventLoop,
    queue: Queue[AppgateEvent],
    load: Callable[[Dict[str, Any], Dict[str, Any] | None, type], Entity_T],
    entity_type: type,
    singleton: bool,
    api_spec: APISpec,
    k8s_configmap_client: K8SConfigMapClient | None,
) -> None:
    log.info(f"[{crd}/{namespace}] Loop for {crd}/{namespace} started")
    watcher = Watch().stream(
        get_crds().list_namespaced_custom_object,
        crd_domain(api_version=api_spec.api_version),
        K8S_APPGATE_VERSION,
        namespace,
        crd,
    )
    while True:
        try:
            data = next(watcher)
            data_obj = data["object"]
            data_mt = data_obj["metadata"]
            kind = data_obj["kind"]
            spec = data_obj["spec"]
            event = EventObject(metadata=data_mt, spec=spec, kind=kind)
            if singleton:
                name = "singleton"
            else:
                name = event.spec["name"]
            if event:
                assert data["type"] in ("ADDED", "DELETED", "MODIFIED")
                ev = K8SEvent(data["type"], event)
                try:
                    # names are not unique between entities, so we need to come up with a unique name now
                    mt = ev.object.metadata
                    latest_entity_generation = None
                    if k8s_configmap_client:
                        latest_entity_generation = (
                            k8s_configmap_client.read_entity_generation(
                                entity_unique_id(kind, name)
                            )
                        )
                    if latest_entity_generation:
                        mt[
                            APPGATE_METADATA_LATEST_GENERATION_FIELD
                        ] = latest_entity_generation.generation
                        mt[APPGATE_METADATA_MODIFICATION_FIELD] = dump_datetime(
                            latest_entity_generation.modified
                        )
                    entity = load(ev.object.spec, ev.object.metadata, entity_type)
                    log.debug(
                        "[%s/%s] K8SEvent type: %s: %s", crd, namespace, ev.type, entity
                    )
                    appgate_event: AppgateEvent = AppgateEventSuccess(
                        op=ev.type, entity=entity
                    )
                except AppgateTypedloadException as e:
                    log.error(
                        "[%s/%s] Unable to parse event with name %s of type %s",
                        crd,
                        namespace,
                        event.spec["name"],
                        event.kind,
                    )
                    log.error(
                        "[%s/%s]%s!!! Error message: %s",
                        crd,
                        namespace,
                        " " * 4,
                        e.message,
                    )
                    log.error(
                        "[%s/%s]%s!!! Error when loading from: %s",
                        crd,
                        namespace,
                        " " * 4,
                        e.platform_type,
                    )
                    log.error(
                        "[%s/%s]%s!!! Error when loading type: %s",
                        crd,
                        namespace,
                        " " * 4,
                        e.type_.__qualname__ if e.type_ else "Unknown",
                    )
                    log.error(
                        "[%s/%s]%s!!! Error when loading value: %s",
                        crd,
                        namespace,
                        " " * 4,
                        e.value,
                    )
                    appgate_event = AppgateEventError(
                        name=event.spec["name"], kind=event.kind, error=str(e)
                    )

                asyncio.run_coroutine_threadsafe(queue.put(appgate_event), loop)
        except ApiException:
            log.exception(
                "[appgate-operator/%s] Error when subscribing events in k8s for %s [%s]",
                namespace,
                crd,
                crd_domain(api_version=api_spec.api_version),
            )
            watcher = Watch().stream(
                get_crds().list_namespaced_custom_object,
                crd_domain(api_version=api_spec.api_version),
                K8S_APPGATE_VERSION,
                namespace,
                crd,
            )
        except StopIteration:
            log.debug(
                "[appgate-operator/%s] Event loop stopped, re-initializing watchers",
                namespace,
            )
            watcher = Watch().stream(
                get_crds().list_namespaced_custom_object,
                crd_domain(api_version=api_spec.api_version),
                K8S_APPGATE_VERSION,
                namespace,
                crd,
            )
        except Exception:
            log.exception(
                "[appgate-operator/%s] Unhandled error for %s", namespace, crd
            )
            exit(1)
