# =============================================================================
# Imagem única para os DOIS processos (API e consumer).
# Mesmo código, mesmos adapters — muda apenas o entrypoint no docker-compose.
# Isso é a arquitetura hexagonal na prática: dois "drivers" diferentes
# (HTTP e Kafka) acionando os mesmos casos de uso.
# =============================================================================

# ---------- Estágio 1: build das dependências --------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Instala num virtualenv isolado para copiar só ele ao estágio final:
# o compilador e os headers ficam para trás, reduzindo superfície de ataque.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --upgrade pip && pip install .

# ---------- Estágio 2: runtime -----------------------------------------------
FROM python:3.12-slim AS runtime

# SEGURANÇA: usuário não-root. Se a aplicação for comprometida, o invasor
# não tem privilégio para instalar pacotes nem escrever fora de /app.
RUN groupadd --gid 1000 appuser \
 && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin appuser

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY --chown=appuser:appuser src/ ./src/

USER appuser

EXPOSE 8000

# Default: API. O serviço `consumer` sobrescreve com o entrypoint do consumidor.
CMD ["python", "-m", "uvicorn", "app.composition.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
