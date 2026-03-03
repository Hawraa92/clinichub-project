.PHONY: hard hard-fast test lint type security deps deploy e2e

hard: lint type test security deps deploy

hard-fast: lint test security deps

# ✅ مهم: نشغّل التست من جذر المشروع (.) حتى ما يصير تعارض tests package
test:
	python manage.py test . -v 2 --keepdb

lint:
	python -m pip install -q ruff
	python -m ruff check .

type:
	python -m pip install -q mypy django-stubs
	python -m mypy .

security:
	python -m pip install -q bandit
	python -m bandit -r . -x .venv,migrations,static,media,node_modules

deps:
	python -m pip install -q pip-audit
	python -m pip_audit

deploy:
	python manage.py check --deploy
	python manage.py makemigrations --check --dry-run

# (اختياري) مكان لتستات E2E لاحقاً
e2e:
	@echo "E2E tests placeholder"