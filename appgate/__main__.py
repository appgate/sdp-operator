import sys
import asyncio
from argparse import ArgumentParser
from asyncio import Queue
from pathlib import Path
from typing import Optional

import typedload
import yaml

from appgate.logger import set_level
from appgate.appgate import policies_loop, entitlements_loop, conditions_loop, \
    init_kubernetes, main_loop, get_context, get_current_appgate_state, Context
from appgate.types import AppgateEvent


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


def main_get_entities() -> None:
    ioloop = asyncio.get_event_loop()
    ioloop.run_until_complete(dump_entities(ctx=get_context('none')))


def main() -> None:
    set_level(log_level='info')
    parser = ArgumentParser('appgate-operator')
    parser.add_argument('--namespace', help='Specify namespace', default=None)
    parser.add_argument('--get-entities', action='store_true',
                        help='Gets entities from controller')
    args = parser.parse_args()
    print(args)
    if args.get_entities:
        main_get_entities()
    else:
        main_k8s(args.namespace)


if __name__ == "__main__":
    main()
