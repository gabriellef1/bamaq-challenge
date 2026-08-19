"""GET /requests/{id} — consulta, 404 e o cache-aside observável pela API."""

from decimal import Decimal

import pytest

from app.domain.entities import Request

pytestmark = pytest.mark.integration


@pytest.fixture
def stored(repo):
    request = Request.create("123", Decimal("1500.00"))
    repo.add(request)
    return request


class TestGet:
    def test_200_com_estado_atual(self, client, stored):
        resp = client.get(f"/requests/{stored.id}")
        assert resp.status_code == 200
        assert resp.json() == {
            "id": str(stored.id),
            "customer_id": "123",
            "value": 1500.0,
            "status": "PENDING",
        }

    def test_404_para_id_inexistente(self, client):
        resp = client.get("/requests/00000000-0000-0000-0000-000000000001")
        assert resp.status_code == 404
        assert "detail" in resp.json()

    def test_422_para_id_que_nem_e_uuid(self, client, repo):
        assert client.get("/requests/nao-e-uuid").status_code == 422
        assert repo.get_calls == 0  # barrado antes de qualquer port

    def test_headers_defensivos_em_toda_resposta(self, client, stored):
        for path in (f"/requests/{stored.id}", "/requests/00000000-0000-0000-0000-000000000001"):
            resp = client.get(path)
            assert resp.headers["x-content-type-options"] == "nosniff"
            assert resp.headers["cache-control"] == "no-store"


class TestCacheAsideViaApi:
    def test_miss_popula_e_hit_nao_toca_no_banco(self, client, repo, cache, stored):
        """A sequência canônica do cache-aside, observada pela borda HTTP."""
        client.get(f"/requests/{stored.id}")       # miss -> banco -> set
        calls_after_miss = repo.get_calls
        assert cache.ops == [("get", stored.id), ("set", stored.id)]

        client.get(f"/requests/{stored.id}")       # hit -> banco intocado
        assert repo.get_calls == calls_after_miss
        assert cache.ops[-1] == ("get", stored.id)

    def test_404_nao_polui_o_cache(self, client, cache):
        client.get("/requests/00000000-0000-0000-0000-000000000001")
        assert all(op != "set" for op, _ in cache.ops)
