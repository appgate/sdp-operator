import sys
import asyncio
from asyncio import Queue

from appgate.logger import log, set_level
from appgate.appgate import policies_loop, entitlements_loop, conditions_loop, \
    init_kubernetes, main_loop
from appgate.types import AppgateEvent


def main() -> None:
    set_level(log_level='info')
    ctx = init_kubernetes()
    if not ctx.namespace and len(sys.argv) == 1:
        log.error('Unable to discover namespace, please provide it.')
        sys.exit(1)
    ns = ctx.namespace or sys.argv[1]
    events_queue: Queue[AppgateEvent] = asyncio.Queue()
    ioloop = asyncio.get_event_loop()
    ioloop.create_task(policies_loop(ns, queue=events_queue))
    ioloop.create_task(entitlements_loop(ns, queue=events_queue))
    ioloop.create_task(conditions_loop(ns, queue=events_queue))
    ioloop.create_task(main_loop(queue=events_queue,
                                 controller=ctx.controller,
                                 user=ctx.user,
                                 password=ctx.password,
                                 namespace=ns))
    ioloop.run_forever()


if __name__ == "__main__":
    main()
