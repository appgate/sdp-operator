import asyncio
import binascii
import itertools
import sys
import os
from argparse import ArgumentParser
from asyncio import Queue
from pathlib import Path
from typing import Optional, Dict, List, Callable, FrozenSet, Iterable
import datetime
import time
import tempfile
import base64


import yaml
from kubernetes.config import (
    load_kube_config,
    list_kube_config_contexts,
    load_incluster_config,
)

from appgate.client import K8SConfigMapClient, AppgateClient
from appgate.logger import set_level, is_debug
from appgate.appgate import main_loop, get_current_appgate_state, start_entity_loop, log
from appgate.openapi.openapi import entity_names, generate_crd, SPEC_DIR
from appgate.openapi.utils import join
from appgate.state import entities_conflict_summary, resolve_appgate_state, AppgateState
from appgate.types import AppgateEvent, OperatorArguments, Context, BUILTIN_TAGS
from appgate.attrs import K8S_LOADER
from appgate.openapi.openapi import generate_api_spec
from appgate.openapi.types import AppgateException
from appgate.secrets import k8s_get_secret


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


def save_cert(cert: str) -> Path:
    cert_path = Path(tempfile.mktemp())
    with cert_path.open("w") as f:
        if cert.startswith("-----BEGIN CERTIFICATE-----"):
            f.write(cert)
        else:
            bytes_decoded: bytes = base64.b64decode(cert)
            f.write(bytes_decoded.decode())
    return cert_path


def get_tags(args: OperatorArguments) -> Iterable[Optional[FrozenSet[str]]]:
    tags: List[Optional[FrozenSet[str]]] = []
    for i, (tags_arg, tags_env) in enumerate(
        [
            (args.target_tags, APPGATE_TARGET_TAGS_ENV),
            (args.exclude_tags, APPGATE_EXCLUDE_TAGS_ENV),
            (args.builtin_tags, APPGATE_BUILTIN_TAGS_ENV),
        ]
    ):
        xs = frozenset(tags_arg) if tags_arg else frozenset()
        ys = filter(None, os.getenv(tags_env, "").split(","))
        ts = None
        if xs or ys:
            ts = xs.union(ys)
        tags.append(ts)
    return tags


def get_context(
    args: OperatorArguments, k8s_get_secret: Optional[Callable[[str, str], str]] = None
) -> Context:
    namespace = args.namespace or os.getenv(NAMESPACE_ENV)
    if not namespace:
        raise AppgateException(
            "Namespace must be defined in order to run the appgate-operator"
        )
    user = os.getenv(USER_ENV) or args.user
    password = os.getenv(PASSWORD_ENV) or args.password
    provider = os.getenv(PROVIDER_ENV) or args.provider
    device_id = os.getenv(DEVICE_ID_ENV) or args.device_id
    controller = os.getenv(HOST_ENV) or args.host
    timeout = os.getenv(TIMEOUT_ENV) or args.timeout

    def to_bool(value: Optional[str]) -> bool:
        if value:
            # Helm JSON schema validation ensures that the input is true/false string
            bool_map = {"true": True, "false": False}
            return bool_map[value.lower()]
        return False

    two_way_sync = args.no_two_way_sync or (to_bool(os.getenv(TWO_WAY_SYNC_ENV)))
    dry_run_mode = args.no_dry_run or (to_bool(os.getenv(DRY_RUN_ENV)))
    cleanup_mode = args.no_cleanup or (to_bool(os.getenv(CLEANUP_ENV)))
    no_verify = args.no_verify or (to_bool(os.getenv(APPGATE_SSL_NO_VERIFY)))

    spec_directory = os.getenv(SPEC_DIR_ENV) or args.spec_directory or SPEC_DIR
    appgate_cacert = os.getenv(APPGATE_SSL_CACERT)
    appgate_cacert_path = None
    verify = not no_verify
    if verify and appgate_cacert:
        try:
            appgate_cacert_path = save_cert(appgate_cacert)
        except (binascii.Error, binascii.Incomplete) as e:
            raise AppgateException(
                f"[get-context] Unable to decode the cerificate provided: {e}"
            )
        log.debug(f"[get_context] Saving certificate in {appgate_cacert_path}")
    elif verify and args.cafile:
        appgate_cacert_path = args.cafile
    secrets_key = os.getenv(APPGATE_SECRETS_KEY)
    target_tags, exclude_tags, builtin_tags = get_tags(args)
    metadata_configmap = (
        args.metadata_configmap
        or os.getenv(APPGATE_MT_CONFIGMAP_ENV)
        or f"{namespace}-configmap"
    )

    if not user or not password or not controller:
        missing_envs = ",".join(
            [
                x[0]
                for x in [
                    (USER_ENV, user),
                    (PASSWORD_ENV, password),
                    (HOST_ENV, controller),
                ]
                if x[1] is None
            ]
        )
        raise AppgateException(
            f"Unable to create appgate-controller context, missing: {missing_envs}"
        )
    api_spec = generate_api_spec(
        spec_directory=Path(spec_directory) if spec_directory else None,
        secrets_key=secrets_key,
        k8s_get_secret=k8s_get_secret,
    )

    return Context(
        namespace=namespace,
        user=user,
        password=password,
        provider=provider,
        device_id=device_id,
        controller=controller,
        timeout=int(timeout),
        dry_run_mode=dry_run_mode,
        cleanup_mode=cleanup_mode,
        two_way_sync=two_way_sync,
        api_spec=api_spec,
        no_verify=no_verify,
        target_tags=target_tags if target_tags else None,
        builtin_tags=builtin_tags if builtin_tags else BUILTIN_TAGS,
        exclude_tags=exclude_tags if exclude_tags else None,
        metadata_configmap=metadata_configmap,
        cafile=appgate_cacert_path,
    )


def init_kubernetes(args: OperatorArguments) -> Context:
    if "KUBERNETES_PORT" in os.environ:
        load_incluster_config()
        # TODO: Discover it somehow
        # https://github.com/kubernetes-client/python/issues/363
        namespace = args.namespace or os.getenv(NAMESPACE_ENV)
    else:
        load_kube_config()
        namespace = (
            args.namespace
            or os.getenv(NAMESPACE_ENV)
            or list_kube_config_contexts()[1]["context"].get("namespace")
        )

    if not namespace:
        raise AppgateException("Unable to discover namespace, please provide it.")
    ns: str = namespace  # lambda thinks it's an Optional
    return get_context(
        args=args,
        k8s_get_secret=lambda secret, key: k8s_get_secret(
            namespace=ns, key=key, secret=secret
        ),
    )


async def run_k8s(args: OperatorArguments) -> None:
    ctx = init_kubernetes(args)
    events_queue: Queue[AppgateEvent] = asyncio.Queue()
    k8s_configmap_client = K8SConfigMapClient(
        namespace=ctx.namespace, name=ctx.metadata_configmap
    )
    await k8s_configmap_client.init()

    if ctx.device_id is None:
        ctx.device_id = await k8s_configmap_client.ensure_device_id()
        log.info(
            "[appgate-operator/%s] Read device id from config map: %s",
            ctx.namespace,
            ctx.device_id,
        )

    tasks = [
        start_entity_loop(
            ctx=ctx,
            queue=events_queue,
            crd=entity_names(e.cls, {})[2],
            singleton=e.singleton,
            entity_type=e.cls,
            k8s_configmap_client=k8s_configmap_client,
        )
        for e in ctx.api_spec.entities.values()
        if e.api_path
    ] + [
        main_loop(
            queue=events_queue, ctx=ctx, k8s_configmap_client=k8s_configmap_client
        )
    ]

    await asyncio.gather(*tasks)


def main_run(args: OperatorArguments) -> None:
    try:
        asyncio.run(run_k8s(args))
    except AppgateException as e:
        log.error("[appgate-operator] Fatal error: %s", e)


async def dump_entities(
    ctx: Context, output_dir: Optional[Path], stdout: bool = False
) -> None:
    if ctx.device_id is None:
        raise AppgateException("No device id specified")

    async with AppgateClient(
        controller=ctx.controller,
        user=ctx.user,
        password=ctx.password,
        provider=ctx.provider,
        device_id=ctx.device_id,
        version=ctx.api_spec.api_version,
        no_verify=ctx.no_verify,
        cafile=ctx.cafile,
        expiration_time_delta=ctx.timeout,
        dry_run=ctx.dry_run_mode,
    ) as appgate_client:
        current_appgate_state = await get_current_appgate_state(ctx, appgate_client)
        expected_appgate_state = AppgateState(
            {
                k: v.entities_with_tags(
                    ctx.builtin_tags.union(ctx.exclude_tags or frozenset())
                )
                for k, v in current_appgate_state.entities_set.items()
            }
        )
        if is_debug():
            for entity_name, entity_set in current_appgate_state.entities_set.items():
                for e in entity_set.entities:
                    log.debug(f"Got entitiy %s: %s [%s]", e.name, e.id, entity_name)
        total_conflicts = resolve_appgate_state(
            expected_state=expected_appgate_state,
            total_appgate_state=current_appgate_state,
            reverse=True,
            api_spec=ctx.api_spec,
        )
        if total_conflicts:
            log.error("[dump-entities] Found errors when getting current state")
            entities_conflict_summary(
                conflicts=total_conflicts, namespace=ctx.namespace
            )
        else:
            current_appgate_state.dump(
                api_version=f"v{ctx.api_spec.api_version}",
                output_dir=output_dir,
                stdout=stdout,
                target_tags=ctx.target_tags,
                exclude_tags=ctx.exclude_tags,
            )


def main_dump_entities(
    args: OperatorArguments,
    stdout: bool = False,
    output_dir: Optional[Path] = None,
) -> None:
    asyncio.run(
        dump_entities(
            ctx=get_context(args),
            output_dir=output_dir,
            stdout=stdout,
        )
    )


def main_api_info(spec_directory: Optional[str] = None) -> None:
    api_spec = generate_api_spec(
        spec_directory=Path(spec_directory) if spec_directory else None
    )
    print(f"API Version: {api_spec.api_version}")
    print("Entities supported:")
    for name, entity in api_spec.api_entities.items():
        deps = entity.dependencies
        print(f'   - {entity.api_path} :: {name} :: {{{join(" | ", deps)}}}')
    print("Entities topological sort:")
    print(f'    - {", ".join(api_spec.entities_sorted)}')


def main_dump_crd(
    stdout: bool,
    output_file: Optional[str],
    spec_directory: Optional[str] = None,
) -> None:
    # We need the context here or just parse it
    api_spec = generate_api_spec(
        spec_directory=Path(spec_directory) if spec_directory else None
    )
    output_path = None
    if not stdout:
        output_file_format = (
            f'{str(datetime.date.today())}_{time.strftime("%H-%M")}-crd.yml'
        )
        output_path = Path(output_file) if output_file else Path(output_file_format)
        f = output_path.open("w")
    else:
        f = sys.stdout
    short_names: Dict[str, str] = {}
    for i, e in enumerate(
        [e.cls for e in api_spec.entities.values() if e.api_path is not None]
    ):
        if i > 0:
            f.write("---\n")
        f.write(generate_crd(e, short_names, f"v{api_spec.api_version}"))
    if output_path:
        log.info("[dump-crd] File %s generated with CRD definitions", output_path)


def main_validate_entities(
    files: List[str], spec_directory: Optional[str] = None
) -> int:

    api_spec = generate_api_spec(
        spec_directory=Path(spec_directory) if spec_directory else None
    )
    candidates = [Path(f) for f in files]
    errors = 0
    while candidates:
        file = candidates.pop()
        if not file.exists():
            errors = errors + 1
            print(f" - {file}: ERROR: file does not exist.")
            continue
        if file.is_dir():
            candidates.extend(itertools.chain(file.glob("*.yaml"), file.glob("*.yml")))
            continue
        with file.open() as f:
            try:
                data = yaml.safe_load_all(f.read())
                for d in data:
                    try:
                        kind = d.get("kind")
                        name = d["metadata"]["name"]
                        api_spec.validate(d, kind, K8S_LOADER)
                        print(f" - {kind}::{name}: OK.")
                    except AppgateException as e:
                        errors = errors + 1
                        print(f" - {kind}::{name}: ERROR: loading entity: {e}.")
            except yaml.YAMLError as e:
                errors = errors + 1
                print(f" - {file}: ERROR: parsing entity: {e}.")
    return errors


def main() -> None:
    set_level(log_level="info")
    parser = ArgumentParser("appgate-operator")
    parser.add_argument("-l", "--log-level", choices=["DEBUG", "INFO"], default="INFO")
    parser.add_argument(
        "--spec-directory",
        default=None,
        help="Specifies the directory where the openapi yml specification is lcoated.",
    )
    subparsers = parser.add_subparsers(dest="cmd")
    # run
    run = subparsers.add_parser("run")
    run.set_defaults(cmd="run")
    run.add_argument("--namespace", help="Specify namespace", default=None)
    run.add_argument(
        "--no-dry-run",
        help="Disabel run in dry-run mode",
        default=False,
        action="store_true",
    )
    run.add_argument("--host", help="Controller host to connect", default=None)
    run.add_argument("--user", help="Username used for authentication", default=None)
    run.add_argument(
        "--password", help="Password used for authentication", default=None
    )
    run.add_argument(
        "--no-cleanup",
        help="Disable delete entities not defined in expected state",
        default=False,
        action="store_true",
    )
    run.add_argument(
        "--mt-config-map", help="Name for the configmap used for metadata", default=None
    )
    run.add_argument(
        "--no-two-way-sync",
        help="Disabel always update current state with latest appgate"
        " state before applying a plan",
        default=False,
        action="store_true",
    )
    run.add_argument(
        "-t",
        "--tags",
        action="append",
        help="Tags to filter entities. Only entities with any of those tags will be dumped",
        default=[],
    )
    run.add_argument(
        "--timeout",
        help="Event loop timeout to determine when there are not more events",
        default=30,
    )
    run.add_argument(
        "--no-verify",
        action="store_true",
        default=False,
        help="Disable SSL strict verification.",
    )
    run.add_argument(
        "--cafile", help="cacert file used for ssl verification.", default=None
    )

    # dump entities
    dump_entities = subparsers.add_parser("dump-entities")
    dump_entities.set_defaults(cmd="dump-entities")
    dump_entities.add_argument(
        "--stdout", action="store_true", default=False, help="Dump entities into stdout"
    )
    dump_entities.add_argument(
        "--no-verify",
        action="store_true",
        default=False,
        help="Disable SSL strict verification.",
    )
    dump_entities.add_argument(
        "--directory",
        help="Directory where to dump entities. "
        'Default value: "YYYY-MM-DD_HH-MM-entities"',
        default=None,
    )
    dump_entities.add_argument(
        "--cafile", help="cacert file used for ssl verification.", default=None
    )
    dump_entities.add_argument(
        "-t",
        "--tags",
        action="append",
        help="Tags to filter entities. Only entities with any of those tags will be dumped",
        default=[],
    )
    # dump crd
    dump_crd = subparsers.add_parser("dump-crd")
    dump_crd.set_defaults(cmd="dump-crd")
    dump_crd.add_argument(
        "--stdout", action="store_true", default=False, help="Dump entities into stdout"
    )
    dump_crd.add_argument(
        "--file",
        help="File where to dump CRD definitions. "
        'Default value: "YYYY-MM-DD_HH-MM-crd.yaml"',
        default=None,
    )
    # validate entities
    validate_entities = subparsers.add_parser("validate-entities")
    validate_entities.set_defaults(cmd="validate-entities")
    validate_entities.add_argument(
        "files",
        type=str,
        metavar="file",
        nargs="+",
        help="Directory from where to get the entities to validate",
    )
    # api info
    api_info = subparsers.add_parser("api-info")
    api_info.set_defaults(cmd="api-info")

    args = parser.parse_args()
    set_level(log_level=os.getenv(APPGATE_LOG_LEVEL) or args.log_level.lower())
    try:
        if args.cmd == "run":
            if args.cafile and not Path(args.cafile).exists():
                print(f"cafile file not found: {args.cafile}")
                sys.exit(1)
            main_run(
                OperatorArguments(
                    namespace=args.namespace,
                    spec_directory=args.spec_directory,
                    no_dry_run=args.no_dry_run,
                    user=args.user,
                    password=args.password,
                    host=args.host,
                    no_two_way_sync=args.no_two_way_sync,
                    target_tags=args.tags,
                    no_cleanup=args.no_cleanup,
                    timeout=args.timeout,
                    metadata_configmap=args.mt_config_map,
                    no_verify=args.no_verify,
                    cafile=Path(args.cafile) if args.cafile else None,
                )
            )
        elif args.cmd == "dump-entities":
            if args.cafile and not Path(args.cafile).exists():
                print(f"cafile file not found: {args.cafile}")
                sys.exit(1)

            main_dump_entities(
                OperatorArguments(
                    namespace="cli",
                    spec_directory=args.spec_directory,
                    target_tags=args.tags,
                    no_verify=args.no_verify,
                    cafile=Path(args.cafile) if args.cafile else None,
                ),
                stdout=args.stdout,
                output_dir=Path(args.directory) if args.directory else None,
            )
        elif args.cmd == "dump-crd":
            main_dump_crd(
                stdout=args.stdout,
                output_file=args.file,
                spec_directory=args.spec_directory,
            )
        elif args.cmd == "api-info":
            main_api_info(spec_directory=args.spec_directory)
        elif args.cmd == "validate-entities":
            res = main_validate_entities(
                spec_directory=args.spec_directory, files=args.files
            )
            sys.exit(res)
        else:
            parser.print_help()
    except AppgateException as e:
        log.error("[%s] %s", args.cmd, e.message or "Unable to perform operation")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(1)
