"""Rotas HTTP — o adapter de entrada.

Cada endpoint tem 3 responsabilidades e SÓ elas: validar o formato (delegado
aos schemas), chamar o caso de uso, formatar a resposta. Nenhuma regra de
negócio aqui — se um `if value > 1000` aparecer neste arquivo, a arquitetura
foi violada.

Endpoints são `def` síncronos DE PROPÓSITO: o FastAPI os executa num
threadpool, então o I/O bloqueante (MySQL, Kafka, Redis) não trava o event
loop. Foi a decisão de modelo síncrono aprovada na etapa (a).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.adapters.inbound.http.rate_limit import limiter
from app.adapters.inbound.http.schemas import CreateRequestIn, ErrorOut, RequestOut
from app.application.use_cases import CreateRequest, GetRequest
from app.config.logging import get_logger
from app.config.settings import Settings
from app.domain.entities import Request as DomainRequest

logger = get_logger(__name__)


# ---------------------------------------------------------------- injeção ----
# Providers lidos de app.state, onde o composition root pendura as instâncias.
# Os testes trocam por fakes via dependency_overrides — sem tocar em rota.
def get_create_request(request: Request) -> CreateRequest:
    return request.app.state.create_request  # type: ignore[no-any-return]


def get_get_request(request: Request) -> GetRequest:
    return request.app.state.get_request  # type: ignore[no-any-return]


def _to_response(request: DomainRequest) -> RequestOut:
    return RequestOut(
        id=str(request.id),
        customer_id=request.customer_id,
        value=request.value,
        status=request.status,
    )


def build_router(settings: Settings) -> APIRouter:
    """Router construído em fábrica para aplicar os limites de rate vindos da
    configuração (o decorator do slowapi exige a string no momento da
    definição da rota)."""
    router = APIRouter()

    @router.post(
        "/requests",
        status_code=status.HTTP_201_CREATED,
        response_model=RequestOut,
        responses={422: {"model": ErrorOut}, 429: {"model": ErrorOut}, 503: {"model": ErrorOut}},
        summary="Cria uma solicitação de processamento",
    )
    @limiter.limit(settings.rate_limit_create)
    def create_request(
        request: Request,  # exigido pelo slowapi (extrai o IP daqui)
        payload: CreateRequestIn,
        response: Response,
        use_case: Annotated[CreateRequest, Depends(get_create_request)],
    ) -> RequestOut:
        created = use_case.execute(customer_id=payload.customer_id, value=payload.value)
        # Location: onde consultar o recurso recém-criado (REST básico bem feito).
        response.headers["Location"] = f"/requests/{created.id}"
        # Log com identificadores, nunca com value/customer (política de logs).
        logger.info("request_created", request_id=str(created.id))
        return _to_response(created)

    @router.get(
        "/requests/{request_id}",
        response_model=RequestOut,
        responses={404: {"model": ErrorOut}, 422: {"model": ErrorOut}, 429: {"model": ErrorOut}},
        summary="Consulta o estado atual de uma solicitação",
    )
    @limiter.limit(settings.rate_limit_read)
    def get_request(
        request: Request,
        request_id: UUID,  # tipado como UUID: id malformado -> 422 automático
        use_case: Annotated[GetRequest, Depends(get_get_request)],
    ) -> RequestOut:
        return _to_response(use_case.execute(request_id))

    @router.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        """Liveness raso: responde se o processo está vivo. NÃO checa MySQL/
        Kafka/Redis de propósito — um health profundo faria o orquestrador
        reiniciar a API por culpa de dependência, transformando incidente
        pequeno em cascata de restarts."""
        return {"status": "ok"}

    return router
