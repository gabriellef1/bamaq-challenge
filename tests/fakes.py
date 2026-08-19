"""Dublês in-memory das ports — compartilhados por toda a suíte.

São FAKES (implementações funcionais simplificadas), não mocks de framework:
implementam as ports por tipagem estrutural, exatamente como os adapters
reais. Um teste que passa contra estes fakes exercita o MESMO contrato que a
produção usa — se o contrato mudar, fakes e adapters quebram juntos.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import OperationalError

from app.domain.entities import Request
from app.domain.value_objects import RequestStatus


class FakeRequestRepository:
    """Implementa RequestRepository sobre um dict, com o mesmo CAS do MySQL."""

    def __init__(self) -> None:
        self.rows: dict[UUID, Request] = {}
        self.fail_times = 0  # injeta N falhas transitórias de "banco fora"
        self.get_calls = 0

    def add(self, request: Request) -> None:
        self.rows[request.id] = request

    def get(self, request_id: UUID) -> Request | None:
        self.get_calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise OperationalError("conn", None, Exception("mysql down"))
        return self.rows.get(request_id)

    def update_if_status(self, request: Request, expected: RequestStatus) -> bool:
        current = self.rows.get(request.id)
        if current is None or current.status is not expected:
            return False
        self.rows[request.id] = request
        return True


class FakeRequestCache:
    """Implementa RequestCache e grava a sequência de operações para asserção."""

    def __init__(self) -> None:
        self.data: dict[UUID, Request] = {}
        self.ops: list[tuple[str, UUID]] = []

    def get(self, request_id: UUID) -> Request | None:
        self.ops.append(("get", request_id))
        return self.data.get(request_id)

    def set(self, request: Request) -> None:
        self.ops.append(("set", request.id))
        self.data[request.id] = request

    def invalidate(self, request_id: UUID) -> None:
        self.ops.append(("del", request_id))
        self.data.pop(request_id, None)


class FakeEventPublisher:
    def __init__(self) -> None:
        self.published: list[UUID] = []

    def publish_created(self, request: Request) -> None:
        self.published.append(request.id)


class FakeKafkaProducer:
    """Dublê do Producer do confluent-kafka (produce/flush) para DLQ e publisher."""

    def __init__(self, dead: bool = False) -> None:
        self.sent: list[dict] = []
        self.dead = dead

    def produce(self, topic, value=None, key=None, headers=None, on_delivery=None):
        if self.dead:
            on_delivery(RuntimeError("broker down"), None)
            return
        self.sent.append(
            {"topic": topic, "value": value, "key": key, "headers": dict(headers or [])}
        )
        on_delivery(None, None)

    def flush(self, timeout: float) -> int:
        return 0
