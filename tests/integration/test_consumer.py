"""Consumer: idempotência, retry/backoff, DLQ e a mecânica de offsets.

A pergunta do desafio — "como evitar que a mesma mensagem seja processada
duas vezes?" — é respondida por estes testes em três níveis: duplicata
sequencial (máquina de estados), corrida entre instâncias (CAS) e a relação
processamento-antes-do-commit (at-least-once).
"""

from decimal import Decimal

import pytest
from tests.fakes import FakeKafkaProducer, FakeRequestCache, FakeRequestRepository

from app.adapters.inbound.messaging.handler import HandleOutcome, MessageHandler
from app.adapters.inbound.messaging.kafka_loop import KafkaConsumerLoop
from app.adapters.outbound.messaging.dlq_publisher import DlqPublishError, KafkaDlqPublisher
from app.adapters.shared.events import RequestCreatedEvent
from app.application.use_cases import (
    MarkRequestAsFailed,
    ProcessingOutcome,
    ProcessRequestEvent,
)
from app.domain.entities import Request
from app.domain.exceptions import InvalidRequestData
from app.domain.value_objects import RequestStatus

pytestmark = pytest.mark.integration


def make_handler(repo, cache=None, producer=None, process=None, max_retries=3):
    slept: list[float] = []
    cache = cache or FakeRequestCache()
    handler = MessageHandler(
        process=process or ProcessRequestEvent(repo, cache),
        mark_failed=MarkRequestAsFailed(repo, cache),
        dlq=KafkaDlqPublisher(producer or FakeKafkaProducer(), "request-processing-dlq"),
        source_topic="request-processing",
        max_retries=max_retries,
        base_delay=0.5,
        max_delay=10.0,
        sleep=slept.append,
    )
    return handler, slept


def event_for(request: Request) -> bytes:
    return RequestCreatedEvent.from_domain(request).to_bytes()


class TestIdempotency:
    def test_duplicata_sequencial_nao_reprocessa(self, repo, cache):
        """1º nível: a mensagem reentregue encontra status terminal e é pulada."""
        request = Request.create("1", Decimal("1500"))
        repo.add(request)
        handler, _ = make_handler(repo, cache)
        raw = event_for(request)

        assert handler.handle(raw, None) is HandleOutcome.PROCESSED
        first_pass = repo.rows[request.id]
        assert first_pass.status is RequestStatus.MANUAL_REVIEW

        assert handler.handle(raw, None) is HandleOutcome.SKIPPED_DUPLICATE
        assert repo.rows[request.id] == first_pass  # nada mudou, nem updated_at

    def test_corrida_entre_instancias_so_uma_vence(self, cache):
        """2º nível: dois consumers leram PENDING; o CAS deixa só um escrever."""

        class RacingRepo(FakeRequestRepository):
            def update_if_status(self, request, expected):
                # Simula o outro consumer commitando entre o get e o update.
                current = self.rows[request.id]
                if current.is_pending:
                    self.rows[request.id] = current.mark_as(RequestStatus.APPROVED)
                return False  # o UPDATE condicional viu rowcount 0

        repo = RacingRepo()
        request = Request.create("1", Decimal("100"))
        repo.add(request)

        use_case = ProcessRequestEvent(repo, cache)
        result = use_case.execute(request.id)
        assert result.outcome is ProcessingOutcome.SKIPPED_LOST_RACE

    def test_processamento_invalida_o_cache_depois_de_gravar(self, repo, cache):
        request = Request.create("1", Decimal("100"))
        repo.add(request)
        cache.set(request)  # simula um GET anterior que populou com PENDING
        handler, _ = make_handler(repo, cache)

        handler.handle(event_for(request), None)
        assert request.id not in cache.data          # invalidado (DELETE)
        assert ("del", request.id) in cache.ops
        assert cache.ops.index(("del", request.id)) > cache.ops.index(("set", request.id))


class TestRetryAndDlq:
    def test_payload_corrompido_vai_direto_para_dlq(self, repo):
        producer = FakeKafkaProducer()
        handler, slept = make_handler(repo, producer=producer)

        assert handler.handle(b"nao-e-json", b"key") is HandleOutcome.SENT_TO_DLQ
        assert slept == []                            # retry seria inútil
        sent = producer.sent[0]
        assert sent["topic"] == "request-processing-dlq"
        assert sent["value"] == b"nao-e-json"         # payload original intacto
        assert sent["headers"]["dlq.attempts"] == b"0"

    def test_erro_transitorio_recupera_com_backoff(self, cache):
        repo = FakeRequestRepository()
        request = Request.create("1", Decimal("100"))
        repo.add(request)
        repo.fail_times = 2                           # 2 falhas, depois volta
        handler, slept = make_handler(repo, cache)

        assert handler.handle(event_for(request), None) is HandleOutcome.PROCESSED
        assert repo.rows[request.id].status is RequestStatus.APPROVED
        assert len(slept) == 2
        # full jitter: cada delay cai na janela [0, min(max, base*2^n)]
        assert 0 <= slept[0] <= 0.5 and 0 <= slept[1] <= 1.0

    def test_esgotamento_envia_para_dlq_com_contagem_real(self, cache):
        repo = FakeRequestRepository()
        request = Request.create("1", Decimal("100"))
        repo.add(request)
        repo.fail_times = 99                          # banco fora "para sempre"
        producer = FakeKafkaProducer()
        handler, slept = make_handler(repo, cache, producer=producer)

        assert handler.handle(event_for(request), None) is HandleOutcome.SENT_TO_DLQ
        assert len(slept) == 3                        # max_retries
        assert producer.sent[0]["headers"]["dlq.attempts"] == b"4"  # 1 + 3

    def test_erro_de_dominio_marca_failed_sem_retry(self, repo, cache):
        """Bug de regra não melhora com retry: DLQ imediata, e o cliente
        enxerga FAILED no GET em vez de PENDING eterno."""
        request = Request.create("1", Decimal("100"))
        repo.add(request)

        class BuggyProcess:
            def execute(self, request_id):
                raise InvalidRequestData("invariante violada")

        producer = FakeKafkaProducer()
        handler, slept = make_handler(repo, cache, producer=producer, process=BuggyProcess())

        assert handler.handle(event_for(request), None) is HandleOutcome.SENT_TO_DLQ
        assert slept == []
        assert producer.sent[0]["headers"]["dlq.attempts"] == b"1"
        assert repo.rows[request.id].status is RequestStatus.FAILED

    def test_dlq_morta_propaga_para_derrubar_o_processo(self, repo):
        """Fail fast: sem DLQ não há onde arquivar — morrer sem commitar o
        offset garante a releitura após o restart."""
        handler, _ = make_handler(repo, producer=FakeKafkaProducer(dead=True))
        with pytest.raises(DlqPublishError):
            handler.handle(b"nao-e-json", None)


class FakeMessage:
    def __init__(self, value: bytes, offset: int):
        self._value, self._offset = value, offset

    def error(self):
        return None

    def value(self):
        return self._value

    def key(self):
        return None

    def topic(self):
        return "request-processing"

    def partition(self):
        return 0

    def offset(self):
        return self._offset


class FakeConsumer:
    def __init__(self, messages):
        self.messages = list(messages)
        self.committed: list[int] = []
        self.closed = False
        self.on_empty = None

    def poll(self, timeout):
        if not self.messages:
            if self.on_empty:
                self.on_empty()
            return None
        return self.messages.pop(0)

    def commit(self, message, asynchronous):
        assert asynchronous is False  # commit síncrono é parte do contrato
        self.committed.append(message.offset())

    def close(self):
        self.closed = True


class TestConsumerLoop:
    def test_processa_commita_em_ordem_e_fecha_no_stop(self, repo, cache):
        low = Request.create("1", Decimal("50"))
        high = Request.create("2", Decimal("5000"))
        repo.add(low)
        repo.add(high)
        handler, _ = make_handler(repo, cache)

        consumer = FakeConsumer([FakeMessage(event_for(low), 7), FakeMessage(event_for(high), 8)])
        loop = KafkaConsumerLoop(consumer, handler)
        consumer.on_empty = loop.stop

        loop.run()
        assert consumer.committed == [7, 8]
        assert consumer.closed
        assert repo.rows[low.id].status is RequestStatus.APPROVED
        assert repo.rows[high.id].status is RequestStatus.MANUAL_REVIEW

    def test_falha_no_handler_nao_commita_e_fecha_limpo(self, repo):
        """A garantia at-least-once vista do loop: exceção -> offset intacto."""
        handler, _ = make_handler(repo, producer=FakeKafkaProducer(dead=True))
        consumer = FakeConsumer([FakeMessage(b"nao-e-json", 42)])
        loop = KafkaConsumerLoop(consumer, handler)

        with pytest.raises(DlqPublishError):
            loop.run()
        assert consumer.committed == []               # nada foi commitado
        assert consumer.closed                        # mas saiu do grupo limpo
