import sys
import asyncio
from asyncio import Queue

from appgate.logger import log, set_level
from appgate.appgate import policies_loop, entitlements_loop, conditions_loop, \
    init_kubernetes, main_loop
from appgate.types import AppgateEvent


def main() -> None:
    set_level(log_level='info')
    ctx = init_kubernetes(sys.argv)
    events_queue: Queue[AppgateEvent] = asyncio.Queue()
    ioloop = asyncio.get_event_loop()
    ioloop.create_task(policies_loop(ctx=ctx, queue=events_queue))
    ioloop.create_task(entitlements_loop(ctx=ctx, queue=events_queue))
    ioloop.create_task(conditions_loop(ctx=ctx, queue=events_queue))
    ioloop.create_task(main_loop(queue=events_queue, ctx=ctx))
    ioloop.run_forever()


if __name__ == "__main__":
    main()
