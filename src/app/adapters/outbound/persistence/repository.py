"""Adapter: implementação MySQL/SQLAlchemy da port RequestRepository.

Repare que a classe NÃO herda de RequestRepository — `typing.Protocol` é
estrutural, a conformidade é verificada pelo mypy no ponto de injeção.

SEGURANÇA — SQL injection: nenhuma query aqui concatena strings. Tudo passa
pelo expression language do SQLAlchemy (`select(...).where(Model.id == valor)`),
que SEMPRE gera placeholders parametrizados (`WHERE id = %s`) e envia o valor
separado do SQL. O driver nunca interpreta dado como código.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.outbound.persistence.mappers import _to_naive_utc, to_domain, to_model
from app.adapters.outbound.persistence.models import RequestModel
from app.domain.entities import Request
from app.domain.value_objects import RequestStatus


class SqlAlchemyRequestRepository:
    """Uma sessão POR OPERAÇÃO (unit of work curto): abre, executa, commita,
    fecha. Simples e sem estado — a alternativa (sessão por request HTTP com
    UoW explícito) só paga quando um caso de uso escreve em vários agregados
    na mesma transação, o que não acontece aqui."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, request: Request) -> None:
        with self._session_factory() as session, session.begin():
            session.add(to_model(request))
        # session.begin() commita ao sair sem exceção e faz rollback se houver.

    def get(self, request_id: UUID) -> Request | None:
        with self._session_factory() as session:
            model = session.scalar(
                select(RequestModel).where(RequestModel.id == str(request_id))
            )
            return to_domain(model) if model else None

    def update_if_status(self, request: Request, expected: RequestStatus) -> bool:
        """Compare-and-set em um único statement atômico:

            UPDATE requests SET status=%s, updated_at=%s
             WHERE id=%s AND status=%s

        O MySQL tranca a linha durante o UPDATE; dois consumers concorrentes
        serializam aqui e apenas um vê rowcount == 1. Não há janela entre
        "ler" e "escrever" porque a condição está DENTRO do próprio UPDATE.
        """
        with self._session_factory() as session, session.begin():
            result = session.execute(
                update(RequestModel)
                .where(
                    RequestModel.id == str(request.id),
                    RequestModel.status == expected.value,
                )
                .values(
                    status=request.status.value,
                    updated_at=_to_naive_utc(request.updated_at),
                )
            )
            return result.rowcount == 1
