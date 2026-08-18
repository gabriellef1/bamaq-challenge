"""Adapter: implementação Kafka (confluent-kafka) da port EventPublisher."""

from __future__ import annotations

from typing import Protocol

from confluent_kafka import KafkaError, Message, Producer

from app.adapters.shared.events import RequestCreatedEvent
from app.application.exceptions import EventPublishError
from app.config.logging import get_logger
from app.config.settings import Settings
from app.domain.entities import Request

logger = get_logger(__name__)


class _ProducerLike(Protocol):
    """Superfície mínima do Producer que usamos — permite injetar um dublê nos
    testes sem subir broker (o Producer real não tem interface própria)."""

    def produce(self, topic: str, value: bytes, key: bytes, on_delivery: object) -> None: ...
    def flush(self, timeout: float) -> int: ...


def build_producer(settings: Settings) -> Producer:
    return Producer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            # acks=all: o broker só confirma depois que TODAS as réplicas in-sync
            # gravaram. Com 1 broker é igual a acks=1, mas o dia em que o cluster
            # crescer para 3, a durabilidade já está certa sem mudar código.
            "acks": "all",
            # Producer idempotente: retries internos do próprio Kafka não geram
            # mensagem duplicada (o broker deduplica por sequence number).
            "enable.idempotence": True,
            # Falhar rápido: melhor um 503 em 5s do que uma requisição pendurada.
            "delivery.timeout.ms": int(settings.kafka_publish_timeout_seconds * 1000),
            "socket.timeout.ms": 3000,
        }
    )


class KafkaEventPublisher:
    def __init__(self, producer: _ProducerLike, topic: str, flush_timeout: float = 5.0) -> None:
        self._producer = producer
        self._topic = topic
        self._flush_timeout = flush_timeout

    def publish_created(self, request: Request) -> None:
        """Publica e ESPERA a confirmação do broker (flush síncrono).

        Trade-off deliberado: perde-se o throughput do batching assíncrono,
        ganha-se a garantia de que o 201 devolvido ao cliente significa "o
        evento ESTÁ no broker". Para uma API transacional, essa honestidade
        vale mais que os poucos ms de latência. Alto volume pediria fire-and-
        forget + Transactional Outbox para reconciliar.

        A CHAVE da mensagem é o request_id: eventos da mesma solicitação caem
        sempre na mesma partição, logo são consumidos NA ORDEM. Entre
        solicitações diferentes a ordem não importa.
        """
        event = RequestCreatedEvent.from_domain(request)
        delivery_error: list[KafkaError] = []

        def _on_delivery(err: KafkaError | None, _msg: Message) -> None:
            if err is not None:
                delivery_error.append(err)

        try:
            self._producer.produce(
                self._topic,
                value=event.to_bytes(),
                key=str(request.id).encode("utf-8"),
                on_delivery=_on_delivery,
            )
            pending = self._producer.flush(self._flush_timeout)
        except (BufferError, KafkaError, OSError) as exc:
            logger.error("kafka_publish_failed", request_id=str(request.id), error=str(exc))
            raise EventPublishError(f"falha ao publicar evento: {exc}") from exc

        if pending > 0:
            logger.error("kafka_publish_timeout", request_id=str(request.id))
            raise EventPublishError("broker não confirmou a entrega dentro do timeout")
        if delivery_error:
            logger.error(
                "kafka_delivery_failed",
                request_id=str(request.id),
                error=str(delivery_error[0]),
            )
            raise EventPublishError(f"broker recusou a mensagem: {delivery_error[0]}")

        logger.info("event_published", request_id=str(request.id), topic=self._topic)
