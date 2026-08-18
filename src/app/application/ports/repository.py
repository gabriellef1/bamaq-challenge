"""Port de persistência.

Uma port é o contrato que a aplicação exige do mundo externo — escrito no
vocabulário do DOMÍNIO (Request, RequestStatus, UUID), nunca no da tecnologia
(Session, Row, cursor). O adapter SQLAlchemy vai implementar esta interface;
os testes usam um fake in-memory. Nenhum dos dois lados sabe do outro.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domain.entities import Request
from app.domain.value_objects import RequestStatus


class RequestRepository(Protocol):
    """Contrato de armazenamento de solicitações."""

    def add(self, request: Request) -> None:
        """Persiste uma solicitação nova. A transação é responsabilidade do adapter."""
        ...

    def get(self, request_id: UUID) -> Request | None:
        """Busca por id. `None` quando não existe — quem decide se isso é 404
        (API) ou anomalia (consumer) é o caso de uso, não o repositório."""
        ...

    def update_if_status(self, request: Request, expected: RequestStatus) -> bool:
        """Grava `request` SOMENTE se o status atual no banco ainda for `expected`.

        É um compare-and-set: no MySQL vira
        ``UPDATE ... WHERE id = :id AND status = :expected`` e o retorno diz se
        alguma linha foi afetada. Este é o segundo nível da idempotência — o
        primeiro é a máquina de estados do domínio; este cobre a corrida entre
        DUAS instâncias do consumer processando a mesma mensagem ao mesmo tempo,
        que nenhuma checagem em memória consegue cobrir.
        """
        ...
