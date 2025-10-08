.PHONY: install-dev install-dev-deps clean test lint format

install-dev:
	pip install -e .

install-dev-deps:
	pip install -e ".[dev]"

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

test:
	pytest

lint:
	flake8 awxmigration/awxtower/ awxmigration/utils/
	mypy awxmigration/awxtower/ awxmigration/utils/
	black --check awxmigration/awxtower/ awxmigration/utils/
	isort --check-only awxmigration/awxtower/ awxmigration/utils/

format:
	black awxmigration/awxtower/ awxmigration/utils/
	isort awxmigration/awxtower/ awxmigration/utils/ 