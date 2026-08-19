"""Composition root da API.

Este é o ÚNICO lugar do sistema que conhece as pontas concretas ao mesmo
tempo: sabe que RequestRepository é SQLAlchemy, que EventPublisher é Kafka,
que RequestCache é Redis — e injeta tudo nos casos de uso. Domínio, aplicação
e adapters continuam sem saber uns dos outros; quem cola é este módulo.

Rodar: uvicorn app.composition.api:app
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from app.adapters.inbound.http.errors import register_error_handlers
from app.adapters.inbound.http.middleware import (
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.adapters.inbound.http.rate_limit import limiter
from app.adapters.inbound.http.routes import build_router
from app.adapters.outbound.cache.redis_cache import RedisRequestCache, build_redis_client
from app.adapters.outbound.messaging.kafka_publisher import KafkaEventPublisher, build_producer
from app.adapters.outbound.persistence.database import (
    build_engine,
    build_session_factory,
    create_tables,
)
from app.adapters.outbound.persistence.repository import SqlAlchemyRequestRepository
from app.application.use_cases import CreateRequest, GetRequest
from app.config.logging import configure_logging, get_logger
from app.config.settings import Settings, get_settings

logger = get_logger(__name__)


def _create_tables_with_retry(engine: Engine, attempts: int = 10, delay: float = 2.0) -> None:
    """O healthcheck do compose segura a API até o MySQL responder ping, mas
    'ping ok' não significa 'pronto para DDL'. Retry curto no boot cobre essa
    janela em vez de morrer no primeiro CREATE TABLE."""
    for attempt in range(1, attempts + 1):
        try:
            create_tables(engine)
            return
        except OperationalError as exc:
            if attempt == attempts:
                raise
            logger.warning("db_not_ready", attempt=attempt, error=type(exc).__name__)
            time.sleep(delay)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # async por exigência do protocolo de lifespan do FastAPI; o corpo é
        # síncrono (roda uma vez no boot, bloquear aqui não afeta requisições).
        # Infra construída AQUI (startup), não no import: importar o módulo —
        # como fazem os testes e o mypy — não exige broker nem banco no ar.
        engine = build_engine(settings)
        _create_tables_with_retry(engine)
        session_factory = build_session_factory(engine)

        repository = SqlAlchemyRequestRepository(session_factory)
        publisher = KafkaEventPublisher(
            producer=build_producer(settings),
            topic=settings.kafka_topic_requests,
            flush_timeout=settings.kafka_publish_timeout_seconds,
        )
        cache = RedisRequestCache(
            client=build_redis_client(settings),
            ttl_seconds=settings.cache_ttl_seconds,
            key_prefix=settings.cache_key_prefix,
        )

        # A mágica da hexagonal em 2 linhas: os casos de uso recebem PORTS;
        # que são MySQL/Kafka/Redis é detalhe que só este arquivo conhece.
        app.state.create_request = CreateRequest(repository=repository, publisher=publisher)
        app.state.get_request = GetRequest(repository=repository, cache=cache)

        logger.info("api_started", env=settings.app_env)
        yield
        engine.dispose()
        logger.info("api_stopped")

    app = FastAPI(
        title="BAMAQ — Processamento de Solicitações",
        version="1.0.0",
        lifespan=lifespan,
        # OpenAPI/Swagger habilitado: é vitrine e facilita a avaliação.
        docs_url="/docs",
    )

    # Middlewares ASGI: o corpo é limitado ANTES de qualquer parse; os
    # headers defensivos saem em TODA resposta (inclusive erros).
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    register_error_handlers(app)
    app.include_router(build_router(settings))
    return app


app = create_app()
