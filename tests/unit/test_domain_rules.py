"""Regra de negócio: a fronteira do 1000 é o coração do desafio."""

from decimal import Decimal

import pytest

from app.domain.entities import Request
from app.domain.rules import AUTO_APPROVAL_LIMIT, decide_status, evaluate
from app.domain.value_objects import RequestStatus

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.01", RequestStatus.APPROVED),
        ("999.99", RequestStatus.APPROVED),
        ("1000.00", RequestStatus.APPROVED),   # fronteira INCLUSIVA (<=)
        ("1000.01", RequestStatus.MANUAL_REVIEW),
        ("1500.00", RequestStatus.MANUAL_REVIEW),
        ("9999999999.99", RequestStatus.MANUAL_REVIEW),
    ],
)
def test_decide_status(value, expected):
    assert decide_status(Decimal(value)) is expected


def test_limite_e_decimal_exato():
    """Se alguém trocar por float, este teste denuncia."""
    assert Decimal("1000.00") == AUTO_APPROVAL_LIMIT
    assert isinstance(AUTO_APPROVAL_LIMIT, Decimal)


def test_evaluate_delega_para_decide_status():
    r = Request.create("123", Decimal("1500.00"))
    assert evaluate(r) is RequestStatus.MANUAL_REVIEW
