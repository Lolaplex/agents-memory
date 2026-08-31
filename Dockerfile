# syntax=docker/dockerfile:1
FROM python:3.11-slim

LABEL maintainer="Lolax <felix@lolax.dev>"
LABEL description="agents-memory cloud sync & remote MCP server"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AGENTS_MEMORY_PORT=8443 \
    AGENTS_MEMORY_HOST=0.0.0.0 \
    AGENTS_MEMORY_TOKEN=""

WORKDIR /app

# Install package
COPY pyproject.toml README.md LICENSE ./
COPY abi/ ./abi/
COPY src/ ./src/

RUN pip install --no-cache-dir -e .

# Persistent memory store volume
VOLUME ["/root/.agents/memory"]

EXPOSE 8443

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import httpx, os; token=os.environ.get('AGENTS_MEMORY_TOKEN',''); port=os.environ.get('AGENTS_MEMORY_PORT','8443'); headers={'Authorization': f'Bearer {token}'} if token else {}; r=httpx.get(f'http://127.0.0.1:{port}/health', headers=headers); exit(0 if r.status_code==200 else 1)"

ENTRYPOINT ["sh", "-c", "exec agents-memory remote serve --host ${AGENTS_MEMORY_HOST} --port ${AGENTS_MEMORY_PORT} --token \"${AGENTS_MEMORY_TOKEN}\""]
