.PHONY: hard hard-fast test lint type security deps deploy e2e

hard: lint type test security deps deploy

hard-fast: lint test security deps

test:
	python manage.py test -v 2

lint:
	python -m pip install -q ruff
	python -m ruff check .

type:
	python -m pip install -q mypy django-stubs
	python -m mypy .

security:
	python -m pip install -q bandit
	python -m bandit -r . -x .venv,migrations,static,media

deps:
	python -m pip install -q pip-audit
	python -m pip_audit

deploy:
	python manage.py check --deploy