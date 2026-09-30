# MCP Server

A Python MCP server for Synology or local operation. It provides Exa web search and page retrieval, finance news, current time, and YouTube metadata, transcripts, and comments. The server listens on port `8000`.

## Local Python environment with venv

A virtual environment (`venv`) isolates this project's Python dependencies from other projects. Create it locally and **never commit it to GitHub**. Required packages are listed in `requirements.txt`.

Use Python 3.13 to match the Dockerfile.

### Windows (PowerShell)

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### Linux / macOS

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

After activation, `python` uses the virtual environment. Run `deactivate` to leave it. Recreate the environment on another computer and install packages from `requirements.txt`; this historical revision does not pin package versions.

## Start the server

For direct startup, set the authentication token in the process environment. PowerShell example:

```powershell
$env:MCP_AUTH_TOKEN = "<YOUR_TOKEN>"
python server.py
```

`server.py` does not automatically load `.env` during direct startup. Allowed hosts and origins in this historical revision use generic examples in `server.py`; configure them locally for your deployment.

## Docker

Create an ignored local `.env` file and replace the placeholder with your own token:

```dotenv
MCP_AUTH_TOKEN=<YOUR_TOKEN>
```

Then start:

```bash
docker compose up -d --build
```

Docker Compose reads the local `.env` and passes the token to the container.

## Git

`.gitignore` excludes `.venv/`, `venv/`, `env/`, `.env`, `.env.*`, Python caches, local IDE settings, secret files, logs, and local databases. `requirements.txt` is committed so dependencies can be installed again later. Keep real deployment settings and credentials in ignored local files.
