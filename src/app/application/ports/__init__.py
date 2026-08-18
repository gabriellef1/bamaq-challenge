"""Ports (interfaces) que a aplicação exige da infraestrutura.

São `typing.Protocol` — tipagem ESTRUTURAL: um adapter implementa a port por
ter os métodos certos, sem herdar de nada. O mypy (strict) verifica a
conformidade em tempo de análise, onde erro de contrato deve ser pego.

Alternativa considerada: ABC. Daria erro em runtime ao instanciar um adapter
incompleto, mas obrigaria os adapters a importar e herdar da port — um
acoplamento nominal que o Protocol dispensa. Como o mypy roda no CI, a
verificação estática chega antes de qualquer runtime.
"""

from app.application.ports.cache import RequestCache
from app.application.ports.event_publisher import EventPublisher
from app.application.ports.repository import RequestRepository

__all__ = ["EventPublisher", "RequestCache", "RequestRepository"]
