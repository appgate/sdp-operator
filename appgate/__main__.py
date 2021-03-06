import asyncio
import itertools
import sys
from argparse import ArgumentParser
from asyncio import Queue
from pathlib import Path
from typing import Optional, Dict, List
import datetime
import time

import yaml

from appgate.client import K8SConfigMapClient
from appgate.openapi.types import AppgateException
from appgate.logger import set_level
from appgate.appgate import init_kubernetes, main_loop, get_context, get_current_appgate_state, \
    Context, start_entity_loop, log
from appgate.openapi.openapi import generate_api_spec, entity_names, generate_crd
from appgate.openapi.utils import join
from appgate.state import entities_conflict_summary, resolve_appgate_state
from appgate.types import AppgateEvent, OperatorArguments
from appgate.attrs import K8S_LOADER


async def run_k8s(args: OperatorArguments) -> None:
    ctx = init_kubernetes(args)
    events_queue: Queue[AppgateEvent] = asyncio.Queue()
    k8s_configmap_client = K8SConfigMapClient(namespace=ctx.namespace, name=ctx.metadata_configmap)
    await k8s_configmap_client.init()
    tasks = [
                start_entity_loop(
                    ctx=ctx,
                    queue=events_queue,
                    crd=entity_names(e.cls, {})[2],
                    singleton=e.singleton,
                    entity_type=e.cls,
                    k8s_configmap_client=k8s_configmap_client)
                for e in ctx.api_spec.entities.values()
                if e.api_path
            ] + [
                main_loop(queue=events_queue, ctx=ctx, k8s_configmap_client=k8s_configmap_client)
            ]

    await asyncio.gather(*tasks)


def main_run(args: OperatorArguments) -> None:
    asyncio.run(run_k8s(args))


async def dump_entities(ctx: Context, output_dir: Optional[Path],
                        stdout: bool = False) -> None:
    current_appgate_state = await get_current_appgate_state(ctx)
    total_conflicts = resolve_appgate_state(appgate_state=current_appgate_state,
                                            reverse=True,
                                            api_spec=ctx.api_spec)
    if total_conflicts:
        log.error('[dump-entities] Found errors when getting current state')
        entities_conflict_summary(conflicts=total_conflicts,
                                  namespace=ctx.namespace)
    else:
        current_appgate_state.dump(output_dir=output_dir, stdout=stdout)


def main_dump_entities(args: OperatorArguments,  stdout: bool = False,
                       output_dir: Optional[Path] = None) -> None:
    asyncio.run(dump_entities(ctx=get_context(args),
                              output_dir=output_dir,
                              stdout=stdout))


def main_api_info(spec_directory: Optional[str] = None) -> None:
    api_spec = generate_api_spec(
        spec_directory=Path(spec_directory) if spec_directory else None)
    print(f'API Version: {api_spec.api_version}')
    print('Entities supported:')
    for name, entity in api_spec.api_entities.items():
        deps = entity.dependencies
        print(f'   - {entity.api_path} :: {name} :: {{{join(" | ", deps)}}}')
    print('Entities topological sort:')
    print(f'    - {", ".join(api_spec.entities_sorted)}')


def main_dump_crd(stdout: bool, output_file: Optional[str],
                  spec_directory: Optional[str] = None) -> None:
    # We need the context here or just parse it
    entities = generate_api_spec(
        spec_directory=Path(spec_directory) if spec_directory else None).entities
    output_path = None
    if not stdout:
        output_file_format = f'{str(datetime.date.today())}_{time.strftime("%H-%M")}-crd.yml'
        output_path = Path(output_file) if output_file else Path(output_file_format)
        f = output_path.open('w')
    else:
        f = sys.stdout
    short_names: Dict[str, str] = {}
    for i, e in enumerate([e.cls for e in entities.values()
                           if e.api_path is not None]):
        if i > 0:
            f.write('---\n')
        f.write(generate_crd(e, short_names))
    if output_path:
        log.info('[dump-crd] File %s generated with CRD definitions', output_path)


def main_validate_entities(files: List[str],
                           spec_directory: Optional[str] = None) -> int:

    api_spec = generate_api_spec(
        spec_directory=Path(spec_directory) if spec_directory else None)
    candidates = [Path(f) for f in files]
    errors = 0
    while candidates:
        file = candidates.pop()
        if not file.exists():
            errors = errors + 1
            print(f' - {file}: ERROR: file does not exist.')
            continue
        if file.is_dir():
            candidates.extend(itertools.chain(file.glob('*.yaml'), file.glob('*.yml')))
            continue
        with file.open() as f:
            try:
                data = yaml.safe_load_all(f.read())
                for d in data:
                    try:
                        kind = d.get('kind')
                        name = d['metadata']['name']
                        api_spec.validate(d, kind, K8S_LOADER)
                        print(f' - {kind}::{name}: OK.')
                    except AppgateException as e:
                        errors = errors + 1
                        print(f' - {kind}::{name}: ERROR: loading entity: {e}.')
            except yaml.YAMLError as e:
                errors = errors + 1
                print(f' - {file}: ERROR: parsing entity: {e}.')
    return errors


def main() -> None:
    set_level(log_level='info')
    parser = ArgumentParser('appgate-operator')
    parser.add_argument('-l', '--log-level', choices=['DEBUG', 'INFO'],
                        default='INFO')
    parser.add_argument('--spec-directory', default=None,
                        help='Specifies the directory where the openapi yml specification is lcoated.')
    subparsers = parser.add_subparsers(dest='cmd')
    # run
    run = subparsers.add_parser('run')
    run.set_defaults(cmd='run')
    run.add_argument('--namespace', help='Specify namespace', default=None)
    run.add_argument('--dry-run', help='Run in dry-run mode', default=False, action='store_true')
    run.add_argument('--host', help='Controller host to connect', default=None)
    run.add_argument('--user', help='Username used for authentication', default=None)
    run.add_argument('--password', help='Password used for authentication', default=None)
    run.add_argument('--cleanup', help='Delete entities not defined in expected state', default=True)
    run.add_argument('--mt-config-map', help='Name for the configmap used for metadata',
                     default=None)
    run.add_argument('--two-way-sync', help='Always update current state with latest appgate'
                                            ' state before applying a plan', default=True)
    run.add_argument('-t', '--tags', action='append',
                     help='Tags to filter entities. Only entities with any of those tags will be dumped',
                     default=[])
    run.add_argument('--timeout', help='Event loop timeout to determine when there are not more events',
                     default=30)
    run.add_argument('--no-verify', action='store_true', default=False, help='Disable SSL strict verification.')
    run.add_argument('--cafile', help='cacert file used for ssl verification.', default=None)

    # dump entities
    dump_entities = subparsers.add_parser('dump-entities')
    dump_entities.set_defaults(cmd='dump-entities')
    dump_entities.add_argument('--stdout', action='store_true', default=False,
                               help='Dump entities into stdout')
    dump_entities.add_argument('--no-verify', action='store_true', default=False,
                               help='Disable SSL strict verification.')
    dump_entities.add_argument('--directory', help='Directory where to dump entities. '
                               'Default value: "YYYY-MM-DD_HH-MM-entities"',
                               default=None)
    dump_entities.add_argument('--cafile', help='cacert file used for ssl verification.', default=None)
    dump_entities.add_argument('-t', '--tags', action='append',
                               help='Tags to filter entities. Only entities with any of those tags will be dumped',
                               default=[])
    # dump crd
    dump_crd = subparsers.add_parser('dump-crd')
    dump_crd.set_defaults(cmd='dump-crd')
    dump_crd.add_argument('--stdout', action='store_true', default=False,
                          help='Dump entities into stdout')
    dump_crd.add_argument('--file', help='File where to dump CRD definitions. '
                                         'Default value: "YYYY-MM-DD_HH-MM-crd.yaml"',
                          default=None)
    # validate entities
    validate_entities = subparsers.add_parser('validate-entities')
    validate_entities.set_defaults(cmd='validate-entities')
    validate_entities.add_argument('files', type=str, metavar='file', nargs='+',
                                   help='Directory from where to get the entities to validate')
    # api info
    api_info = subparsers.add_parser('api-info')
    api_info.set_defaults(cmd='api-info')

    args = parser.parse_args()
    set_level(log_level=args.log_level.lower())
    try:
        if args.cmd == 'run':
            if args.cafile and not Path(args.cafile).exists():
                print(f'cafile file not found: {args.cafile}')
                sys.exit(1)
            main_run(OperatorArguments(
                namespace=args.namespace, spec_directory=args.spec_directory,
                dry_run=args.dry_run, user=args.user, password=args.password,
                host=args.host, two_way_sync=args.two_way_sync, target_tags=args.tags,
                cleanup=args.cleanup, timeout=args.timeout, metadata_configmap=args.mt_config_map,
                no_verify=args.no_verify, cafile=Path(args.cafile) if args.cafile else None))
        elif args.cmd == 'dump-entities':
            if args.cafile and not Path(args.cafile).exists():
                print(f'cafile file not found: {args.cafile}')
                sys.exit(1)

            main_dump_entities(
                OperatorArguments(namespace='cli', spec_directory=args.spec_directory,
                                  target_tags=args.tags, no_verify=args.no_verify,
                                  cafile=Path(args.cafile) if args.cafile else None),
                stdout=args.stdout,
                output_dir=Path(args.directory) if args.directory else None)
        elif args.cmd == 'dump-crd':
            main_dump_crd(stdout=args.stdout, output_file=args.file,
                          spec_directory=args.spec_directory)
        elif args.cmd == 'api-info':
            main_api_info(spec_directory=args.spec_directory)
        elif args.cmd == 'validate-entities':
            res = main_validate_entities(spec_directory=args.spec_directory,
                                         files=args.files)
            sys.exit(res)
        else:
            parser.print_help()
    except AppgateException as e:
        log.error('[%s] %s', args.cmd, e.message or 'Unable to perform operation')
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info('Interrupted by user.')
        sys.exit(1)
