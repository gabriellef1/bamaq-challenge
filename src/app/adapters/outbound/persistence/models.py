"""Modelo ORM da tabela `requests`.

Este é o "gêmeo de infraestrutura" da entidade de domínio. Mantê-los separados
(em vez de anotar a entidade com colunas SQLAlchemy) custa um mapper de ~20
linhas e compra o desacoplamento inteiro: o domínio não sabe que MySQL existe.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, DECIMAL, DateTime, Index, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RequestModel(Base):
    __tablename__ = "requests"

    # UUID como CHAR(36) legível. Alternativa: BINARY(16) ocupa menos e indexa
    # mais rápido, mas torna todo SELECT manual ilegível — para este volume,
    # a ergonomia de debug vale mais que os 20 bytes.
    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)

    customer_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # DECIMAL(15,2): dinheiro exato no banco, espelhando o Decimal do domínio.
    # FLOAT/DOUBLE no MySQL teria os mesmos erros binários que float no Python.
    value: Mapped[Decimal] = mapped_column(DECIMAL(15, 2), nullable=False)

    # VARCHAR e não ENUM do MySQL: adicionar um status novo vira INSERT normal,
    # não ALTER TABLE (que bloqueia a tabela). A validação de valores legais é
    # papel do domínio, não do banco.
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # DATETIME(6): microssegundos. Sempre UTC "naive" no banco; o fuso é
    # aplicado/removido no mapper — convenção única, zero ambiguidade.
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False)

    __table_args__ = (
        # Consulta operacional típica: "o que está preso em PENDING?"
        Index("ix_requests_status_created", "status", "created_at"),
        # Visão do cliente: "minhas solicitações mais recentes"
        Index("ix_requests_customer", "customer_id", "created_at"),
    )
