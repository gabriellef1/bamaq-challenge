"""Caso de uso: criar uma solicitação (POST /requests)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.application.ports import EventPublisher, RequestRepository
from app.domain.entities import Request


@dataclass(frozen=True, slots=True)
class CreateRequest:
    """Orquestra: criar entidade -> persistir -> publicar evento.

    As dependências chegam por injeção (atributos do dataclass); o caso de uso
    só conhece as ports. Quem decide se `repository` é SQLAlchemy ou um dict em
    memória é o composition root — é isso que torna esta classe testável sem
    nenhum container no ar.
    """

    repository: RequestRepository
    publisher: EventPublisher

    def execute(self, customer_id: str, value: Decimal) -> Request:
        """Cria e devolve a solicitação, já persistida e anunciada.

        ORDEM IMPORTA: persistir ANTES de publicar. Se o publish falhar, existe
        uma linha PENDING no banco (estado honesto: "recebida, não disparada") e
        a API devolve 503. A ordem inversa seria pior: um evento circulando
        sobre uma solicitação que não existe — o consumer falharia sempre.
        Garantia total exigiria Transactional Outbox (ver README).
        """
        request = Request.create(customer_id=customer_id, value=value)
        self.repository.add(request)
        self.publisher.publish_created(request)
        return request
