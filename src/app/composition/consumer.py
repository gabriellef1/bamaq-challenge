"""Composition root do consumer — o segundo "driver" da mesma aplicação.

Compare com composition/api.py: os MESMOS adapters de saída (repositório,
cache), os MESMOS casos de uso — só muda o adapter de ENTRADA (Kafka em vez de
HTTP). É a prova concreta de que o hexágono tem dois lados plugáveis.

Rodar: python -m app.composition.consumer
"""

from __future__ import annotations

import signal
import sys
from types import FrameType

from confluent_kafka import Consumer

from app.adapters.inbound.messaging.handler import MessageHandler
from app.adapters.inbound.messaging.kafka_loop import KafkaConsumerLoop
from app.adapters.outbound.cache.redis_cache import RedisRequestCache, build_redis_client
from app.adapters.outbound.messaging.dlq_publisher import KafkaDlqPublisher
from app.adapters.outbound.messaging.kafka_publisher import build_producer
from app.adapters.outbound.persistence.database import build_engine, build_session_factory
from app.adapters.outbound.persistence.repository import SqlAlchemyRequestRepository
from app.application.use_cases import MarkRequestAsFailed, ProcessRequestEvent
from app.config.logging import configure_logging, get_logger
from app.config.settings import Settings, get_settings

logger = get_logger(__name__)


def build_consumer(settings: Settings) -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": settings.kafka_consumer_group,
            # O CORAÇÃO do at-least-once: nada de auto-commit. O offset só
            # avança quando o loop commita, DEPOIS de processar (ver kafka_loop).
            "enable.auto.commit": False,
            # Grupo novo começa do início do tópico: não perde eventos
            # publicados antes do primeiro deploy do consumer.
            "auto.offset.reset": "earliest",
        }
    )


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)

    # Mesmos adapters outbound da API — construídos aqui, injetados nos use cases.
    engine = build_engine(settings)
    repository = SqlAlchemyRequestRepository(build_session_factory(engine))
    cache = RedisRequestCache(
        client=build_redis_client(settings),
        ttl_seconds=settings.cache_ttl_seconds,
        key_prefix=settings.cache_key_prefix,
    )

    handler = MessageHandler(
        process=ProcessRequestEvent(repository=repository, cache=cache),
        mark_failed=MarkRequestAsFailed(repository=repository, cache=cache),
        dlq=KafkaDlqPublisher(build_producer(settings), settings.kafka_topic_dlq),
        source_topic=settings.kafka_topic_requests,
        max_retries=settings.kafka_max_retries,
        base_delay=settings.kafka_retry_base_delay_seconds,
        max_delay=settings.kafka_retry_max_delay_seconds,
    )

    consumer = build_consumer(settings)
    consumer.subscribe([settings.kafka_topic_requests])
    loop = KafkaConsumerLoop(consumer, handler)

    def _shutdown(signum: int, _frame: FrameType | None) -> None:
        logger.info("shutdown_signal_received", signal=signal.Signals(signum).name)
        loop.stop()

    # docker stop envia SIGTERM e espera 10s antes do SIGKILL: tratar o sinal
    # é o que garante "termina a mensagem atual, commita e sai" em deploys.
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("consumer_starting", topic=settings.kafka_topic_requests)
    try:
        loop.run()
    except Exception:
        logger.exception("consumer_crashed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
