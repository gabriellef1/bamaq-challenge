"""Configuração da aplicação — 100% via variáveis de ambiente.

Nenhum valor sensível vive no código: `pydantic-settings` lê do ambiente (e do
`.env` em desenvolvimento) e valida tipo e presença NA PARTIDA. Uma variável
obrigatória faltando derruba o processo no boot com mensagem clara — muito
melhor do que um `KeyError` no meio de uma requisição às 3h da manhã.
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # o .env tem vars de outros serviços (compose); ignore-as
    )

    # ---- Aplicação ----------------------------------------------------------
    app_name: str = "bamaq-requests"
    app_env: str = "local"
    log_level: str = "INFO"

    # ---- MySQL --------------------------------------------------------------
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_database: str = "bamaq"
    mysql_user: str = "bamaq"
    # SecretStr: o valor não aparece em repr(), str() nem em log acidental.
    # Só sai via .get_secret_value(), o que torna o vazamento auditável no grep.
    mysql_password: SecretStr = Field(default=...)
    db_pool_size: int = 10
    db_pool_max_overflow: int = 5
    db_pool_recycle_seconds: int = 1800

    # ---- Kafka --------------------------------------------------------------
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic_requests: str = "request-processing"
    kafka_topic_dlq: str = "request-processing-dlq"
    kafka_consumer_group: str = "request-processor"
    kafka_max_retries: int = 3
    kafka_retry_base_delay_seconds: float = 0.5
    kafka_retry_max_delay_seconds: float = 10.0
    kafka_publish_timeout_seconds: float = 5.0

    # ---- Redis --------------------------------------------------------------
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: SecretStr = SecretStr("")
    cache_ttl_seconds: int = 300
    cache_key_prefix: str = "request"

    # ---- API ----------------------------------------------------------------
    api_host: str = "0.0.0.0"  # noqa: S104 — bind em todas as interfaces é intencional em container
    api_port: int = 8000
    rate_limit_create: str = "10/minute"
    rate_limit_read: str = "60/minute"
    # Teto do corpo HTTP. O payload legítimo tem ~60 bytes; 16 KB é folga de
    # sobra e ainda barra o JSON-de-500MB como vetor de negação de serviço.
    max_body_bytes: int = 16_384

    @property
    def database_url(self) -> str:
        """URL SQLAlchemy do MySQL. A senha é URL-escapada — um `@` ou `/` na
        senha quebraria o parse da URL de forma silenciosa e difícil de debugar."""
        password = quote_plus(self.mysql_password.get_secret_value())
        return (
            f"mysql+pymysql://{self.mysql_user}:{password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            "?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    """Singleton preguiçoso: importar este módulo não exige ambiente configurado;
    só a primeira CHAMADA valida. Facilita testes (cache_clear + env fake)."""
    return Settings()
