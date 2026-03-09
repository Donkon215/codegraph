.PHONY: install test lint format typecheck clean build help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Install package in editable mode with dev extras
	pip install -e ".[dev]"

test:  ## Run test suite with pytest
	pytest tests/ -v --tb=short

test-cov:  ## Run tests with coverage
	pytest tests/ -v --tb=short --cov=codegraph --cov-report=term-missing

lint:  ## Lint with ruff
	ruff check codegraph/ tests/

format:  ## Auto-format with black
	black codegraph/ tests/

typecheck:  ## Type-check with mypy
	mypy codegraph/

clean:  ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info .mypy_cache .pytest_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

build:  ## Build distribution packages
	python -m build
