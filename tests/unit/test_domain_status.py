"""Máquina de estados: cada aresta testada explicitamente.

O mapa de transições é a base da idempotência do sistema inteiro — merece
cobertura exaustiva, e como é puro, o custo é zero.
"""

import pytest

from app.domain.value_objects import RequestStatus

ALL = list(RequestStatus)
TERMINAL = [RequestStatus.APPROVED, RequestStatus.MANUAL_REVIEW, RequestStatus.FAILED]

pytestmark = pytest.mark.unit


class TestTransitions:
    @pytest.mark.parametrize("target", TERMINAL)
    def test_pending_alcanca_todos_os_terminais(self, target):
        assert RequestStatus.PENDING.can_transition_to(target)

    def test_pending_nao_transiciona_para_si_mesmo(self):
        assert not RequestStatus.PENDING.can_transition_to(RequestStatus.PENDING)

    @pytest.mark.parametrize("origin", TERMINAL)
    @pytest.mark.parametrize("target", ALL)
    def test_terminais_nao_saem_para_lugar_nenhum(self, origin, target):
        """A propriedade que sustenta a idempotência: terminal é beco sem saída."""
        assert not origin.can_transition_to(target)


class TestProperties:
    def test_pending_e_o_unico_nao_terminal(self):
        assert not RequestStatus.PENDING.is_terminal
        for status in TERMINAL:
            assert status.is_terminal

    def test_serializa_como_string_pura(self):
        """StrEnum: o valor vai direto para JSON e para o VARCHAR do MySQL."""
        assert f"{RequestStatus.MANUAL_REVIEW}" == "MANUAL_REVIEW"
        assert RequestStatus("APPROVED") is RequestStatus.APPROVED
