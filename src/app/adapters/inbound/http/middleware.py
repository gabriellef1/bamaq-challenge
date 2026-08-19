"""Middlewares de segurança da borda HTTP.

Implementados como ASGI puro (funções sobre scope/receive/send) em vez de
BaseHTTPMiddleware: o wrapper do Starlette bufferiza a resposta inteira e cria
uma task por requisição — para middlewares triviais como estes, ASGI puro tem
custo praticamente zero e nenhuma surpresa com streaming.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

_Scope = dict[str, Any]
_Message = dict[str, Any]
_Receive = Callable[[], Awaitable[_Message]]
_Send = Callable[[_Message], Awaitable[None]]
_ASGIApp = Callable[[_Scope, _Receive, _Send], Awaitable[None]]


class BodySizeLimitMiddleware:
    """Rejeita corpos maiores que `max_bytes` com 413 ANTES de ler o payload.

    Sem isto, um cliente pode enviar um JSON de 500 MB e o servidor vai
    alocá-lo inteiro em memória antes mesmo do Pydantic dizer "422" — vetor
    barato de negação de serviço. O payload legítimo deste sistema tem ~60
    bytes; o limite default (16 KB) dá folga de 250x.

    Estratégia em duas camadas:
    1. Content-Length declarado acima do limite -> 413 imediato, custo zero.
    2. Corpo chunked (sem Content-Length) -> conta os bytes conforme chegam e
       corta a conexão se estourar — cliente malicioso não escapa omitindo o
       header.
    """

    def __init__(self, app: _ASGIApp, max_bytes: int = 16 * 1024) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: _Scope, receive: _Receive, send: _Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_bytes:
                    await _send_json(send, 413, {"detail": "payload excede o tamanho máximo"})
                    return
            except ValueError:
                await _send_json(send, 400, {"detail": "Content-Length inválido"})
                return

        received = 0

        async def limited_receive() -> _Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Sinaliza desconexão para a app parar de ler; a resposta
                    # 413 já não é garantida aqui (a app pode ter começado a
                    # responder), então derrubar é o comportamento seguro.
                    return {"type": "http.disconnect"}
            return message

        await self.app(scope, limited_receive, send)


class SecurityHeadersMiddleware:
    """Headers defensivos em toda resposta.

    Para uma API JSON os relevantes são poucos, mas baratos:
    - X-Content-Type-Options: nosniff — impede o navegador de "adivinhar" que
      um JSON é HTML e executá-lo (mata uma classe de XSS refletido via API).
    - Cache-Control: no-store — status de solicitação é dado dinâmico e
      potencialmente sensível; proxies e navegadores não devem guardar cópia.
      (O cache do sistema é o Redis, controlado por nós — não o do cliente.)
    - X-Frame-Options: DENY — API não é página; se algum dia servir HTML de
      erro, ninguém a emoldura num iframe de clickjacking.
    """

    _HEADERS: ClassVar[tuple[tuple[bytes, bytes], ...]] = (
        (b"x-content-type-options", b"nosniff"),
        (b"cache-control", b"no-store"),
        (b"x-frame-options", b"DENY"),
    )

    def __init__(self, app: _ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: _Scope, receive: _Receive, send: _Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: _Message) -> None:
            if message["type"] == "http.response.start":
                existing = {name for name, _ in message.setdefault("headers", [])}
                message["headers"].extend(
                    (name, value) for name, value in self._HEADERS if name not in existing
                )
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def _send_json(send: _Send, status: int, payload: dict[str, str]) -> None:
    body = json.dumps(payload).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"x-content-type-options", b"nosniff"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
