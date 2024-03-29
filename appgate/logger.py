import logging


__all__ = ["set_level", "is_debug", "log"]


TRACE_LEVEL = logging.DEBUG - 5
log_levels = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "trace": TRACE_LEVEL,
}

logging.addLevelName(TRACE_LEVEL, "TRACE")


class Logger:
    def __init__(self, log: logging.Logger) -> None:
        self._log: logging.Logger = log
        self.info = self._log.info
        self.debug = self._log.debug
        self.warning = self._log.warning
        self.error = self._log.error
        self.exception = self._log.exception
        self.getEffectiveLevel = self._log.getEffectiveLevel
        self.setLevel = self._log.setLevel

    @property
    def level(self) -> int:
        return self._log.level

    def trace(self, message, *args, **kws) -> None:
        if self._log.isEnabledFor(TRACE_LEVEL):
            self._log._log(TRACE_LEVEL, message, args, **kws)


# Setup appgate-operator logger
_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(_formatter)
_log = logging.getLogger("appgate-operator")
_log.addHandler(_stream_handler)
log = Logger(_log)


def set_level(log_level: str = "debug", logger=log) -> None:
    if log_level in log_levels:
        level = log_levels[log_level]
        if level != logger.getEffectiveLevel():
            logger.setLevel(level)
            log.info("[logger] Set log level to %s", log_level)
    else:
        log.error("[logger] Invalid log level %s", log_level)


def is_debug() -> bool:
    return log.level <= logging.DEBUG
