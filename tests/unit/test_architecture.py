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

SRC = Path(__file__).resolve().parents[2] / "src" / "app"

#: Camadas internas do hexágono: ambas proibidas de conhecer infraestrutura.
#: `application` pode importar `domain`; `domain` não importa ninguém.
INNER_LAYERS = (SRC / "domain", SRC / "application")

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


def _inner_modules() -> list[Path]:
    return sorted(
        p for layer in INNER_LAYERS for p in layer.rglob("*.py") if p.name != "__init__.py"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "module_path", _inner_modules(), ids=lambda p: f"{p.parent.parent.name}/{p.name}"
)
def test_camadas_internas_nao_importam_infraestrutura(module_path: Path) -> None:
    """Nenhum módulo de domain/ ou application/ pode importar tecnologia externa."""
    violations = [
        imported
        for imported in _imported_modules(module_path.read_text(encoding="utf-8"))
        if imported.startswith(FORBIDDEN_PREFIXES)
    ]
    assert not violations, (
        f"{module_path.name} importa infraestrutura: {violations}. "
        "domain/ e application/ só dependem da stdlib e das camadas internas."
    )


@pytest.mark.unit
def test_camadas_internas_nao_estao_vazias() -> None:
    """Protege o teste acima de passar por não ter encontrado arquivo nenhum."""
    assert len(_inner_modules()) >= 8
