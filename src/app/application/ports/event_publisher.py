"""Port de publicação de eventos."""

from __future__ import annotations

from typing import Protocol

from app.domain.entities import Request


class EventPublisher(Protocol):
    """Contrato para anunciar fatos do domínio ao mundo.

    O método fala em intenção de negócio ("uma solicitação foi criada"), não em
    mecânica de infra ("produza no tópico X com chave Y"). Tópico, partição,
    serialização e acks são decisões do adapter Kafka.
    """

    def publish_created(self, request: Request) -> None:
        """Anuncia que uma solicitação foi criada e aguarda processamento.

        Deve levantar `EventPublishError` se a entrega não puder ser confirmada —
        o caso de uso decide o que fazer (aqui: propagar; a API traduz em 503).
        """
        ...
