FROM python:3.12-slim AS base

LABEL maintainer="codegraph contributors"
LABEL description="codegraph — AST graph system for AI agents"

WORKDIR /app

# Install only runtime dependencies first (cache layer)
COPY pyproject.toml readme.md ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir .

# Copy source code
COPY codegraph/ codegraph/

# Re-install in editable mode with source
RUN pip install --no-cache-dir -e .

# Default working directory for mounted projects
WORKDIR /project

ENTRYPOINT ["codegraph"]
CMD ["--help"]
