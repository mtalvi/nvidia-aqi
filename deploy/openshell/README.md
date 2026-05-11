# AI-Q on NVIDIA OpenShell (local BYOC)

This directory documents running the **AI-Q async API** (Dask + `aiq_api` + `deploy/entrypoint.py`) inside an [OpenShell](https://github.com/NVIDIA/OpenShell) sandbox with explicit egress policy.

## Prerequisites

- Docker (OpenShell builds BYOC images into the local daemon).
- OpenShell CLI ([install](https://github.com/NVIDIA/OpenShell#install)).
- A checkout of this repository.
- API keys in the environment or in a file you pass at runtime (see below).

## 1. Start a local OpenShell gateway

From your clone of the OpenShell repository (for example `./OpenShell` next to this repo):

```bash
cd OpenShell
mise install   # first time only
mise run gateway:docker
```

Leave that process running. In another terminal, confirm the CLI sees the gateway:

```bash
openshell status
```

`mise run gateway:docker` already registers the **`docker-dev`** gateway. You usually only need to mark it active:

```bash
openshell gateway select docker-dev
openshell status
```

If you started the gateway some other way and have no registration yet, add it once, then select:

```bash
openshell gateway add http://127.0.0.1:18080 --local --name docker-dev
openshell gateway select docker-dev
```

The bundled Docker gateway defaults to **127.0.0.1:18080** and the gateway name **`docker-dev`** (see `OpenShell/tasks/scripts/gateway-docker.sh`). Override with `OPENSHELL_SERVER_PORT` / `OPENSHELL_DOCKER_GATEWAY_NAME` if needed.

## 2. Build the AI-Q OpenShell image (optional)

OpenShell can build from `Dockerfile.openshell` at the **repository root** (parent of this folder is the build context):

```bash
cd /path/to/aiq
docker build -f Dockerfile.openshell --target openshell -t aiq-openshell:local .
```

Or let `openshell sandbox create --from Dockerfile.openshell` build it automatically.

## 3. Create the sandbox

Run from the **AI-Q repository root** so `--from Dockerfile.openshell` resolves correctly.

**Secrets:** the local `docker-dev` gateway usually does **not** copy your host shell exports into the container. Prefer **Option B** (upload + `source`) so `NVIDIA_API_KEY` / `TAVILY_API_KEY` exist in the sandbox process.

### Option B — upload `.openshell.env` (recommended for `docker-dev`)

1. From the repo root, create a gitignored env file (never commit it):

   ```bash
   cd /path/to/aiq
   cp deploy/openshell/.openshell.env.example .openshell.env
   # Edit .openshell.env: set NVIDIA_API_KEY=... and TAVILY_API_KEY=... (no quotes unless your key needs them)
   ```

2. Stop any old forward on port `8000` if needed (`openshell forward stop 8000 <old-sandbox>`), then create the sandbox:

   ```bash
   openshell sandbox create \
     --from Dockerfile.openshell \
     --forward 8000 \
     --upload .openshell.env:/tmp/openshell.env \
     -- bash -lc 'set -a && source /tmp/openshell.env && set +a && exec /app/.venv/bin/python /app/deploy/entrypoint.py'
   ```

   `set -a` exports every variable defined in the file so child processes (Dask, uvicorn) inherit them.

### Option A — host exports (only if your gateway injects them)

```bash
cd /path/to/aiq
export NVIDIA_API_KEY=...
export TAVILY_API_KEY=...

openshell sandbox create \
  --from Dockerfile.openshell \
  --forward 8000 \
  -- /app/.venv/bin/python /app/deploy/entrypoint.py
```

Prefer **`/app/.venv/bin/python`** so the first process uses the venv (OpenShell may put system `python` earlier on `PATH`). `deploy/entrypoint.py` also **re-execs** into `/app/.venv/bin/python` when it detects system Python, so `python /app/deploy/entrypoint.py` works after an image rebuild that includes this script.

OpenShell runs your command **after `--`**; it replaces the image `ENTRYPOINT` (see OpenShell BYOC docs).

Then on the host:

```bash
curl -sS http://127.0.0.1:8000/v1/jobs/async/agents
```

## 4. Apply egress policy

Default sandboxes restrict outbound traffic. After the sandbox is created, allow NVIDIA NIM and Tavily from **`/app/.venv/bin/python`**:

```bash
openshell policy set <sandbox-name> --policy deploy/openshell/policy-egress.example.yaml --wait
```

Reconnect or restart the workload if your gateway requires it; then retry API calls.

Extend the YAML if your `CONFIG_FILE` adds hosts (Serper, internal RAG, Hugging Face, etc.).

## 5. Submit a long-running async job

See [frontends/aiq_api/README.md](../../frontends/aiq_api/README.md) for `POST /v1/jobs/async/submit` and SSE URLs. Use `agent_type` **`deep_researcher`** for the long research path.

## Troubleshooting

### `PermissionError` on `multiprocessing.SemLock` (Dask Nanny)

Dask’s **Nanny** uses POSIX semaphores; some sandboxes block them. `deploy/entrypoint.py` passes **`--no-nanny`** to `dask-worker` so a single-process worker runs (fine for local async jobs).

### `NAT_JOB_STORE_DB_URL must be set` / wrong `CONFIG_FILE`

OpenShell may not pass **image `ENV`** into your process. `deploy/entrypoint.py` **re-exports** `CONFIG_FILE`, `NAT_JOB_STORE_DB_URL`, and related paths into `os.environ` before starting `start_web.py` so they match Docker Compose behavior.

### `FileNotFoundError: ... 'dask-scheduler'`

The OpenShell image uses `uv pip install --no-deps` for workspace packages, which **does not** pull `aiq_api`’s dependencies. [`Dockerfile.openshell`](../../Dockerfile.openshell) adds an explicit `dask[distributed]` install so `deploy/entrypoint.py` can spawn `dask-scheduler` / `dask-worker`. Rebuild the image after pulling the latest Dockerfile.

### `uv sync` / Docker build fails downloading wheels from PyPI (`operation timed out`)

The OpenShell Dockerfile sets **`UV_HTTP_TIMEOUT=300`** to tolerate slow mirrors. If the build host still cannot reach **`files.pythonhosted.org`**, fix host DNS (see below), use a corporate **HTTP(S) proxy** for Docker builds, or try **`docker build --network=host`** when policy allows.

The default lockfile no longer installs **`nvidia-nat[telemetry]`** (that stack pulled **`debugpy`** and other notebook tooling). To restore it in a custom image, add **`--extra nat-telemetry`** to **`uv sync`** in your Dockerfile (the lockfile already includes that extra).

### `curl: (52) Empty reply from server` on the forwarded port

**Host port must match the app port inside the container.** OpenShell forwards `localhost:<N>` on your machine to **`127.0.0.1:<N>` inside the sandbox** (same number). AI-Q’s web server defaults to **`PORT=8000`**, so use **`--forward 8000`** (and `curl http://127.0.0.1:8000/...`). If you forward **`8001`**, nothing is listening on container port **8001**, and `curl` often sees an empty reply.

If the host port matches `PORT` and it still fails, confirm the app responds inside the sandbox (**`-n` / `--name`**, not a positional name before `--`):

```bash
openshell sandbox exec -n <sandbox-name> -- curl -sS -v http://127.0.0.1:8000/health
```

If that returns `200 OK` but the host forward fails, restart the forward (`openshell forward stop` / `forward start` with `--background`). To expose the API on host port **8001** instead, set **`PORT=8001`** in `.openshell.env` (so uvicorn binds to **8001** in the container) and use **`--forward 8001`**; the forwarded number must always match **`PORT`**.

### `/home/sandbox/.profile: Permission denied`

Usually a **harmless** warning from the login shell when the supervisor starts your command. If the app then exits with another error, fix that primary error first.

### Jobs fail with `Temporary failure in name resolution` / `ClientConnectorDNSError` for `integrate.api.nvidia.com`

The egress policy allows **TCP 443** to that host, but the client must still **resolve the hostname** inside the sandbox. If DNS is broken or unreachable from the sandbox network namespace, you see this error **before** any HTTPS policy check.

Diagnose (replace `<sandbox-name>`):

```bash
openshell sandbox exec -n <sandbox-name> -- cat /etc/resolv.conf
openshell sandbox exec -n <sandbox-name> -- getent hosts integrate.api.nvidia.com || true
```

If **`nameserver 127.0.0.11`** appears (Docker’s embedded DNS), resolution can still fail inside an OpenShell sandbox if that loopback address is **not reachable** from the sandbox’s network namespace.

**Automated host fix (recommended):** from the AI-Q repo on the machine that runs Docker, merge upstream DNS into **`/etc/docker/daemon.json`** and restart Docker:

```bash
cd /path/to/aiq
python3 deploy/openshell/scripts/configure_docker_dns.py
sudo python3 deploy/openshell/scripts/configure_docker_dns.py --apply --restart
```

The first line is a **dry run** (prints the merged `dns` list). The second writes **`/etc/docker/daemon.json`** and restarts Docker.

Defaults: **`1.1.1.1`** and **`8.8.8.8`**. Override with **`OPENSHELL_DOCKER_DNS=10.0.0.1,10.0.0.2`** (comma-separated) for corporate resolvers, then run the same **`--apply --restart`**.

Recreate the sandbox, then re-check **`getent hosts integrate.api.nvidia.com`** inside it.

The container **`deploy/entrypoint.py`** also runs a quick DNS probe at startup (override with **`AIQ_SKIP_DNS_PROBE=1`**, or **`AIQ_STRICT_DNS=1`** to exit instead of warning).

If resolution still fails after Docker DNS is set, treat it as **gateway / OpenShell version / sandbox networking** (see [OpenShell issues on sandbox DNS and hostname resolution](https://github.com/NVIDIA/OpenShell/issues))—not an AI-Q application bug.

### `openshell-sandbox`: `libc.so.6: version GLIBC_2.38` / `2.39` not found

The gateway injects the **`openshell-sandbox`** supervisor built on your **host** into the sandbox container. If the **image** uses an older distro (for example Ubuntu 22.04 / Jammy, glibc 2.35), the supervisor cannot start.

[`Dockerfile.openshell`](../../Dockerfile.openshell) therefore uses **Ubuntu 24.04 (Noble)** so glibc matches typical current hosts (for example Fedora 43). Rebuild the image, delete the failed sandbox, and create again:

```bash
docker build -f Dockerfile.openshell --target openshell -t aiq-openshell:local .
openshell sandbox delete calming-kid   # use your sandbox name
```

## Files

| File | Purpose |
|------|---------|
| [../../Dockerfile.openshell](../../Dockerfile.openshell) | Non-distroless image; `sandbox` user uid/gid `1000660000`; writable `/sandbox/data` for SQLite/Chroma |
| [policy-egress.example.yaml](policy-egress.example.yaml) | Starter network policy for `integrate.api.nvidia.com` and `api.tavily.com` |
| [scripts/configure_docker_dns.py](scripts/configure_docker_dns.py) | Host-side: merge **`dns`** into Docker **`daemon.json`** and optionally **`systemctl restart docker`** (OpenShell DNS workaround) |

## OpenShift follow-up

Helm install notes for OpenShell on OpenShift live in the OpenShell repo: `OpenShell/deploy/helm/openshell/README.md`. AI-Q on OpenShift remains separate (Helm chart under `deploy/helm/`).
