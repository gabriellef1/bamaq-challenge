"""Handler de mensagens: o cérebro do consumer, SEM saber que Kafka existe.

Recebe bytes + metadados, devolve um veredito. Toda a política de erro mora
aqui — retry com backoff, classificação retryável/não-retryável, DLQ — e por
isso é testável em memória pura. O loop de consumo (kafka_loop.py) fica burro
de propósito: poll, delega, commita.

CLASSIFICAÇÃO DE ERROS — a decisão central:

- NÃO-RETRYÁVEL (DLQ imediata): payload malformado (ValidationError) e
  violações de regra (DomainError). Uma mensagem corrompida não fica boa na
  segunda tentativa; retry aqui só atrasa a fila.
- RETRYÁVEL (backoff e nova tentativa): infraestrutura transitória —
  SQLAlchemyError (MySQL reiniciando, conexão caída), OSError (rede) e
  RequestNotFound (anômalo, mas pode ser atraso de visibilidade; se persistir
  após os retries, vira DLQ como tudo).
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum, auto
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.outbound.messaging.dlq_publisher import KafkaDlqPublisher
from app.adapters.shared.events import RequestCreatedEvent
from app.application.use_cases import MarkRequestAsFailed, ProcessRequestEvent
from app.config.logging import get_logger
from app.domain.exceptions import DomainError, RequestNotFound

logger = get_logger(__name__)

_RETRYABLE = (SQLAlchemyError, OSError, RequestNotFound)


class HandleOutcome(StrEnum):
    PROCESSED = auto()
    SKIPPED_DUPLICATE = auto()
    SENT_TO_DLQ = auto()


@dataclass
class MessageHandler:
    process: ProcessRequestEvent
    mark_failed: MarkRequestAsFailed
    dlq: KafkaDlqPublisher
    source_topic: str
    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 10.0
    # sleep injetável: os testes verificam o backoff sem dormir de verdade.
    sleep: Callable[[float], None] = field(default=time.sleep)

    def handle(self, payload: bytes, key: bytes | None) -> HandleOutcome:
        # 1. Parse: erro aqui é terminal por definição — direto para a DLQ.
        try:
            event = RequestCreatedEvent.from_bytes(payload)
        except ValidationError as exc:
            logger.error("event_payload_invalid", error=str(exc)[:200])
            self._send_to_dlq(payload, key, error=f"payload inválido: {exc}", attempts=0)
            return HandleOutcome.SENT_TO_DLQ

        request_id = str(event.request_id)

        # 2. Processamento com retry + backoff exponencial e full jitter.
        #    attempt 0 é a tentativa original; retries são as seguintes.
        last_error: Exception | None = None
        attempts_made = 0
        for attempt in range(self.max_retries + 1):
            attempts_made = attempt + 1
            try:
                result = self.process.execute(event.request_id)
            except _RETRYABLE as exc:
                last_error = exc
                if attempt < self.max_retries:
                    delay = self._backoff_delay(attempt)
                    logger.warning(
                        "processing_retry",
                        request_id=request_id,
                        attempt=attempt + 1,
                        max_retries=self.max_retries,
                        delay_seconds=round(delay, 3),
                        error=type(exc).__name__,
                    )
                    self.sleep(delay)
                continue
            except DomainError as exc:
                # Regra violada não melhora com retry: DLQ imediata.
                last_error = exc
                break
            else:
                outcome = (
                    HandleOutcome.PROCESSED
                    if result.outcome.name == "PROCESSED"
                    else HandleOutcome.SKIPPED_DUPLICATE
                )
                logger.info(
                    "event_handled",
                    request_id=request_id,
                    outcome=result.outcome,
                    status=result.request.status,
                )
                return outcome

        # 3. Esgotou (ou erro terminal): marca FAILED para o cliente enxergar
        #    o desfecho no GET, e arquiva na DLQ para reprocessamento futuro.
        self._try_mark_failed(request_id)
        self._send_to_dlq(
            payload,
            key,
            error=f"{type(last_error).__name__}: {last_error}",
            attempts=attempts_made,
        )
        return HandleOutcome.SENT_TO_DLQ

    def _backoff_delay(self, attempt: int) -> float:
        """Exponencial com teto e FULL JITTER: sorteia entre 0 e o teto da
        janela. Sem jitter, N consumers que falharam juntos (MySQL caiu)
        voltariam a bater juntos, a cada janela — o jitter espalha a carga."""
        window = min(self.max_delay, self.base_delay * (2**attempt))
        return random.uniform(0, window)  # noqa: S311 — jitter, não criptografia

    def _try_mark_failed(self, request_id: str) -> None:
        """Best-effort: se o banco continua fora, a DLQ ainda preserva a
        mensagem — o FAILED pode ser aplicado num reprocessamento."""
        try:
            self.mark_failed.execute(UUID(request_id))
            logger.info("request_marked_failed", request_id=request_id)
        except Exception as exc:  # amplo de propósito: nada pode impedir a DLQ
            logger.warning(
                "mark_failed_unavailable", request_id=request_id, error=type(exc).__name__
            )

    def _send_to_dlq(
        self, payload: bytes, key: bytes | None, *, error: str, attempts: int
    ) -> None:
        # DlqPublishError propaga de propósito: se nem a DLQ aceita, o processo
        # deve MORRER sem commitar o offset (fail fast) — o orquestrador
        # reinicia e a mensagem é relida. Perder mensagem é pior que reiniciar.
        self.dlq.send(
            payload, key, error=error, attempts=attempts, source_topic=self.source_topic
        )
