"""Engine e fábrica de sessões SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.outbound.persistence.models import Base
from app.config.settings import Settings


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        # pool_pre_ping: testa a conexão antes de usá-la. Evita o clássico
        # "MySQL server has gone away" quando o banco recicla conexões ociosas.
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        pool_recycle=settings.db_pool_recycle_seconds,
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: depois do commit ainda lemos os atributos do
    # objeto para montar a resposta — sem isso, cada leitura pós-commit
    # dispararia um novo SELECT.
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_tables(engine: Engine) -> None:
    """Bootstrap do schema no startup, idempotente (CREATE TABLE IF NOT EXISTS).

    TRADE-OFF assumido para o desafio: em produção isto seria Alembic, com
    migrações versionadas e reversíveis — create_all não sabe ALTERAR tabela
    existente, só criar do zero. Documentado no README como evolução.
    """
    Base.metadata.create_all(engine)
