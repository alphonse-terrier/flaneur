# Flâneur MCP server — portable container image.
# Build:  docker build -t flaneur .
# Run:    docker run -p 8000:8000 -e PORT=8000 flaneur
FROM python:3.12-slim

# uv for fast, reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cached unless the lock/manifest changes).
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PORT=8000
EXPOSE 8000

# $PORT is honored by the server (Render/containers set it).
CMD ["uv", "run", "flaneur"]
