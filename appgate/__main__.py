import sys
import asyncio

from appgate.logger import log, set_level
from appgate.appgate import policies_loop, entitlements_loop, conditions_loop, \
    init_kubernetes, init_environment, main_loop


def main() -> None:
    set_level(log_level='info')
    ns = init_kubernetes()
    if not ns and len(sys.argv) == 1:
        log.error('Unable to discover namespace, please provide it.')
        sys.exit(1)
    ns = ns or sys.argv[1]
    events_queue = asyncio.Queue()
    ioloop = asyncio.get_event_loop()
    ioloop.create_task(policies_loop(ns, queue=events_queue))
    ioloop.create_task(entitlements_loop(ns, queue=events_queue))
    ioloop.create_task(conditions_loop(ns, queue=events_queue))
    ioloop.create_task(main_loop(queue=events_queue,
                                 controller='controller',
                                 user='admin',
                                 password='admin',
                                 namespace=ns))
    ioloop.run_forever()


if __name__ == "__main__":
    main()
