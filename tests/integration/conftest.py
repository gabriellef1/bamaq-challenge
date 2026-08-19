"""Fixtures da suíte de integração.

"Integração" aqui = as peças reais da aplicação (rotas, casos de uso,
handler) integradas entre si, com FAKES nas ports de infraestrutura.
Nenhum container é necessário; a stack real é exercitada à parte (e2e).
"""

import pytest
from fastapi.testclient import TestClient
from tests.fakes import FakeEventPublisher, FakeRequestCache, FakeRequestRepository

from app.adapters.inbound.http.rate_limit import limiter
from app.adapters.inbound.http.routes import get_create_request, get_get_request
from app.application.use_cases import CreateRequest, GetRequest
from app.composition.api import create_app
from app.config.settings import Settings


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """O limiter é singleton com storage in-memory: sem reset, um teste
    "gastaria" o budget do seguinte e a suíte ficaria dependente de ordem."""
    limiter.reset()


@pytest.fixture
def settings():
    # _env_file=None: o teste NUNCA lê o .env da máquina — ambiente hermético.
    return Settings(
        _env_file=None,
        mysql_password="test",
        rate_limit_create="1000/minute",
        rate_limit_read="1000/minute",
    )


@pytest.fixture
def repo():
    return FakeRequestRepository()


@pytest.fixture
def cache():
    return FakeRequestCache()


@pytest.fixture
def publisher():
    return FakeEventPublisher()


@pytest.fixture
def app(settings, repo, cache, publisher):
    application = create_app(settings)
    application.dependency_overrides[get_create_request] = lambda: CreateRequest(repo, publisher)
    application.dependency_overrides[get_get_request] = lambda: GetRequest(repo, cache)
    return application


@pytest.fixture
def client(app):
    # Sem `with`: o lifespan (que constrói infra real) não roda — as ports
    # vêm dos overrides acima. É o composition root trocado pelo de teste.
    return TestClient(app, raise_server_exceptions=False)
