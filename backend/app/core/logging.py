import logging
import re

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, unbind_contextvars

SECRET = re.compile(r"(api[_-]?key|password|token|authorization|database_url)", re.I)


def _redact(_, __, event_dict):
    for key in list(event_dict):
        if SECRET.search(key):
            event_dict[key] = "********"
    return event_dict


def configure_logging(level="INFO", fmt="console"):
    renderer = (
        structlog.processors.JSONRenderer() if fmt == "json" else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    logging.basicConfig(level=getattr(logging, level.upper()), format="%(message)s", force=True)


def bind_context(**values):
    bind_contextvars(**{k: v for k, v in values.items() if v is not None})


def unbind_context(*keys):
    unbind_contextvars(*keys)


def clear_context():
    clear_contextvars()
