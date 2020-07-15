import logging


log = logging.getLogger('appgate-operator')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log_levels = {
    'critical': logging.CRITICAL,
    'error': logging.ERROR,
    'warning': logging.WARNING,
    'info': logging.INFO,
    'debug': logging.DEBUG
}


def set_level(log_level: str = 'debug', logger=log) -> None:
    if log_level in log_levels:
        level = log_levels[log_level]
        if level != logger.getEffectiveLevel():
            logger.setLevel(level)
            log.info('[logger] Set log level to %s', log_level)
    else:
        log.error('[logger] Invalid log level %s', log_level)
