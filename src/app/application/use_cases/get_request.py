"""Caso de uso: consultar uma solicitação (GET /requests/{id})."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.application.ports import RequestCache, RequestRepository
from app.domain.entities import Request
from app.domain.exceptions import RequestNotFound


@dataclass(frozen=True, slots=True)
class GetRequest:
    """Cache-aside: o padrão vive AQUI, não no adapter Redis.

    O adapter sabe falar com o Redis; a DECISÃO de "olhar cache primeiro,
    cair para o banco no miss, repovoar" é regra da aplicação. Se amanhã o
    Redis virar Memcached, esta classe não muda uma linha.
    """

    repository: RequestRepository
    cache: RequestCache

    def execute(self, request_id: UUID) -> Request:
        cached = self.cache.get(request_id)
        if cached is not None:
            return cached  # hit: nem toca no MySQL

        request = self.repository.get(request_id)
        if request is None:
            # Miss de cache E de banco: não existe. A API traduz em 404.
            # De propósito NÃO cacheamos o negativo — evita a sutileza de um
            # 404 "grudado" se o id passar a existir; trade-off no README.
            raise RequestNotFound(request_id)

        self.cache.set(request)  # popula para os próximos leitores
        return request
