"""Port de cache de leitura."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domain.entities import Request


class RequestCache(Protocol):
    """Contrato de cache para o padrão cache-aside.

    POLÍTICA DO CONTRATO: cache é acelerador, nunca fonte de verdade — uma
    falha de cache não pode derrubar uma leitura que o MySQL consegue atender.
    Por isso as implementações NÃO devem propagar erros de infraestrutura:
    Redis fora do ar => `get` responde `None` (miss) e `set`/`invalidate`
    viram no-op logado. Essa regra fica na port (e não em cada caso de uso)
    para valer para qualquer chamador e qualquer implementação.
    """

    def get(self, request_id: UUID) -> Request | None:
        """Devolve a solicitação cacheada, ou `None` em caso de miss OU de erro."""
        ...

    def set(self, request: Request) -> None:
        """Armazena com TTL (definido pelo adapter via configuração). Best-effort."""
        ...

    def invalidate(self, request_id: UUID) -> None:
        """Remove a entrada. Chamado pelo consumer após mudar o status. Best-effort."""
        ...
