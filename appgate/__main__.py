import asyncio
from argparse import ArgumentParser
from asyncio import Queue
from typing import Optional


from appgate.openapi import generate_crd
from appgate.logger import set_level
from appgate.appgate import policies_loop, entitlements_loop, conditions_loop, \
    init_kubernetes, main_loop, get_context, get_current_appgate_state, Context, log
from appgate.types import AppgateEvent, Entitlement, Condition, IdentityProvider, Policy


def main_k8s(namespace: Optional[str]) -> None:
    set_level(log_level='info')
    ctx = init_kubernetes(namespace)
    events_queue: Queue[AppgateEvent] = asyncio.Queue()
    ioloop = asyncio.get_event_loop()
    ioloop.create_task(policies_loop(ctx=ctx, queue=events_queue))
    ioloop.create_task(entitlements_loop(ctx=ctx, queue=events_queue))
    ioloop.create_task(conditions_loop(ctx=ctx, queue=events_queue))
    ioloop.create_task(main_loop(queue=events_queue, ctx=ctx))
    ioloop.run_forever()


async def dump_entities(ctx: Context) -> None:
    current_appgate_state = await get_current_appgate_state(ctx)
    current_appgate_state.dump()


def main_dump_entities() -> None:
    ioloop = asyncio.get_event_loop()
    ioloop.run_until_complete(dump_entities(ctx=get_context('none')))


def main_dump_crd() -> None:
    for e in [Condition, Entitlement, IdentityProvider, Policy]:
        print(generate_crd(e))
        print('---')


def main() -> None:
    set_level(log_level='info')
    parser = ArgumentParser('appgate-operator')
    parser.add_argument('-l', '--log-level', choices=['DEBUG', 'INFO'],
                        default='DEBUG')
    subparsers = parser.add_subparsers(dest='cmd')
    # run
    run = subparsers.add_parser('run')
    run.set_defaults(cmd='run')
    run.add_argument('--namespace', help='Specify namespace', default=None)
    # dump entities
    dump_entities = subparsers.add_parser('dump-entities')
    dump_entities.set_defaults(cmd='dump-entities')
    # dump crd
    # dump entities
    dump_crd = subparsers.add_parser('dump-crd')
    dump_crd.set_defaults(cmd='dump-crd')
    args = parser.parse_args()
    set_level(log_level=args.log_level.lower())

    if args.cmd == 'run':
        main_k8s(args.namespace)
    elif args.cmd == 'dump-entities':
        main_dump_entities()
    elif args.cmd == 'dump-crd':
        main_dump_crd()


if __name__ == "__main__":
    set_level(log_level='debug')
    main()
