import asyncio
from argparse import ArgumentParser
from asyncio import Queue
from pathlib import Path
from typing import Optional

from appgate.openapi import generate_crd, entity_names
from appgate.logger import set_level
from appgate.appgate import init_kubernetes, main_loop, get_context, get_current_appgate_state, \
    Context, entity_loop, log
from appgate.state import entities_conflict_summary, resolve_appgate_state
from appgate.types import AppgateEvent, generate_entities, entities_sorted


def main_k8s(namespace: Optional[str]) -> None:
    ctx = init_kubernetes(namespace)
    events_queue: Queue[AppgateEvent] = asyncio.Queue()
    ioloop = asyncio.get_event_loop()
    entities = generate_entities()
    for e in [e for e in entities.values() if e[2] is not None]:
        _, _, plural_name = entity_names(e[0])
        ioloop.create_task(entity_loop(ctx=ctx, queue=events_queue, crd_path=plural_name,
                                       entity_type=e[0]))
    ioloop.create_task(main_loop(queue=events_queue, ctx=ctx))
    ioloop.run_forever()


async def dump_entities(ctx: Context, output_dir: Optional[Path],
                        stdout: bool = False) -> None:
    current_appgate_state = await get_current_appgate_state(ctx)
    total_conflicts = resolve_appgate_state(appgate_state=current_appgate_state,
                                            reverse=True)
    if total_conflicts:
        log.error('[dump-entities] Found errors when getting current state')
        entities_conflict_summary(conflicts=total_conflicts,
                                  namespace=ctx.namespace)
    else:
        current_appgate_state.dump(output_dir=output_dir, stdout=stdout)


def main_dump_entities(stdout: bool, output_dir: Optional[Path]) -> None:
    ioloop = asyncio.get_event_loop()
    ioloop.run_until_complete(dump_entities(ctx=get_context('cli'),
                                            stdout=stdout,
                                            output_dir=Path(output_dir) if output_dir else None))


def main_dump_crd() -> None:
    entities = generate_entities()
    c = 0
    for e in [e[0] for e in entities.values()
              if e[3] == 0 and e[2] is not None]:
        if c > 0:
            print('---')
        print(generate_crd(e))
        c += 1


def main() -> None:
    set_level(log_level='info')
    parser = ArgumentParser('appgate-operator')
    parser.add_argument('-l', '--log-level', choices=['DEBUG', 'INFO'],
                        default='INFO')
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
                               'Default value: ',
                               default=None)
    # dump crd
    # dump entities
    dump_crd = subparsers.add_parser('dump-crd')
    dump_crd.set_defaults(cmd='dump-crd')
    args = parser.parse_args()
    set_level(log_level=args.log_level.lower())

    if args.cmd == 'run':
        main_k8s(args.namespace)
    elif args.cmd == 'dump-entities':
        main_dump_entities(stdout=args.stdout, output_dir=args.directory)
    elif args.cmd == 'dump-crd':
        main_dump_crd()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
