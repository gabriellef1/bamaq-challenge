"""Entidades do domínio.

Zero imports de infraestrutura aqui: nada de SQLAlchemy, Pydantic, FastAPI ou
Kafka. Só a biblioteca padrão. Essa regra é verificada automaticamente por
`tests/unit/test_architecture.py` — se alguém importar infra neste pacote, o
teste quebra.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID, uuid4

from app.domain.exceptions import InvalidRequestData, InvalidStatusTransition
from app.domain.value_objects import RequestStatus

#: Limite de tamanho do identificador do cliente. Barra payloads absurdos antes
#: de chegarem ao banco (a coluna é VARCHAR(64)).
MAX_CUSTOMER_ID_LENGTH: Final[int] = 64

#: Teto do valor aceito. Sem um limite superior, um valor gigante estouraria o
#: DECIMAL(15,2) do MySQL só na hora do INSERT — falha tarde e no lugar errado.
MAX_VALUE: Final[Decimal] = Decimal("9999999999.99")


def _utc_now() -> datetime:
    """Relógio do domínio, sempre em UTC e timezone-aware.

    Datetime "naive" é uma fonte clássica de bug quando a app e o banco estão em
    fusos diferentes. Guardamos sempre UTC e convertemos só na apresentação.
    """
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Request:
    """Uma solicitação de processamento.

    É **imutável** (`frozen=True`): mudar o status não altera o objeto, produz um
    novo. Duas vantagens concretas:

    1. Nenhum trecho de código consegue alterar o status pelas costas da máquina
       de estados — a única porta de entrada é `mark_as()`, que valida a transição.
    2. Em testes, o objeto "antes" continua intacto para comparação depois da
       operação, o que torna as asserções muito mais claras.

    O custo é alocar um objeto novo a cada transição — irrelevante neste volume.
    """

    id: UUID
    customer_id: str
    value: Decimal
    status: RequestStatus
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        """Garante as invariantes na construção — inclusive vindo do banco.

        Sim, o Pydantic já valida na borda HTTP. Isto aqui é defesa em
        profundidade: a entidade também é construída pelo consumer e pelo
        repositório, caminhos que não passam pelo Pydantic. Uma invariante que
        só vale em um dos caminhos de entrada não é invariante.
        """
        customer_id = self.customer_id.strip()
        if not customer_id:
            raise InvalidRequestData("customer_id não pode ser vazio")
        if len(customer_id) > MAX_CUSTOMER_ID_LENGTH:
            raise InvalidRequestData(
                f"customer_id excede {MAX_CUSTOMER_ID_LENGTH} caracteres"
            )
        if customer_id != self.customer_id:
            # `frozen=True` bloqueia atribuição direta; object.__setattr__ é a
            # forma canônica de normalizar um campo dentro de __post_init__.
            object.__setattr__(self, "customer_id", customer_id)

        if not isinstance(self.value, Decimal):
            raise InvalidRequestData("value precisa ser Decimal, não float")
        if self.value <= 0:
            raise InvalidRequestData("value precisa ser maior que zero")
        if self.value > MAX_VALUE:
            raise InvalidRequestData(f"value excede o máximo de {MAX_VALUE}")

    # ------------------------------------------------------------------ criação
    @classmethod
    def create(
        cls,
        customer_id: str,
        value: Decimal,
        *,
        request_id: UUID | None = None,
        now: datetime | None = None,
    ) -> Request:
        """Fábrica de uma solicitação nova — nasce sempre em PENDING.

        `request_id` e `now` são parâmetros opcionais em vez de chamadas fixas a
        `uuid4()`/`now()` para que o teste possa injetar valores determinísticos.
        Sem isso, testar "o created_at foi preenchido corretamente" viraria
        monkeypatch no módulo de datetime.
        """
        moment = now or _utc_now()
        return cls(
            id=request_id or uuid4(),
            customer_id=customer_id,
            value=value,
            status=RequestStatus.PENDING,  # invariante: toda solicitação nasce pendente
            created_at=moment,
            updated_at=moment,
        )

    # --------------------------------------------------------------- transições
    @property
    def is_pending(self) -> bool:
        """Atalho de leitura usado pelo consumer para decidir se deve processar."""
        return self.status is RequestStatus.PENDING

    def mark_as(self, new_status: RequestStatus, *, now: datetime | None = None) -> Request:
        """Devolve uma NOVA solicitação com o status alterado.

        Levanta `InvalidStatusTransition` se a máquina de estados não permitir o
        caminho. Quem chama decide o que fazer com o erro: o consumer trata como
        "já processado, ignora" (idempotência); qualquer outro caminho trata como bug.
        """
        if not self.status.can_transition_to(new_status):
            raise InvalidStatusTransition(current=self.status, target=new_status)
        return replace(self, status=new_status, updated_at=now or _utc_now())
