"""POST /requests — contrato, validação de borda e falha de publicação."""

from decimal import Decimal

import pytest

from app.adapters.inbound.http.routes import get_create_request
from app.application.exceptions import EventPublishError
from app.application.use_cases import CreateRequest

pytestmark = pytest.mark.integration

PAYLOAD = {"customer_id": "123", "value": 1500.00}


class TestHappyPath:
    def test_201_com_contrato_do_enunciado(self, client, repo, publisher):
        resp = client.post("/requests", json=PAYLOAD)
        assert resp.status_code == 201
        body = resp.json()
        assert set(body) == {"id", "customer_id", "value", "status"}
        assert body["customer_id"] == "123"
        assert body["value"] == 1500.0
        assert body["status"] == "PENDING"

    def test_location_aponta_para_o_recurso(self, client):
        resp = client.post("/requests", json=PAYLOAD)
        assert resp.headers["location"] == f"/requests/{resp.json()['id']}"

    def test_persiste_e_publica_exatamente_uma_vez(self, client, repo, publisher):
        resp = client.post("/requests", json=PAYLOAD)
        assert len(repo.rows) == 1 and len(publisher.published) == 1
        stored = next(iter(repo.rows.values()))
        assert str(stored.id) == resp.json()["id"]
        assert stored.value == Decimal("1500.00")  # Decimal de ponta a ponta
        assert publisher.published[0] == stored.id

    def test_ids_sao_unicos(self, client):
        ids = {client.post("/requests", json=PAYLOAD).json()["id"] for _ in range(5)}
        assert len(ids) == 5


class TestValidation:
    @pytest.mark.parametrize(
        "payload",
        [
            {"customer_id": "123"},                              # value ausente
            {"value": 10},                                       # customer ausente
            {"customer_id": "123", "value": 0},                  # zero
            {"customer_id": "123", "value": -5},                 # negativo
            {"customer_id": "123", "value": 10.555},             # 3 casas decimais
            {"customer_id": "123", "value": "abc"},              # não numérico
            {"customer_id": "", "value": 10},                    # customer vazio
            {"customer_id": "a b", "value": 10},                 # espaço (whitelist)
            {"customer_id": "1;DROP TABLE", "value": 10},        # injeção óbvia
            {"customer_id": "x" * 65, "value": 10},              # longo demais
            {"customer_id": "123", "value": 10, "extra": 1},     # campo extra
        ],
        ids=lambda p: str(sorted(p.items()))[:45],
    )
    def test_payload_invalido_da_422_e_nao_toca_nas_ports(self, client, repo, publisher, payload):
        assert client.post("/requests", json=payload).status_code == 422
        assert not repo.rows and not publisher.published  # morreu NA borda

    def test_corpo_gigante_da_413_antes_do_parse(self, settings, repo, publisher, app):
        from fastapi.testclient import TestClient

        big = '{"customer_id": "123", "value": 10, "x": "' + "a" * 20_000 + '"}'
        client = TestClient(app)
        resp = client.post("/requests", content=big, headers={"content-type": "application/json"})
        assert resp.status_code == 413


class TestPublishFailure:
    def test_broker_fora_da_503_mas_persiste_pending(self, client, repo, app):
        """A decisão de design mais importante do POST: persistir ANTES de
        publicar. O cliente recebe 503 (retry), mas a linha existe e é PENDING —
        estado honesto e auditável."""

        class DeadPublisher:
            def publish_created(self, request):
                raise EventPublishError("broker down")

        app.dependency_overrides[get_create_request] = lambda: CreateRequest(
            repo, DeadPublisher()
        )
        resp = client.post("/requests", json=PAYLOAD)
        assert resp.status_code == 503
        assert resp.headers["retry-after"] == "5"
        assert len(repo.rows) == 1 and next(iter(repo.rows.values())).is_pending


class TestRateLimit:
    def test_estoura_o_limite_da_429(self, settings, repo, publisher):
        from fastapi.testclient import TestClient

        from app.composition.api import create_app

        s = settings.model_copy(update={"rate_limit_create": "3/minute"})
        app = create_app(s)
        app.dependency_overrides[get_create_request] = lambda: CreateRequest(repo, publisher)
        client = TestClient(app)
        codes = [client.post("/requests", json=PAYLOAD).status_code for _ in range(5)]
        assert codes == [201, 201, 201, 429, 429]
