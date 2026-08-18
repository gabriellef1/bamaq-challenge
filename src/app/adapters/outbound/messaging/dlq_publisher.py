"""Publicação na Dead Letter Queue (request-processing-dlq).

A DLQ é o "hospital" das mensagens: quando uma mensagem esgota os retries (ou
nem faz sentido tentar), ela vai para cá COM CONTEXTO, o offset é commitado e a
partição destrava. Sem DLQ, uma única mensagem venenosa (poison pill) pararia o
consumo da partição inteira para sempre.
"""

from __future__ import annotations

from datetime import UTC, datetime

from confluent_kafka import KafkaError

from app.application.exceptions import ApplicationError
from app.config.logging import get_logger

logger = get_logger(__name__)


class DlqPublishError(ApplicationError):
    """A própria DLQ falhou — o chamador decide (aqui: derrubar o processo)."""


class KafkaDlqPublisher:
    def __init__(self, producer: object, topic: str, flush_timeout: float = 5.0) -> None:
        self._producer = producer
        self._topic = topic
        self._flush_timeout = flush_timeout

    def send(
        self,
        payload: bytes,
        key: bytes | None,
        *,
        error: str,
        attempts: int,
        source_topic: str,
    ) -> None:
        """Reenvia o payload ORIGINAL, intacto, com o diagnóstico em headers.

        Payload no corpo + contexto nos headers é deliberado: um job de
        reprocessamento futuro consome a DLQ e republica o corpo como veio,
        sem precisar "desembrulhar" nenhum envelope. Os headers respondem à
        pergunta de plantão: por que esta mensagem está aqui?
        """
        headers = [
            ("dlq.error", error.encode("utf-8")[:500]),
            ("dlq.attempts", str(attempts).encode("utf-8")),
            ("dlq.source-topic", source_topic.encode("utf-8")),
            ("dlq.failed-at", datetime.now(UTC).isoformat().encode("utf-8")),
        ]
        delivery_error: list[object] = []

        def _on_delivery(err: object, _msg: object) -> None:
            if err is not None:
                delivery_error.append(err)

        try:
            self._producer.produce(  # type: ignore[attr-defined]
                self._topic, value=payload, key=key, headers=headers, on_delivery=_on_delivery
            )
            pending = self._producer.flush(self._flush_timeout)  # type: ignore[attr-defined]
        except (BufferError, KafkaError, OSError) as exc:
            raise DlqPublishError(f"falha ao publicar na DLQ: {exc}") from exc

        if pending > 0 or delivery_error:
            raise DlqPublishError("broker não confirmou a mensagem da DLQ")

        logger.warning("message_sent_to_dlq", topic=self._topic, error=error, attempts=attempts)
