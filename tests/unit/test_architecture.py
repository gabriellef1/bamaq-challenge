"""Teste de fitness arquitetural.

A regra "o domínio não depende de infraestrutura" é fácil de escrever no README
e fácil de quebrar sem querer num pull request às 18h. Este teste transforma a
regra em algo que o CI reprova: ele lê a AST de cada módulo do domínio e falha
se encontrar um import proibido.

É o mesmo papel do ArchUnit no mundo Java.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

DOMAIN_DIR = Path(__file__).resolve().parents[2] / "src" / "app" / "domain"

#: Tudo que caracteriza infraestrutura: banco, web, fila, cache, serialização.
FORBIDDEN_PREFIXES = (
    "sqlalchemy",
    "pymysql",
    "fastapi",
    "starlette",
    "pydantic",
    "confluent_kafka",
    "kafka",
    "redis",
    "httpx",
    "requests",
    "app.adapters",
    "app.config",
    "app.composition",
)


def _imported_modules(source: str) -> list[str]:
    """Extrai os módulos importados percorrendo a AST (não por regex)."""
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.append(node.module)
    return modules


def _domain_modules() -> list[Path]:
    return sorted(p for p in DOMAIN_DIR.rglob("*.py") if p.name != "__init__.py")


@pytest.mark.unit
@pytest.mark.parametrize("module_path", _domain_modules(), ids=lambda p: p.name)
def test_domain_nao_importa_infraestrutura(module_path: Path) -> None:
    """Nenhum módulo do domínio pode importar uma tecnologia externa."""
    violations = [
        imported
        for imported in _imported_modules(module_path.read_text(encoding="utf-8"))
        if imported.startswith(FORBIDDEN_PREFIXES)
    ]
    assert not violations, (
        f"{module_path.name} importa infraestrutura: {violations}. "
        "O domínio só pode depender da biblioteca padrão e de si mesmo."
    )


@pytest.mark.unit
def test_dominio_nao_esta_vazio() -> None:
    """Protege o teste acima de passar por não ter encontrado arquivo nenhum."""
    assert len(_domain_modules()) >= 4
