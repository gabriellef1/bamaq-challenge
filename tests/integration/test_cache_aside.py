"""Cache: o padrão no caso de uso e a resiliência no adapter Redis."""

from decimal import Decimal
from uuid import uuid4

import pytest
import redis as redis_lib

from app.adapters.outbound.cache.redis_cache import RedisRequestCache
from app.application.use_cases import GetRequest
from app.domain.entities import Request
from app.domain.exceptions import RequestNotFound

pytestmark = pytest.mark.integration


class TestCacheAsideUseCase:
    def test_hit_devolve_do_cache_sem_tocar_no_repositorio(self, repo, cache):
        request = Request.create("1", Decimal("10"))
        cache.data[request.id] = request              # pré-povoado, repo VAZIO

        result = GetRequest(repo, cache).execute(request.id)
        assert result == request
        assert repo.get_calls == 0                    # prova do hit

    def test_miss_busca_no_banco_e_popula(self, repo, cache):
        request = Request.create("1", Decimal("10"))
        repo.add(request)

        result = GetRequest(repo, cache).execute(request.id)
        assert result == request
        assert cache.data[request.id] == request      # próximo GET será hit

    def test_inexistente_levanta_not_found_sem_cachear(self, repo, cache):
        with pytest.raises(RequestNotFound):
            GetRequest(repo, cache).execute(uuid4())
        assert not cache.data


class InMemoryRedis:
    """Dublê do cliente redis com a superfície usada pelo adapter."""

    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}

    def get(self, name):
        return self.store.get(name)

    def set(self, name, value, ex):
        self.store[name] = value.encode()
        self.ttls[name] = ex

    def delete(self, *names):
        for name in names:
            self.store.pop(name, None)


class BrokenRedis:
    """Todo comando falha como se o servidor estivesse fora do ar."""

    def get(self, name):
        raise redis_lib.ConnectionError("connection refused")

    def set(self, name, value, ex):
        raise redis_lib.ConnectionError("connection refused")

    def delete(self, *names):
        raise redis_lib.ConnectionError("connection refused")


class TestRedisAdapter:
    def test_roundtrip_preserva_a_entidade_com_decimal(self):
        adapter = RedisRequestCache(InMemoryRedis(), ttl_seconds=300)
        request = Request.create("123", Decimal("1500.00"))

        adapter.set(request)
        restored = adapter.get(request.id)
        assert restored == request
        assert isinstance(restored.value, Decimal)

    def test_set_aplica_o_ttl_configurado(self):
        client = InMemoryRedis()
        adapter = RedisRequestCache(client, ttl_seconds=300, key_prefix="request")
        request = Request.create("1", Decimal("10"))

        adapter.set(request)
        assert client.ttls[f"request:{request.id}"] == 300

    def test_entrada_corrompida_vira_miss_e_e_removida(self):
        client = InMemoryRedis()
        adapter = RedisRequestCache(client, ttl_seconds=300, key_prefix="request")
        rid = uuid4()
        client.store[f"request:{rid}"] = b'{"quebrado":'

        assert adapter.get(rid) is None
        assert f"request:{rid}" not in client.store   # lixo não fica para trás

    def test_redis_fora_do_ar_degrada_sem_excecao(self):
        """A política best-effort do contrato da port: get vira miss,
        set/invalidate viram no-op — o GET do usuário segue pelo MySQL."""
        adapter = RedisRequestCache(BrokenRedis(), ttl_seconds=300)
        request = Request.create("1", Decimal("10"))

        assert adapter.get(request.id) is None
        adapter.set(request)                          # não levanta
        adapter.invalidate(request.id)                # não levanta
