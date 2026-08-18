"""Erros do domínio.

Estas exceções são a linguagem que o domínio usa para recusar operações
inválidas. Elas NÃO conhecem HTTP, Kafka ou banco: quem traduz um
`RequestNotFound` em "404" é o adapter de entrada, não o domínio.
"""

from __future__ import annotations


class DomainError(Exception):
    """Raiz de todos os erros de negócio.

    Ter uma base única permite que os adapters capturem `DomainError` e
    traduzam para o protocolo deles sem precisar listar cada subclasse.
    """


class InvalidRequestData(DomainError):
    """Os dados violam uma invariante da entidade (valor <= 0, cliente vazio...)."""


class InvalidStatusTransition(DomainError):
    """Tentativa de mudar o status por um caminho que a máquina de estados proíbe.

    É esta exceção que sustenta a idempotência do consumer: reprocessar uma
    solicitação já finalizada não "corrige" nada, é um erro de fluxo.
    """

    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(f"transição de status inválida: {current} -> {target}")


class RequestNotFound(DomainError):
    """Não existe solicitação com o identificador informado."""

    def __init__(self, request_id: object) -> None:
        self.request_id = request_id
        super().__init__(f"solicitação não encontrada: {request_id}")
