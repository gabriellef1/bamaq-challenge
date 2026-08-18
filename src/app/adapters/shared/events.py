"""Contrato de fio (wire format) dos eventos Kafka.

Vive em `adapters/shared` porque é usado pelos DOIS lados da mensageria:
o producer (outbound) serializa, o consumer (inbound) desserializa. É um
contrato de INFRAESTRUTURA — o domínio não sabe que ele existe.

DECISÃO — evento "magro" (notification pattern): o evento carrega apenas o
`request_id`, não os dados da solicitação. O consumer relê o estado atual no
MySQL antes de processar. Por quê:

1. O MySQL continua sendo a ÚNICA fonte de verdade — um evento atrasado ou
   reordenado nunca carrega dados velhos, porque não carrega dados.
2. A checagem de idempotência exige ler o banco de qualquer forma; o dado
   "de carona" no evento seria redundante.

Trade-off: +1 SELECT por mensagem. O evento "gordo" (carregar value/customer)
pouparia essa leitura — vale a pena quando o consumer não tem acesso ao banco
do produtor, que não é o caso aqui.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.entities import Request


class RequestCreatedEvent(BaseModel):
    """Payload publicado em `request-processing` quando uma solicitação nasce."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Versão do schema no payload: quando o formato evoluir, o consumer pode
    # aceitar v1 e v2 durante a migração em vez de quebrar na primeira mensagem.
    schema_version: Literal[1] = 1
    event_type: Literal["request.created"] = "request.created"
    request_id: UUID
    occurred_at: datetime

    @classmethod
    def from_domain(cls, request: Request) -> RequestCreatedEvent:
        return cls(request_id=request.id, occurred_at=request.created_at)

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> RequestCreatedEvent:
        """Levanta `pydantic.ValidationError` para payload malformado — o
        consumer trata como erro NÃO-retryável (direto para a DLQ: uma mensagem
        corrompida não fica boa na segunda tentativa)."""
        return cls.model_validate_json(raw)
