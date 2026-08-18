"""Regras de negócio.

Funções puras: mesma entrada, mesma saída, nenhum efeito colateral, nenhuma
dependência de banco, fila ou relógio. É a parte do sistema que o avaliador vai
querer ler primeiro — e a mais barata de testar, porque roda em memória.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from app.domain.entities import Request
from app.domain.value_objects import RequestStatus

#: Teto da aprovação automática. Acima disso, um humano precisa olhar.
#:
#: Decimal("1000.00") e não 1000.0: float binário não representa valores
#: decimais exatamente (0.1 + 0.2 != 0.3), e uma comparação de fronteira em
#: dinheiro é exatamente onde esse erro aparece. Todo o fluxo monetário deste
#: projeto é Decimal, do JSON ao DECIMAL(15,2) do MySQL.
AUTO_APPROVAL_LIMIT: Final[Decimal] = Decimal("1000.00")


def decide_status(value: Decimal) -> RequestStatus:
    """Aplica a regra de decisão sobre um valor monetário.

    ``value <= 1000`` -> APPROVED · ``value > 1000`` -> MANUAL_REVIEW

    O limite é inclusivo: exatamente 1000.00 é aprovado automaticamente, como
    especifica o enunciado.
    """
    if value <= AUTO_APPROVAL_LIMIT:
        return RequestStatus.APPROVED
    return RequestStatus.MANUAL_REVIEW


def evaluate(request: Request) -> RequestStatus:
    """Decide o status final de uma solicitação.

    Existe separado de `decide_status` para dar ao caso de uso um ponto único de
    entrada orientado à entidade. Quando a regra deixar de depender só do valor
    (score do cliente, histórico, horário), é esta função que cresce — a
    assinatura de quem chama fica igual.
    """
    return decide_status(request.value)
