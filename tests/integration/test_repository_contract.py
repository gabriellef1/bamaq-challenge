"""Contrato do repositório SQLAlchemy contra um banco real (SQLite in-memory).

O dialeto muda (SQLite aqui, MySQL em produção) mas o CONTRATO — roundtrip
fiel e CAS atômico — é o mesmo, porque tudo passa pelo expression language.
O comportamento específico do MySQL é coberto pela validação e2e da stack.
"""

import warnings
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.adapters.outbound.persistence.models import Base
from app.adapters.outbound.persistence.repository import SqlAlchemyRequestRepository
from app.domain.entities import Request
from app.domain.value_objects import RequestStatus

pytestmark = pytest.mark.integration


@pytest.fixture
def sql_repo():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with warnings.catch_warnings():
        # SQLite não tem DECIMAL nativo e o SQLAlchemy avisa; no MySQL o tipo
        # é exato. O aviso é esperado AQUI e só aqui.
        warnings.simplefilter("ignore")
        yield SqlAlchemyRequestRepository(sessionmaker(bind=engine, expire_on_commit=False))


class TestRoundtrip:
    def test_add_get_preserva_tipos_do_dominio(self, sql_repo):
        request = Request.create("123", Decimal("1500.00"))
        sql_repo.add(request)

        restored = sql_repo.get(request.id)
        assert restored == request
        assert isinstance(restored.value, Decimal)
        assert restored.created_at.tzinfo is not None  # volta aware-UTC

    def test_get_inexistente_devolve_none(self, sql_repo):
        assert sql_repo.get(uuid4()) is None


class TestCompareAndSet:
    def test_vence_quando_o_status_esperado_confere(self, sql_repo):
        request = Request.create("1", Decimal("100"))
        sql_repo.add(request)
        updated = request.mark_as(RequestStatus.APPROVED)

        assert sql_repo.update_if_status(updated, expected=RequestStatus.PENDING) is True
        assert sql_repo.get(request.id).status is RequestStatus.APPROVED

    def test_perde_quando_outro_ja_transicionou(self, sql_repo):
        """A corrida no nível do banco: o segundo UPDATE condicional vê
        rowcount 0 e NÃO sobrescreve a decisão do primeiro."""
        request = Request.create("1", Decimal("100"))
        sql_repo.add(request)
        winner = request.mark_as(RequestStatus.APPROVED)
        loser = request.mark_as(RequestStatus.MANUAL_REVIEW)

        assert sql_repo.update_if_status(winner, expected=RequestStatus.PENDING) is True
        assert sql_repo.update_if_status(loser, expected=RequestStatus.PENDING) is False
        assert sql_repo.get(request.id).status is RequestStatus.APPROVED
