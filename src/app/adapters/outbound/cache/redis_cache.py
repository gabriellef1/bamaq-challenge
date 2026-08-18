"""Adapter: implementação Redis da port RequestCache.

Cumpre a política da port: cache é acelerador, não fonte de verdade. TODO erro
de infraestrutura (Redis fora, timeout, payload corrompido) é logado e engolido
— `get` degrada para miss, `set`/`invalidate` para no-op. O GET do usuário
continua funcionando pelo MySQL.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

import redis

from app.config.logging import get_logger
from app.config.settings import Settings
from app.domain.entities import Request
from app.domain.value_objects import RequestStatus

logger = get_logger(__name__)

#: Erros que tratamos como "Redis indisponível". Deliberadamente NÃO inclui
#: coisas como TypeError — bug de programação deve estourar, não ser engolido.
_REDIS_ERRORS = (redis.RedisError, OSError)


class _RedisLike(Protocol):
    """Superfície mínima do cliente que usamos (dublê nos testes)."""

    def get(self, name: str) -> bytes | None: ...
    def set(self, name: str, value: str, ex: int) -> object: ...
    def delete(self, *names: str) -> object: ...


def build_redis_client(settings: Settings) -> redis.Redis:
    return redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password.get_secret_value() or None,
        # Timeouts curtos: um Redis lento NÃO pode segurar a requisição — o
        # fallback (MySQL) é mais rápido que esperar 30s de timeout default.
        socket_timeout=0.5,
        socket_connect_timeout=0.5,
    )


class RedisRequestCache:
    def __init__(self, client: _RedisLike, ttl_seconds: int, key_prefix: str = "request") -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._prefix = key_prefix

    def _key(self, request_id: UUID) -> str:
        return f"{self._prefix}:{request_id}"

    # ------------------------------------------------------------------ leitura
    def get(self, request_id: UUID) -> Request | None:
        try:
            raw = self._client.get(self._key(request_id))
        except _REDIS_ERRORS as exc:
            logger.warning("cache_get_failed", request_id=str(request_id), error=str(exc))
            return None
        if raw is None:
            return None
        try:
            return _deserialize(raw)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            # Entrada corrompida (deploy mudou o formato?): descarta e segue
            # como miss — o próximo set regrava no formato novo.
            logger.warning("cache_entry_corrupted", request_id=str(request_id), error=str(exc))
            self.invalidate(request_id)
            return None

    # ------------------------------------------------------------------ escrita
    def set(self, request: Request) -> None:
        try:
            # SET com EX atômico. O TTL é rede de segurança contra entrada órfã
            # (ex.: invalidação perdida) — a consistência primária vem do
            # DELETE explícito feito pelo consumer.
            self._client.set(self._key(request.id), _serialize(request), ex=self._ttl)
        except _REDIS_ERRORS as exc:
            logger.warning("cache_set_failed", request_id=str(request.id), error=str(exc))

    def invalidate(self, request_id: UUID) -> None:
        try:
            self._client.delete(self._key(request_id))
        except _REDIS_ERRORS as exc:
            logger.warning("cache_invalidate_failed", request_id=str(request_id), error=str(exc))


# ---------------------------------------------------------------- serialização
# JSON manual e explícito: Decimal vira string (nunca float — perderia
# exatidão), datetime vira ISO-8601. A volta reconstrói a ENTIDADE, que
# revalida as invariantes.

def _serialize(request: Request) -> str:
    return json.dumps(
        {
            "id": str(request.id),
            "customer_id": request.customer_id,
            "value": str(request.value),
            "status": request.status.value,
            "created_at": request.created_at.isoformat(),
            "updated_at": request.updated_at.isoformat(),
        }
    )


def _deserialize(raw: bytes) -> Request:
    data = json.loads(raw)
    return Request(
        id=UUID(data["id"]),
        customer_id=data["customer_id"],
        value=Decimal(data["value"]),
        status=RequestStatus(data["status"]),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
    )
