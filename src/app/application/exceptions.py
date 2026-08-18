"""Erros da camada de aplicação.

Diferença de papel: `app.domain.exceptions` são violações de REGRA DE NEGÓCIO;
estes aqui são falhas de ORQUESTRAÇÃO (uma dependência externa não cumpriu o
contrato). Os adapters de saída levantam estes erros; os de entrada traduzem.
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Raiz dos erros de aplicação."""


class EventPublishError(ApplicationError):
    """O broker não confirmou a publicação do evento.

    A API traduz isto em 503: a solicitação FICOU persistida como PENDING, mas
    o processamento não foi disparado. Trade-off documentado no README — a
    alternativa robusta é o padrão Transactional Outbox.
    """
