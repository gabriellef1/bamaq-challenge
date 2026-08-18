# Atalhos do dia a dia. `make help` lista tudo.
.DEFAULT_GOAL := help
.PHONY: help setup up down logs ps test test-cov lint fmt typecheck diagram clean

help:  ## Lista os comandos disponíveis
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	 | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup:  ## Cria o .env a partir do .env.example e instala as deps de dev
	@test -f .env || (cp .env.example .env && echo "  .env criado — revise as senhas")
	python -m pip install -e ".[dev]"

up:  ## Sobe a stack completa (MySQL, Kafka, Redis, API, consumer)
	docker compose up -d --build

down:  ## Derruba a stack e apaga os volumes
	docker compose down -v

logs:  ## Segue os logs da API e do consumer
	docker compose logs -f api consumer

ps:  ## Estado dos containers
	docker compose ps

test:  ## Roda os testes que não exigem infra (unit + integration)
	python -m pytest -m "not e2e"

test-cov:  ## Testes com relatório de cobertura
	python -m pytest -m "not e2e" --cov --cov-report=term-missing

lint:  ## Análise estática (ruff)
	python -m ruff check src tests

fmt:  ## Formata o código
	python -m ruff format src tests && python -m ruff check --fix src tests

typecheck:  ## Checagem de tipos (mypy strict)
	python -m mypy

diagram:  ## Reexporta docs/architecture.mmd para SVG e PNG
	npx -y @mermaid-js/mermaid-cli -i docs/architecture.mmd -o docs/architecture.svg
	npx -y @mermaid-js/mermaid-cli -i docs/architecture.mmd -o docs/architecture.png -s 2

clean:  ## Remove caches e artefatos de teste
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov
