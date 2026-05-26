# AIQ on NVIDIA OpenShell — OpenShift Deployment Guide

Deploy the AIQ async research agent inside an NVIDIA OpenShell sandbox on an
OpenShift cluster, with policy-enforced egress, Landlock filesystem isolation,
and the Kubernetes compute driver.

> This guide assumes you have already completed and tested the
> [local deployment](openshell.md). The sandbox image, egress policy, and
> `.openshell.env` are reused here.

---

## 0. Prerequisites

| Requirement | Version / Notes |
|---|---|
| **OpenShift cluster** | 4.14+ (tested on 4.19) |
| **`oc` CLI** | Logged in with cluster-admin privileges |
| **Helm** | 3.x |
| **OpenShell CLI** | Same version as the local deployment |
| **Docker** | On your workstation, for building and pushing the image |
| **AIQ sandbox image** | `aiq-openshell:local` (built via `Dockerfile.openshell`) |
| **`.openshell.env`** | Created during local deployment (see [local guide §2.2](openshell.md)) |

---

## 1. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  OpenShift Cluster                                              │
│                                                                 │
│  namespace: agent-sandbox-system                                │
│  ┌──────────────────────────────────┐                           │
│  │ Agent Sandbox CRD Controller     │                           │
│  └──────────────────────────────────┘                           │
│                                                                 │
│  namespace: openshell                                           │
│  ┌──────────────┐     ┌───────────────────────────────────────┐ │
│  │ openshell-0   │────▶│ aiq-ocp (sandbox pod)                │ │
│  │ (gateway)    │     │                                       │ │
│  │ :8080        │     │  ┌─ supervisor (root ns)              │ │
│  └──────────────┘     │  │    ├─ Landlock policy              │ │
│                       │  │    ├─ network namespace 10.200.0.x │ │
│  ┌──────────────┐     │  │    └─ egress proxy :3128           │ │
│  │ Internal     │     │  │                                    │ │
│  │ Registry     │◀────│  └─ sandbox namespace                 │ │
│  │ (image pull) │     │       ├─ dask-scheduler               │ │
│  └──────────────┘     │       ├─ dask-worker (--no-nanny)     │ │
│                       │       └─ uvicorn (FastAPI) :8000      │ │
│                       └───────────────────────────────────────┘ │
│                                                                 │
│  Workstation                                                    │
│  ┌───────────────────────────────────┐                          │
│  │ oc port-forward → TCP proxy :8000 │ ◀── curl / UI           │
│  └───────────────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────┘
```

| Component | Details |
|---|---|
| **Gateway** | `openshell-0` StatefulSet, Helm chart v0.0.48 |
| **Sandbox** | Kubernetes pod running the OpenShell supervisor + AIQ image |
| **Image registry** | OpenShift internal registry (`image-registry.openshift-image-registry.svc:5000`) |
| **Network** | Sandbox runs in an isolated network namespace inside the pod; egress goes through the supervisor's proxy |

---

## 2. Deployment Steps

### 2.1 Install the Agent Sandbox CRDs

```shell
kubectl apply -f https://github.com/kubernetes-sigs/agent-sandbox/releases/latest/download/manifest.yaml
```

Verify the controller is running:

```shell
kubectl get pods -n agent-sandbox-system
```

### 2.2 Create the namespace and grant SCC

```shell
oc create ns openshell

oc adm policy add-scc-to-user privileged -z openshell-sandbox -n openshell
```

The `privileged` SCC is required because sandbox pods use network namespaces
and Landlock, which need elevated capabilities.

### 2.3 Deploy the OpenShell gateway via Helm

```shell
helm install openshell oci://ghcr.io/nvidia/openshell/helm-chart \
  --version 0.0.48 \
  -n openshell \
  --set pkiInitJob.enabled=false \
  --set server.disableTls=true \
  --set server.auth.allowUnauthenticatedUsers=true \
  --set podSecurityContext.fsGroup=null \
  --set securityContext.runAsUser=null
```

| Override | Reason |
|---|---|
| `pkiInitJob.enabled=false` | Skip the PKI init job (mTLS certs not needed for dev) |
| `server.disableTls=true` | Plaintext gRPC — TLS is terminated at the OpenShift edge |
| `server.auth.allowUnauthenticatedUsers=true` | Dev-only — allows CLI access without OIDC setup |
| `podSecurityContext.fsGroup=null` | Let OpenShift assign fsGroup via SCC |
| `securityContext.runAsUser=null` | Let OpenShift assign UID via SCC |

> **Production note:** For shared or production clusters, configure OIDC
> authentication instead of `allowUnauthenticatedUsers=true`. See the
> Helm chart `server.oidc.*` values.

### 2.4 Create the JWT signing keys

The gateway requires a signing key secret for minting sandbox JWTs. Since we
disabled the PKI init job, create it manually:

```shell
openssl genpkey -algorithm ed25519 -out /tmp/signing.pem
openssl pkey -in /tmp/signing.pem -pubout -out /tmp/public.pem
openssl rand -hex 16 > /tmp/kid

oc create secret generic openshell-jwt-keys \
  -n openshell \
  --from-file=signing.pem=/tmp/signing.pem \
  --from-file=public.pem=/tmp/public.pem \
  --from-file=kid=/tmp/kid

rm -f /tmp/signing.pem /tmp/public.pem /tmp/kid
```

Restart the gateway pod to pick up the secret:

```shell
oc delete pod openshell-0 -n openshell
```

Wait for it to come back:

```shell
oc get pods -n openshell -w
# Wait for openshell-0  1/1  Running
```

### 2.5 Push the AIQ image to the internal registry

```shell
REGISTRY=$(oc get route default-route -n openshift-image-registry -o jsonpath='{.spec.host}')

docker login -u $(oc whoami) -p $(oc whoami -t) $REGISTRY

docker tag aiq-openshell:local $REGISTRY/openshell/aiq-openshell:latest
docker push $REGISTRY/openshell/aiq-openshell:latest
```

Verify the image stream was created:

```shell
oc get imagestream aiq-openshell -n openshell
```

### 2.6 Connect the OpenShell CLI to the cluster gateway

Port-forward the gateway service to your workstation:

```shell
oc port-forward svc/openshell 18080:8080 -n openshell &
```

Register the gateway in the CLI:

```shell
openshell gateway add http://127.0.0.1:18080 --local --name ocp-dev
openshell gateway select ocp-dev
openshell status
# Should show: Status: Connected, Version: 0.0.48
```

### 2.7 Create the sandbox

```shell
openshell sandbox create \
  --from image-registry.openshift-image-registry.svc:5000/openshell/aiq-openshell:latest \
  --name aiq-ocp \
  --policy deploy/openshell/policy-egress.yaml \
  --no-tty
```

> You may see `connect_path is empty` — this is a known issue with the CLI's
> SSH tunneling against the Kubernetes driver. The sandbox itself is created
> successfully. Verify with `openshell sandbox list`.

### 2.8 Upload the environment file and start the AIQ API

Copy the env file into the sandbox pod:

```shell
oc cp .openshell.env openshell/aiq-ocp:/sandbox/.env -c agent
oc exec aiq-ocp -n openshell -c agent -- chown sandbox:sandbox /sandbox/.env
```

Start the AIQ entrypoint via `openshell sandbox exec`:

```shell
openshell sandbox exec -n aiq-ocp --no-tty \
  bash -c 'set -a && source /sandbox/.env && set +a && \
           export PATH="/app/.venv/bin:$PATH" && \
           python /app/deploy/entrypoint.py'
```

Wait for `Uvicorn running on http://0.0.0.0:8000` in the output.

### 2.9 Set up port access (TCP proxy bridge)

The AIQ app runs inside a nested network namespace (10.200.0.2) within the
sandbox pod. Standard `oc port-forward` cannot reach it directly. Deploy a
lightweight TCP proxy in the pod's root namespace to bridge the gap.

Create the proxy script:

```python
# /tmp/tcp_proxy.py
import asyncio, sys

LISTEN_HOST, LISTEN_PORT = "0.0.0.0", int(sys.argv[1]) if len(sys.argv) > 1 else 8000
TARGET_HOST, TARGET_PORT = sys.argv[2] if len(sys.argv) > 2 else "10.200.0.2", int(sys.argv[3]) if len(sys.argv) > 3 else 8000

async def handle(reader, writer):
    try:
        tr, tw = await asyncio.open_connection(TARGET_HOST, TARGET_PORT)
    except Exception:
        writer.close(); return
    async def pipe(r, w):
        try:
            while True:
                d = await r.read(65536)
                if not d: break
                w.write(d); await w.drain()
        except Exception: pass
        finally:
            try: w.close()
            except: pass
    await asyncio.gather(pipe(reader, tw), pipe(tr, writer))

async def main():
    srv = await asyncio.start_server(handle, LISTEN_HOST, LISTEN_PORT)
    print(f"Proxy listening on {LISTEN_HOST}:{LISTEN_PORT} -> {TARGET_HOST}:{TARGET_PORT}", flush=True)
    async with srv: await srv.serve_forever()

asyncio.run(main())
```

Upload and run the proxy:

```shell
oc cp /tmp/tcp_proxy.py openshell/aiq-ocp:/tmp/tcp_proxy.py -c agent
oc exec aiq-ocp -n openshell -c agent -- python3 /tmp/tcp_proxy.py 8000 10.200.0.2 8000 &
```

Now port-forward to the pod:

```shell
oc port-forward pod/aiq-ocp 8000:8000 -n openshell &
```

### 2.10 Verify

```shell
# Health check
curl http://127.0.0.1:8000/health
# → {"status":"healthy"}

# List available agents
curl http://127.0.0.1:8000/v1/jobs/async/agents
# → {"agents":[{"agent_type":"deep_researcher",...},{"agent_type":"shallow_researcher",...}]}

# Submit a test job
curl -X POST http://127.0.0.1:8000/v1/jobs/async/submit \
  -H 'Content-Type: application/json' \
  -d '{"input":"What is OpenShift?","agent_type":"shallow_researcher"}'
# → {"job_id":"...","status":"submitted",...}

# Poll status (replace JOB_ID)
curl http://127.0.0.1:8000/v1/jobs/async/job/<JOB_ID>

# Stream events
curl -N http://127.0.0.1:8000/v1/jobs/async/job/<JOB_ID>/stream
```

---

## 3. Known Issues

| Issue | Description | Workaround |
|---|---|---|
| `connect_path is empty` | OpenShell CLI SSH tunneling does not work with the Kubernetes compute driver. Affects `openshell forward`, `openshell sandbox exec` (intermittently), and the initial command in `sandbox create`. | Use `oc cp` + `oc exec` + `oc port-forward` with the TCP proxy bridge (§2.8–2.9). |
| `nft ruleset load failed` | Non-fatal sandbox supervisor warning. The nftables `ct state` module is not available in the pod kernel. Bypass logging degrades but sandbox networking works. | No action needed — the supervisor falls back gracefully. |
| `.env` upload via `--upload` lost | Files uploaded during `sandbox create` may be overwritten by the workspace PVC mount. | Copy the env file after creation with `oc cp` (§2.8). |

---

## 4. Namespaces and Resources

| Namespace | Resources |
|---|---|
| `agent-sandbox-system` | Agent Sandbox CRD controller |
| `openshell` | Gateway StatefulSet (`openshell-0`), sandbox pods (`aiq-ocp`), service accounts (`openshell`, `openshell-sandbox`), JWT signing secret, ConfigMap, PVCs |

---

## 5. Cleanup

```shell
# Delete the sandbox
openshell sandbox delete aiq-ocp

# Uninstall the Helm release
helm uninstall openshell -n openshell

# Remove the namespace
oc delete ns openshell

# Remove the Agent Sandbox CRDs (optional — affects all users)
kubectl delete -f https://github.com/kubernetes-sigs/agent-sandbox/releases/latest/download/manifest.yaml
```

---

## 6. Differences from Local Deployment

| Aspect | Local (Docker) | OpenShift (Kubernetes) |
|---|---|---|
| **Compute driver** | Docker | Kubernetes |
| **Gateway** | `mise run gateway:docker` | Helm chart StatefulSet |
| **Image delivery** | Local Docker daemon | OpenShift internal registry |
| **DNS pinning** | `docker exec` into container `/etc/hosts` | Not needed — egress proxy resolves DNS |
| **Port access** | `openshell forward start 8000` | TCP proxy bridge + `oc port-forward` |
| **Auth** | No auth (local plaintext) | `allowUnauthenticatedUsers=true` (dev) or OIDC (prod) |
| **JWT keys** | Auto-generated by gateway | Manual secret creation (§2.4) |
