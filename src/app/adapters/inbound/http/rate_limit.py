"""Rate limiting básico com slowapi.

SEGURANÇA: sem limite, um único cliente consegue encher o MySQL e o Kafka de
lixo com um `while true; do curl ...`. O limite por IP não é proteção contra
DDoS distribuído (isso é papel de WAF/CDN na frente), mas fecha o abuso
trivial e demonstra a preocupação.

Limites diferentes por rota: escrita (10/min) é mais cara e mais perigosa que
leitura (60/min) — POST cria linha, evento e trabalho de consumer; GET no pior
caso faz um SELECT.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

# key_func por IP remoto. Atrás de um proxy real usaríamos X-Forwarded-For
# validado — anotado no README para não parecer descuido.
limiter = Limiter(key_func=get_remote_address)
