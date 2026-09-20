import logging
import structlog
import sys

def setup_logging(json_format: bool = True, log_level: str = "INFO"):
    """
    Configure enterprise structured logging.
    If json_format is True, outputs JSON. Otherwise, outputs human-readable console logs.
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Masking sensitive data
    def redact_secrets(logger, log_method, event_dict):
        sensitive_keys = {"api_key", "api_secret", "password", "token", "authorization"}
        for k, v in list(event_dict.items()):
            if any(secret in k.lower() for secret in sensitive_keys):
                event_dict[k] = "***REDACTED***"
        return event_dict

    processors.append(redact_secrets)

    if json_format:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
