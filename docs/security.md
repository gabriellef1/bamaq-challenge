# Segurança

Medidas implementadas, **onde** cada uma vive no código e o que ela previne.
A filosofia é defesa em profundidade: nenhuma camada confia que a anterior segurou tudo.

## 1. Validação rigorosa de entrada
**Onde:** `adapters/inbound/http/schemas.py` (borda) + `domain/entities.py` (invariantes)

- `extra="forbid"`: campo desconhecido → 422. Bloqueia *mass assignment* e denuncia contrato errado.
- `customer_id` com whitelist `[A-Za-z0-9_-]` e tamanho ≤ 64: sem espaços, unicode exótico ou quebras de linha (fecha *log injection*).
- `value` como `Decimal` direto do JSON (nunca passa por float), `gt=0`, `decimal_places=2` — `10.555` é **rejeitado**, não arredondado em silêncio.
- Defesa em profundidade: a entidade revalida tudo no `__post_init__`, porque consumer e repositório constroem `Request` sem passar pelo Pydantic.
- Path param `request_id` tipado como `UUID`: id malformado → 422 automático.

## 2. Nenhum secret no código ou no repositório
**Onde:** `config/settings.py` + `.gitignore`/`.dockerignore`

- Tudo via variável de ambiente (`pydantic-settings`), validado no boot; `.env` real fora do git **e** fora da imagem docker (`.dockerignore`).
- Senhas em `SecretStr`: não aparecem em `repr()`, `str()` nem log acidental — vazamento exige `.get_secret_value()`, auditável por grep.
- Senha URL-escapada na connection string (um `@` na senha não quebra nem vaza).
- Em produção, o `.env` seria substituído por secret manager (Vault/AWS SM) — o código não muda, só a origem das envs.

## 3. SQL injection: impossível por construção
**Onde:** `adapters/outbound/persistence/repository.py`

- Zero SQL raw, zero interpolação de string. Todo acesso usa o expression language do SQLAlchemy, que **sempre** gera placeholders parametrizados — o dado viaja separado do SQL e nunca é interpretado como código.
- Auditado: `grep -rE 'text\(|execute\(f"' src/` → vazio.

## 4. Containers non-root e imagem mínima
**Onde:** `Dockerfile`

- Runtime roda como `appuser` (uid 1000, shell `nologin`): comprometimento da app não dá privilégio de instalar pacotes nem escrever fora de `/app`.
- Multi-stage: compilador e headers ficam no estágio de build; a imagem final é `python:3.12-slim` + venv.
- MySQL: a aplicação usa o usuário `bamaq`, nunca root.

## 5. Rate limiting
**Onde:** `adapters/inbound/http/rate_limit.py` (slowapi)

- Por IP: 10/min na escrita, 60/min na leitura (assimétrico: POST cria linha + evento + trabalho de consumer; GET é um SELECT).
- Não é proteção anti-DDoS distribuído (papel de WAF/CDN) — fecha o abuso trivial de um único cliente.
- Limitação conhecida: storage in-memory conta por réplica; multi-réplica pediria storage Redis (suportado pelo slowapi).

## 6. Limite de tamanho de corpo (anti-DoS barato)
**Onde:** `adapters/inbound/http/middleware.py`

- Corpo > 16 KB → 413 **antes** de qualquer parse (payload legítimo tem ~60 bytes; folga de 250×).
- Duas camadas: `Content-Length` declarado é rejeitado de graça; corpo *chunked* é contado byte a byte e cortado se estourar — omitir o header não escapa do limite.

## 7. Headers defensivos e respostas que não vazam
**Onde:** `middleware.py` + `errors.py`

- `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, `X-Frame-Options: DENY` em toda resposta, inclusive erros.
- `--no-server-header` no uvicorn: sem fingerprinting de servidor/versão.
- Erros de infraestrutura devolvem mensagem genérica ao cliente e detalhe real só no log — mensagem de driver de banco em resposta HTTP é vazamento de topologia.

## 8. Logs sem dados sensíveis
**Onde:** `config/logging.py`

- Política: loga-se **identificadores** (request_id, status, outcome), nunca conteúdo de negócio (value, customer_id).
- Rede de segurança automática: processor do structlog redige `value`, `customer_id`, `password`, `secret`, `authorization` → `[REDACTED]` mesmo que alguém os passe por engano.

## 9. Análise estática contínua
- Ruff com as regras `S` (flake8-bandit) no lint padrão: uso de `assert` fora de teste, subprocess inseguro, random criptográfico etc. são pegos no CI.
- Teste de fitness arquitetural: `domain/` e `application/` não podem importar infraestrutura (lido por AST — quebra o build se violado).

## Débitos assumidos (e onde dói)
Anotados de propósito — segurança honesta inclui saber o que ficou de fora:

| Débito | Risco | Mitigação em produção |
|---|---|---|
| Kafka em PLAINTEXT | sniffing/spoofing na rede interna | SASL/SCRAM + TLS entre brokers e clients |
| Redis sem senha no compose local | leitura do cache por vizinho de rede | `requirepass`/ACL + TLS (suportado via `REDIS_PASSWORD`) |
| Sem autenticação na API | qualquer um cria solicitações | JWT/OAuth2 no gateway ou `Depends` de auth por rota |
| `/docs` aberto | enumeração da API | fechar ou proteger em produção (`docs_url=None` via env) |
| Rate limit por IP direto | atrás de proxy, todos os clientes viram 1 IP | `X-Forwarded-For` validado do proxy confiável |
