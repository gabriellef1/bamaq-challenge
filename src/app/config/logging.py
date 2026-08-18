"""Logging estruturado com structlog.

Política de dados sensíveis: logamos IDENTIFICADORES (request_id, status,
outcome), nunca CONTEÚDO de negócio (value, customer_id). Se um log vazar para
um sistema de terceiros, ele não carrega dado de cliente. O processor
`_drop_sensitive_keys` é a rede de segurança caso alguém esqueça a política.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

#: Chaves que NUNCA podem sair em log, mesmo se alguém as passar por engano.
SENSITIVE_KEYS = frozenset({"value", "customer_id", "password", "secret", "authorization"})


def _drop_sensitive_keys(
    _logger: object, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    for key in SENSITIVE_KEYS & event_dict.keys():
        event_dict[key] = "[REDACTED]"
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configura logs em JSON no stdout (padrão de container: quem roteia é a
    plataforma, não a aplicação)."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _drop_sensitive_keys,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
