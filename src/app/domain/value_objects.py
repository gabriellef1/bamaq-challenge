"""Objetos de valor do domínio."""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class RequestStatus(StrEnum):
    """Ciclo de vida de uma solicitação.

    `StrEnum` (Python 3.11+) faz cada membro ser também uma `str`, então o valor
    já serializa direto em JSON e vai para o MySQL sem conversão manual — sem
    abrir mão da checagem de tipo e do autocomplete.

    Máquina de estados::

        PENDING ──> APPROVED        (value <= 1000, automático)
                ──> MANUAL_REVIEW   (value  > 1000, exige análise humana)
                ──> FAILED          (falha definitiva no processamento -> DLQ)

    PENDING é o único estado não-terminal. Essa propriedade é a base da
    idempotência: se o consumer recebe a mesma mensagem duas vezes, a segunda
    encontra a solicitação já fora de PENDING e simplesmente não faz nada.
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        """Verdadeiro quando o status não admite mais nenhuma transição.

        Nota de escopo: no mundo real MANUAL_REVIEW seria transitório — um
        analista depois aprovaria ou recusaria. Aqui ele é terminal porque o
        desafio não prevê essa segunda etapa; acrescentá-la significaria só
        abrir novas arestas em `_ALLOWED_TRANSITIONS`.
        """
        return self is not RequestStatus.PENDING

    def can_transition_to(self, target: RequestStatus) -> bool:
        """Diz se `self -> target` é um caminho permitido pela máquina de estados."""
        return target in _ALLOWED_TRANSITIONS[self]


# Mapa explícito de transições. Deixar isto como dado (e não como uma cadeia de
# `if`) permite ler a máquina de estados inteira de uma vez e testá-la exaustivamente.
_ALLOWED_TRANSITIONS: Final[dict[RequestStatus, frozenset[RequestStatus]]] = {
    RequestStatus.PENDING: frozenset(
        {RequestStatus.APPROVED, RequestStatus.MANUAL_REVIEW, RequestStatus.FAILED}
    ),
    RequestStatus.APPROVED: frozenset(),
    RequestStatus.MANUAL_REVIEW: frozenset(),
    RequestStatus.FAILED: frozenset(),
}
