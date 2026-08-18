"""Loop de consumo Kafka: poll -> delega ao handler -> commit manual.

Deliberadamente burro: TODA decisão (retry, DLQ, idempotência) mora no
MessageHandler. Aqui só existe a mecânica de offsets — e é nela que vive a
garantia de entrega:

AT-LEAST-ONCE: `enable.auto.commit=false` e commit SÍNCRONO só DEPOIS do
handler devolver um veredito. Se o processo morrer no meio do processamento,
o offset não foi commitado e a mensagem será relida no restart — pode gerar
duplicata, e é exatamente por isso que o processamento é idempotente (duas
camadas, etapa c). A alternativa (auto-commit periódico) poderia commitar uma
mensagem AINDA NÃO processada e perdê-la numa queda: at-most-once, inaceitável
para uma solicitação financeira.
"""

from __future__ import annotations

from typing import Protocol

from app.adapters.inbound.messaging.handler import MessageHandler
from app.config.logging import get_logger

logger = get_logger(__name__)


class _MessageLike(Protocol):
    def error(self) -> object | None: ...
    def value(self) -> bytes: ...
    def key(self) -> bytes | None: ...
    def topic(self) -> str: ...
    def partition(self) -> int: ...
    def offset(self) -> int: ...


class _ConsumerLike(Protocol):
    def poll(self, timeout: float) -> _MessageLike | None: ...
    def commit(self, message: _MessageLike, asynchronous: bool) -> object: ...
    def close(self) -> None: ...


class KafkaConsumerLoop:
    def __init__(self, consumer: _ConsumerLike, handler: MessageHandler) -> None:
        self._consumer = consumer
        self._handler = handler
        self._running = False

    def stop(self) -> None:
        """Chamado pelo signal handler (SIGTERM/SIGINT): termina a mensagem
        atual e sai limpo — nunca abandona um processamento no meio."""
        self._running = False

    def run(self) -> None:
        self._running = True
        logger.info("consumer_loop_started")
        try:
            while self._running:
                message = self._consumer.poll(1.0)
                if message is None:
                    continue
                if message.error():
                    # Erro de transporte (rebalance, broker...): o cliente já
                    # faz retry interno; logamos e seguimos.
                    logger.warning("kafka_poll_error", error=str(message.error()))
                    continue

                outcome = self._handler.handle(message.value(), message.key())
                # Commit síncrono por mensagem: simplicidade e janela mínima de
                # reentrega. Trade-off: menos throughput que commit em lote a
                # cada N mensagens — para este volume, correção > vazão.
                self._consumer.commit(message, asynchronous=False)
                logger.info(
                    "offset_committed",
                    outcome=outcome,
                    partition=message.partition(),
                    offset=message.offset(),
                )
        finally:
            # DlqPublishError (ou qualquer erro inesperado) chega aqui SEM o
            # commit da mensagem atual: fail fast, o supervisor reinicia e a
            # mensagem é relida. close() sai do grupo de forma ordenada,
            # disparando o rebalance imediato em vez de esperar o timeout.
            self._consumer.close()
            logger.info("consumer_loop_stopped")
