import asyncio
import sys
from argparse import ArgumentParser
from asyncio import Queue
from pathlib import Path
from typing import Optional, Dict, List
import datetime
import time

from appgate.logger import set_level
from appgate.appgate import init_kubernetes, main_loop, get_context, get_current_appgate_state, \
    Context, start_event_loop, log
from appgate.openapi.openapi import generate_api_spec, entity_names, generate_crd
from appgate.state import entities_conflict_summary, resolve_appgate_state
from appgate.types import AppgateEvent


async def run_k8s(namespace: Optional[str], spec_directory: Optional[str] = None) -> None:
    ctx = init_kubernetes(namespace, spec_directory=spec_directory)
    events_queue: Queue[AppgateEvent] = asyncio.Queue()
    tasks = [
                start_event_loop(
                    namespace=ctx.namespace,
                    queue=events_queue,
                    crd=entity_names(e.cls, {})[2],
                    entity_type=e.cls)
                for e in ctx.api_spec.entities.values()
                if e.api_path
            ] + [
                main_loop(queue=events_queue, ctx=ctx)
            ]

    await asyncio.gather(*tasks)


def main_run(namespace: Optional[str], spec_directory: Optional[str] = None) -> None:
    asyncio.run(run_k8s(namespace, spec_directory))


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


def main_dump_entities(stdout: bool, output_dir: Optional[str],
                       spec_directory: Optional[str] = None,
                       target_tags: Optional[List[str]] = None) -> None:
    asyncio.run(dump_entities(ctx=get_context('cli', spec_directory, None, target_tags=target_tags),
                              stdout=stdout,
                              output_dir=Path(output_dir) if output_dir else None))


def main_api_info(spec_directory: Optional[str] = None) -> None:
    api_spec = generate_api_spec(
        spec_directory=Path(spec_directory) if spec_directory else None)
    print(f'API Version: {api_spec.api_version}')
    print('Entities supported:')
    for name, entity  in api_spec.api_entities.items():
        print(f'   - {entity.api_path} :: {name}')


def main_dump_crd(stdout: bool, output_file: Optional[str],
                  spec_directory: Optional[str] = None) -> None:
    # We need the context here or just parse it
    entities = generate_api_spec(
        spec_directory=Path(spec_directory) if spec_directory else None).entities
    if not stdout:
        output_file_format = f'{str(datetime.date.today())}_{time.strftime("%H-%M")}-crd.yml'
        f = (Path(output_file) if output_file else Path(output_file_format)).open('w')
    else:
        f = sys.stdout
    short_names: Dict[str, str] = {}
    for i, e in enumerate([e.cls for e in entities.values()
                           if e.api_path is not None]):
        if i > 0:
            f.write('---\n')
        f.write(generate_crd(e, short_names))


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
    # dump entities
    dump_entities = subparsers.add_parser('dump-entities')
    dump_entities.set_defaults(cmd='dump-entities')
    dump_entities.add_argument('--stdout', action='store_true', default=False,
                               help='Dump entities into stdout')
    dump_entities.add_argument('--directory', help='Directory where to dump entities. '
                               'Default value: "YYYY-MM-DD_HH-MM-entities"',
                               default=None)
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
    # api info
    api_info = subparsers.add_parser('api-info')
    api_info.set_defaults(cmd='api-info')

    args = parser.parse_args()
    set_level(log_level=args.log_level.lower())

    if args.cmd == 'run':
        main_run(args.namespace, args.spec_directory)
    elif args.cmd == 'dump-entities':
        main_dump_entities(stdout=args.stdout, output_dir=args.directory,
                           spec_directory=args.spec_directory, target_tags=args.tags)
    elif args.cmd == 'dump-crd':
        main_dump_crd(stdout=args.stdout, output_file=args.file,
                      spec_directory=args.spec_directory)
    elif args.cmd == 'api-info':
        main_api_info(spec_directory=args.spec_directory)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
