FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY listeners.py oauth_config.py oauth_server.py oauth_store.py oauth_admin.py ./

RUN groupadd --gid 10001 mcp && useradd --uid 10001 --gid mcp --no-create-home mcp && \
    mkdir -p /data && chown mcp:mcp /data

ENV MCP_OAUTH_DATABASE=/data/oauth.sqlite3
USER mcp

EXPOSE 8000 8001

CMD ["python", "server.py"]
