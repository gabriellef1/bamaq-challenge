"""Entidade Request: invariantes, fábrica e transições."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.entities import MAX_VALUE, Request
from app.domain.exceptions import InvalidRequestData, InvalidStatusTransition
from app.domain.value_objects import RequestStatus

pytestmark = pytest.mark.unit


def make(value="100.00", customer="123"):
    return Request.create(customer_id=customer, value=Decimal(value))


class TestCreate:
    def test_nasce_pending_com_uuid_e_timestamps(self):
        moment = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
        rid = uuid4()
        r = Request.create("123", Decimal("10"), request_id=rid, now=moment)
        assert r.status is RequestStatus.PENDING
        assert r.id == rid and r.created_at == moment and r.updated_at == moment

    def test_normaliza_espacos_do_customer_id(self):
        assert make(customer="  123  ").customer_id == "123"

    @pytest.mark.parametrize(
        ("customer", "value", "motivo"),
        [
            ("", "10", "customer vazio"),
            ("   ", "10", "customer só espaços"),
            ("x" * 65, "10", "customer longo demais"),
            ("123", "0", "valor zero"),
            ("123", "-0.01", "valor negativo"),
        ],
    )
    def test_rejeita_dados_invalidos(self, customer, value, motivo):
        with pytest.raises(InvalidRequestData):
            make(customer=customer, value=value)

    def test_rejeita_float_explicitamente(self):
        """float em dinheiro é erro de programação — a entidade não converte."""
        with pytest.raises(InvalidRequestData, match="Decimal"):
            Request.create("123", 100.0)

    def test_rejeita_valor_acima_do_teto(self):
        with pytest.raises(InvalidRequestData):
            make(value=str(MAX_VALUE + 1))

    def test_aceita_exatamente_o_teto(self):
        assert make(value=str(MAX_VALUE)).value == MAX_VALUE


class TestMarkAs:
    def test_devolve_nova_instancia_e_preserva_a_original(self):
        original = make()
        updated = original.mark_as(RequestStatus.APPROVED)
        assert updated is not original
        assert original.status is RequestStatus.PENDING  # imutável
        assert updated.status is RequestStatus.APPROVED
        assert updated.id == original.id

    def test_atualiza_updated_at_e_preserva_created_at(self):
        original = make()
        later = datetime(2030, 1, 1, tzinfo=UTC)
        updated = original.mark_as(RequestStatus.APPROVED, now=later)
        assert updated.updated_at == later
        assert updated.created_at == original.created_at

    def test_transicao_de_terminal_e_erro(self):
        done = make().mark_as(RequestStatus.APPROVED)
        with pytest.raises(InvalidStatusTransition):
            done.mark_as(RequestStatus.MANUAL_REVIEW)

    def test_entidade_e_congelada(self):
        with pytest.raises(AttributeError):
            make().status = RequestStatus.APPROVED
