"""Caso de uso: processar o evento consumido do Kafka."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, auto
from uuid import UUID

from app.application.ports import RequestCache, RequestRepository
from app.domain.entities import Request
from app.domain.exceptions import RequestNotFound
from app.domain.rules import evaluate
from app.domain.value_objects import RequestStatus


class ProcessingOutcome(StrEnum):
    """O que aconteceu com a mensagem — o consumer loga e commita o offset com base nisso."""

    PROCESSED = auto()          # transição aplicada por esta execução
    SKIPPED_NOT_PENDING = auto()  # já estava finalizada: duplicata, ignorar em paz
    SKIPPED_LOST_RACE = auto()    # outra instância venceu o compare-and-set no banco


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    outcome: ProcessingOutcome
    request: Request


@dataclass(frozen=True, slots=True)
class ProcessRequestEvent:
    """Aplica a regra de negócio e efetiva a transição de status.

    IDEMPOTÊNCIA EM DUAS CAMADAS — Kafka entrega at-least-once, duplicatas
    são fato da vida, então:

    1. Checagem de domínio (`is_pending`): barra o caso comum — a mensagem
       reentregue depois que a primeira execução já finalizou.
    2. Compare-and-set no banco (`update_if_status`): barra o caso raro que a
       camada 1 NÃO cobre — duas instâncias do consumer leram PENDING ao mesmo
       tempo (rebalance no meio do processamento, por exemplo). Só uma vence o
       UPDATE condicional; a outra vê rowcount 0 e desiste.

    Qualquer um dos dois "skips" é sucesso do ponto de vista do consumer:
    a mensagem foi tratada, o offset pode ser commitado.
    """

    repository: RequestRepository
    cache: RequestCache

    def execute(self, request_id: UUID) -> ProcessingResult:
        request = self.repository.get(request_id)
        if request is None:
            # Anômalo: publicamos DEPOIS do commit, então o evento sempre
            # referencia linha existente. Se cair aqui, algo grave aconteceu
            # (banco restaurado de backup?). Propaga -> retry -> DLQ.
            raise RequestNotFound(request_id)

        if not request.is_pending:
            return ProcessingResult(ProcessingOutcome.SKIPPED_NOT_PENDING, request)

        updated = request.mark_as(evaluate(request))

        if not self.repository.update_if_status(updated, expected=RequestStatus.PENDING):
            lost_to = self.repository.get(request_id) or request
            return ProcessingResult(ProcessingOutcome.SKIPPED_LOST_RACE, lost_to)

        # Invalidação DEPOIS do commit: apagar antes abriria janela para outro
        # leitor repovoar o cache com o status antigo lido do banco.
        self.cache.invalidate(updated.id)
        return ProcessingResult(ProcessingOutcome.PROCESSED, updated)


@dataclass(frozen=True, slots=True)
class MarkRequestAsFailed:
    """Marca FAILED quando o consumer esgota os retries e envia a mensagem à DLQ.

    Sem isso a solicitação ficaria PENDING para sempre e o cliente jamais
    saberia que o processamento morreu. Usa o mesmo compare-and-set: se a
    solicitação já saiu de PENDING por outro caminho, não sobrescreve.
    """

    repository: RequestRepository
    cache: RequestCache

    def execute(self, request_id: UUID) -> ProcessingResult:
        request = self.repository.get(request_id)
        if request is None:
            raise RequestNotFound(request_id)
        if not request.is_pending:
            return ProcessingResult(ProcessingOutcome.SKIPPED_NOT_PENDING, request)

        failed = request.mark_as(RequestStatus.FAILED)
        if not self.repository.update_if_status(failed, expected=RequestStatus.PENDING):
            lost_to = self.repository.get(request_id) or request
            return ProcessingResult(ProcessingOutcome.SKIPPED_LOST_RACE, lost_to)

        self.cache.invalidate(failed.id)
        return ProcessingResult(ProcessingOutcome.PROCESSED, failed)
