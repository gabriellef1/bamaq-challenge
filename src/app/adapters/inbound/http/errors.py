"""Tradução de exceções internas -> respostas HTTP.

Este módulo é o "dicionário" entre a linguagem do domínio/aplicação e o
protocolo HTTP. O domínio levanta RequestNotFound sem saber o que é 404;
quem sabe é o adapter de entrada. É aqui que a hexagonal aparece na prática.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.application.exceptions import EventPublishError
from app.config.logging import get_logger
from app.domain.exceptions import InvalidRequestData, RequestNotFound

logger = get_logger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestNotFound)
    def _not_found(_req: Request, exc: RequestNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            # Ecoamos o id (UUID já validado pelo path param), nunca payload cru.
            content={"detail": f"solicitação não encontrada: {exc.request_id}"},
        )

    @app.exception_handler(InvalidRequestData)
    def _invalid_data(_req: Request, exc: InvalidRequestData) -> JSONResponse:
        # Rede de segurança: o Pydantic barra 99% antes, mas a invariante do
        # domínio é a palavra final (defesa em profundidade).
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": str(exc)},
        )

    @app.exception_handler(EventPublishError)
    def _publish_failed(_req: Request, _exc: EventPublishError) -> JSONResponse:
        # A solicitação FOI persistida (PENDING); o disparo do processamento
        # falhou. 503 diz "tente de novo mais tarde" sem expor detalhe de broker.
        logger.error("request_accepted_but_not_dispatched")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "serviço de processamento indisponível, tente novamente"},
            headers={"Retry-After": "5"},
        )

    @app.exception_handler(SQLAlchemyError)
    def _database_down(_req: Request, exc: SQLAlchemyError) -> JSONResponse:
        # Erro de conexão/infra do banco: logamos o real (para nós), devolvemos
        # o genérico (para o cliente). Mensagem de driver em resposta HTTP é
        # vazamento de topologia interna.
        logger.error("database_error", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "banco de dados indisponível, tente novamente"},
            headers={"Retry-After": "5"},
        )
