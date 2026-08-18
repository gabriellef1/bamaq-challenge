"""Tradução entidade de domínio <-> modelo ORM.

Concentrar a conversão aqui significa que decisões chatas (UUID vira str? fuso
vira o quê?) existem em UM lugar, testável isoladamente.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.adapters.outbound.persistence.models import RequestModel
from app.domain.entities import Request
from app.domain.value_objects import RequestStatus


def _to_naive_utc(moment: datetime) -> datetime:
    """Domínio manda aware-UTC; o MySQL DATETIME não guarda fuso, então
    persistimos naive-UTC por convenção."""
    return moment.astimezone(UTC).replace(tzinfo=None)


def _to_aware_utc(moment: datetime) -> datetime:
    """Na volta do banco, devolvemos o fuso que a convenção garante."""
    return moment.replace(tzinfo=UTC)


def to_model(request: Request) -> RequestModel:
    return RequestModel(
        id=str(request.id),
        customer_id=request.customer_id,
        value=request.value,
        status=request.status.value,
        created_at=_to_naive_utc(request.created_at),
        updated_at=_to_naive_utc(request.updated_at),
    )


def to_domain(model: RequestModel) -> Request:
    """Reconstrói a entidade — que revalida as invariantes no __post_init__.
    Se alguém corromper uma linha por fora, o erro estoura AQUI, na leitura,
    e não silenciosamente em alguma regra de negócio adiante."""
    return Request(
        id=UUID(model.id),
        customer_id=model.customer_id,
        value=model.value,
        status=RequestStatus(model.status),
        created_at=_to_aware_utc(model.created_at),
        updated_at=_to_aware_utc(model.updated_at),
    )
