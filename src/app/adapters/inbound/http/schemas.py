"""Contratos HTTP (DTOs Pydantic).

São a FRONTEIRA de validação: payload ruim morre aqui com 422 e nunca encosta
no domínio. Repare que estes modelos não são a entidade — a entidade tem
comportamento e invariantes; estes só descrevem o formato do JSON que entra e
sai. Confundir os dois acopla o contrato público ao modelo interno.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.domain.entities import MAX_CUSTOMER_ID_LENGTH, MAX_VALUE
from app.domain.value_objects import RequestStatus


class CreateRequestIn(BaseModel):
    """Body do POST /requests.

    SEGURANÇA — validação rigorosa de entrada:
    - `extra="forbid"`: campo desconhecido -> 422. Bloqueia mass assignment e
      denuncia clientes com contrato errado em vez de ignorá-los em silêncio.
    - `customer_id` com whitelist `[A-Za-z0-9_-]`: identificador é
      identificador — nada de espaços, unicode exótico ou quebras de linha
      (que permitiriam log injection). SQL injection já é impossível pelas
      queries parametrizadas; a whitelist é defesa em profundidade.
    - `value` chega como Decimal SEM passar por float: o pydantic v2 converte
      direto da string do JSON. `decimal_places=2` REJEITA 10.555 em vez de
      arredondar em silêncio — dinheiro não se arredonda sem avisar.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    customer_id: str = Field(
        min_length=1,
        max_length=MAX_CUSTOMER_ID_LENGTH,
        pattern=r"^[A-Za-z0-9_-]+$",
        examples=["123"],
    )
    value: Decimal = Field(
        gt=0,
        le=MAX_VALUE,
        max_digits=15,
        decimal_places=2,
        examples=[1500.00],
    )


class RequestOut(BaseModel):
    """Resposta do POST (201) e do GET (200) — o contrato do enunciado."""

    id: str
    customer_id: str
    value: Decimal
    status: RequestStatus

    @field_serializer("value")
    def _serialize_value(self, value: Decimal) -> float:
        """O pydantic serializa Decimal como string JSON ("1500.00"); o contrato
        do desafio mostra número (1500.00). Convertemos para float SÓ AQUI, na
        apresentação — toda comparação e persistência continua em Decimal, e um
        double representa qualquer valor de 2 casas deste domínio sem erro no
        round-trip. Alternativa (string, estilo APIs financeiras) no README."""
        return float(value)


class ErrorOut(BaseModel):
    """Formato único de erro. `detail` nunca ecoa payload do cliente nem
    mensagem interna de driver — evita reflected XSS via API e vazamento de
    detalhes de infraestrutura."""

    detail: str
