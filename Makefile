.DEFAULT_GOAL := help
.PHONY: help sync lint format types arch test check hooks fleet run

help:             ## list targets
	@awk 'BEGIN{FS=":.*## "} /^[a-z][a-zA-Z0-9_-]*:.*##/ {printf "  \033[32m%-10s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync:             ## install the environment
	uv sync

lint:             ## ruff check
	uv run ruff check src tests

format:           ## ruff format
	uv run ruff format src tests

types:            ## ty static type check
	uv run ty check

arch:             ## tach import contracts
	uv run tach check

test:             ## unit suite, 100 % coverage gate
	uv run pytest --cov -q

check: lint types arch test ## the full local gate

hooks:            ## install the git hooks
	uv run prek install

fleet:            ## list the projects under maintenance
	uv run esteward fleet

run:              ## dry run of one project: make run P=etrafilatura
	GH_TOKEN="$$(gh auth token)" uv run esteward run $(P)
