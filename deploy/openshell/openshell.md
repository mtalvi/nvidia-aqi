# AIQ on NVIDIA OpenShell — Local Deployment Guide

Deploy the AIQ async research agent inside an NVIDIA OpenShell sandbox with
policy-enforced egress, Landlock filesystem isolation, and a full UI.

> **Prerequisite:** A working OpenShell gateway. Follow the
> [OpenShell README](../../OpenShell/README.md) to install the CLI and start a
> local Docker-backed gateway (`mise run gateway:docker`).

---

## 1. Architecture

```
┌────────────────────────────────────────────────────────┐
│  Host                                                  │
│                                                        │
│  ┌──────────┐       ┌──────────────────────────────┐   │
│  │ AIQ UI   │──────▶│ OpenShell Sandbox (container) │   │
│  │ :3000    │  :8000│                                │   │
│  └──────────┘  fwd  │  entrypoint.py                 │   │
│                     │    ├─ dask-scheduler            │   │
│                     │    ├─ dask-worker (--no-nanny)  │   │
│                     │    └─ uvicorn (FastAPI)         │   │
│                     │                                │   │
│                     │  Egress policy ──▶ NVIDIA API   │   │
│                     │                 ──▶ Tavily API  │   │
│                     └──────────────────────────────────┘   │
│                                                        │
│  OpenShell Gateway (Docker driver)                     │
└────────────────────────────────────────────────────────┘
```

| Component | Details |
|---|---|
| **Sandbox image** | `aiq-openshell:local` — Ubuntu 24.04, Python 3.12 venv, ChromaDB <1.0 |
| **Egress policy** | `deploy/openshell/policy-egress.yaml` — allows `integrate.api.nvidia.com:443` and `api.tavily.com:443` |
| **Port forward** | `--forward 8000` maps sandbox port 8000 to `127.0.0.1:8000` on the host |
| **UI** | `aiq-ui:local` — Next.js, connects to the backend via `BACKEND_URL` |

---

## 2. Quick Start

### 2.1 Build the sandbox image

```bash
cd /path/to/aiq
docker build -f Dockerfile.openshell --target openshell -t aiq-openshell:local .
```

### 2.2 Configure secrets

Create `.openshell.env` in the repo root (git-ignored):

```env
OPENSHELL=true
NVIDIA_API_KEY=nvapi-...
TAVILY_API_KEY=tvly-...
HTTP_PROXY=http://10.200.0.1:3128
HTTPS_PROXY=http://10.200.0.1:3128
CONFIG_FILE=/app/configs/config_web_default_llamaindex.yml
HOST=0.0.0.0
PORT=8000
PYTHONUNBUFFERED=1
PYTHONDONTWRITEBYTECODE=1
NAT_JOB_STORE_DB_URL=sqlite+aiosqlite:////sandbox/data/jobs.db
AIQ_CHROMA_DIR=/sandbox/data/chroma_data
AIQ_CHECKPOINT_DB=/sandbox/data/checkpoints.db
AIQ_SUMMARY_DB=sqlite+aiosqlite:////sandbox/data/summaries.db
```

> `OPENSHELL=true` gates sandbox-specific behaviour in shared code (see
> §5 — Change Isolation).

### 2.3 Start the OpenShell gateway

```bash
cd OpenShell
mise run gateway:docker          # first run compiles Rust — takes ~2 min
```

### 2.4 Create the sandbox

```bash
cd /path/to/aiq
openshell sandbox create \
  --from aiq-openshell:local \
  --forward 8000 \
  --policy deploy/openshell/policy-egress.yaml \
  --upload .openshell.env:/tmp/openshell.env \
  -- bash -lc 'export PATH="/app/.venv/bin:$PATH" && \
               set -a && source /tmp/openshell.env && set +a && \
               exec /app/.venv/bin/python /app/deploy/entrypoint.py'
```

Wait for `Uvicorn running on http://0.0.0.0:8000` in the output.

### 2.5 Pin DNS entries

OpenShell sandboxes use a network namespace that cannot resolve external
hostnames via Docker's embedded DNS. Pin them manually in the running
container:

```bash
CONTAINER=$(docker ps --format '{{.Names}}' | head -1)
docker exec "$CONTAINER" bash -c '
  echo "99.83.136.103 integrate.api.nvidia.com" >> /etc/hosts
  echo "3.226.38.126 api.tavily.com" >> /etc/hosts
'
```

> **Tip:** Resolve the IPs fresh with `dig +short integrate.api.nvidia.com`
> before pinning — they may change over time.

### 2.6 Verify

```bash
curl http://127.0.0.1:8000/health
# {"status":"healthy"}
```

### 2.7 (Optional) Start the UI

```bash
cd frontends/ui
docker build -f deploy/Dockerfile -t aiq-ui:local .

docker run -d --name aiq-ui \
  --network host \
  -e BACKEND_URL=http://127.0.0.1:8000 \
  -e REQUIRE_AUTH=false \
  aiq-ui:local
```

Open **http://localhost:3000** in a browser.

---

## 3. Testing AIQ Capabilities

### Shallow researcher

```bash
curl -X POST http://127.0.0.1:8000/v1/jobs/async/submit \
  -H 'Content-Type: application/json' \
  -d '{"input":"What is NVIDIA NIM?","agent_type":"shallow_researcher"}'
# → {"job_id":"...","status":"submitted",...}

# Poll status:
curl http://127.0.0.1:8000/v1/jobs/async/job/<JOB_ID>

# Get the report:
curl http://127.0.0.1:8000/v1/jobs/async/job/<JOB_ID>/report
```

### Deep researcher

```bash
curl -X POST http://127.0.0.1:8000/v1/jobs/async/submit \
  -H 'Content-Type: application/json' \
  -d '{"input":"Compare NVIDIA NIM and TorchServe architectures","agent_type":"deep_researcher"}'
```

### Knowledge ingestion (RAG)

```bash
# Create a collection
curl -X POST http://127.0.0.1:8000/v1/collections \
  -H 'Content-Type: application/json' \
  -d '{"name":"my_docs","description":"Test docs"}'

# Upload a document
curl -X POST http://127.0.0.1:8000/v1/collections/my_docs/documents \
  -F "files=@README.md"

# Check ingestion status
curl http://127.0.0.1:8000/v1/collections/my_docs/documents
```

### SSE streaming

```bash
curl -N http://127.0.0.1:8000/v1/jobs/async/job/<JOB_ID>/stream
```

---

## 4. Egress Policy Reference

`deploy/openshell/policy-egress.yaml` controls what the sandbox can access:

```yaml
filesystem_policy:
  read_only:  [/usr, /lib, /proc, /dev/urandom, /app, /etc, /var/log]
  read_write: [/sandbox, /tmp, /dev/null, /etc/hosts]

network_policies:
  aiq_nvidia_api:
    endpoints: [{ host: integrate.api.nvidia.com, port: 443 }]
    binaries:  [python, python3.12, dask-worker, dask-scheduler, curl]
  aiq_tavily:
    endpoints: [{ host: api.tavily.com, port: 443 }]
    binaries:  [python, python3.12, dask-worker, dask-scheduler, curl]
```

To add a new external service, append an entry under `network_policies` and
pin its IP in `/etc/hosts` (§2.5).

---

## 5. Change Isolation

All OpenShell-specific behaviour is gated behind the `OPENSHELL` environment
variable. When `OPENSHELL` is **not set** (i.e., standard Docker or OpenShift
deployments), the gated code paths are skipped entirely.

### OpenShell-only files (no impact on other deployments)

| File | Purpose |
|---|---|
| `Dockerfile.openshell` | BYOC image: Ubuntu 24.04, ChromaDB <1.0 (pure-Python SQLite for Landlock compatibility), `aiohttp` `trust_env=True` patches for proxy support |
| `deploy/openshell/policy-egress.yaml` | Egress and filesystem policy |
| `.openshell.env` | Sandbox environment variables and API keys |

### Gated changes in shared files

| File | Change | Gate |
|---|---|---|
| `deploy/entrypoint.py` | Adds `--no-nanny` to `dask-worker` (Landlock blocks POSIX semaphores used by Dask's Nanny) | `if os.environ.get("OPENSHELL")` |
| `sources/knowledge_layer/src/llamaindex/adapter.py` | Bootstraps ChromaDB `default_tenant` / `default_database` on first client creation (needed for ChromaDB <1.0 in the sandbox image) | `if os.environ.get("OPENSHELL")` |

### General bug fixes (safe for all deployments)

These were discovered during OpenShell testing but fix real issues in the
shared codebase. They are **not gated** because they improve all deployment
targets:

| File | Change | Why it's safe |
|---|---|---|
| `frontends/aiq_api/src/aiq_api/jobs/runner.py` | Dynamic LLM resolution: supports both `orchestrator_llm` (deep researcher) and `llm` (shallow researcher). Uses `inspect.signature` for agent instantiation instead of fragile try/except chain. | Fixes `AttributeError: 'ShallowResearchAgentConfig' object has no attribute 'orchestrator_llm'`. The new code is a strict superset of the old behaviour. |
| `frontends/aiq_api/src/aiq_api/routes/jobs.py` | Ensures the NAT `job_info` table exists at startup via idempotent `Base.metadata.create_all`. | `create_all` is a no-op when the table already exists. Prevents a race condition on fresh databases. |

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Cannot connect to host ... ssl:default [Temporary failure in name resolution]` | Sandbox network namespace cannot resolve external DNS | Pin IPs in `/etc/hosts` (§2.5) |
| `Connect call failed ... proxy=None` | `aiohttp` ignoring `HTTP_PROXY` | The `Dockerfile.openshell` patches `trust_env=True` into `langchain_nvidia_ai_endpoints` and `langchain_tavily`. Rebuild if missing. |
| `PermissionError: [Errno 13]` on Dask Nanny | Landlock blocks POSIX semaphores | Ensure `OPENSHELL=true` is set so `--no-nanny` is used |
| `error returned from database: (code: 14) unable to open database file` | ChromaDB ≥1.0 Rust SQLite backend fails under Landlock | The `Dockerfile.openshell` pins `chromadb>=0.5.0,<1.0.0`. Rebuild if using a newer image. |
| `Port 8000 already forwarded` | Stale sandbox | `openshell sandbox delete <name>` then recreate |
| `Text file busy` when restarting gateway | Stale `openshell-gateway` process holds the supervisor binary | Kill all `openshell-gateway` processes, remove `.cache/gateway-docker/supervisor/amd64/openshell-sandbox`, restart |

---

## 7. Cleanup

```bash
# Stop and remove the sandbox
openshell sandbox delete <sandbox-name>

# Stop the UI
docker stop aiq-ui && docker rm aiq-ui

# Stop the gateway
# Ctrl-C in the gateway terminal, or:
pkill -f openshell-gateway
```
