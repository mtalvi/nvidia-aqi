# AIRA v2.0 — OpenShift Deployment Guide

This guide covers deploying the NVIDIA AI-Q Research Assistant (AIRA) v2.0 blueprint on Red Hat OpenShift.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Knowledge Modes](#knowledge-modes)
- [Prerequisites](#prerequisites)
- [Hardware Requirements](#hardware-requirements)
- [Quick Start](#quick-start)
- [Deployment Files](#deployment-files)
- [OpenShift-Specific Challenges and Solutions](#openshift-specific-challenges-and-solutions)
- [Verification](#verification)
- [Testing and Data Ingestion](#testing-and-data-ingestion)
- [Scaling Down / Scaling Up](#scaling-down--scaling-up)
- [Uninstall](#uninstall)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

AIRA v2.0 is a deep-research AI assistant that uses hosted NVIDIA NIM models for all LLM inference (no local GPU-based LLM required). The core deployment consists of three pods:

| Component | Description | GPU |
|-----------|-------------|-----|
| **aiq-backend** | FastAPI backend running the research agent workflows | None |
| **aiq-frontend** | Next.js web UI | None |
| **aiq-postgres** | PostgreSQL for job state, checkpoints, and summaries | None |

All LLM inference (Nemotron, GPT-OSS, etc.) runs on NVIDIA's hosted API (`integrate.api.nvidia.com`), meaning AIRA itself requires **0 GPUs**.

### Changes from v1.2

| Feature | v1.2 | v2.0 |
|---------|------|------|
| Local LLM NIM | Yes (Llama 8B/70B, 1-2 GPUs) | No (all LLMs hosted) |
| Helm chart | AIRA-specific with subcharts | Generic app chart (`deployment-k8s`) |
| Knowledge backend | FRAG only (external RAG Blueprint) | LlamaIndex (built-in) or FRAG (external) |
| Database | None | PostgreSQL (jobs, checkpoints, summaries) |
| AIRA GPU requirement | 1-2 GPUs | 0 GPUs |

---

## Knowledge Modes

AIRA v2.0 supports two knowledge retrieval backends. **Both are fully supported** by the OpenShift deployment script.

### LlamaIndex Mode (Default)

- **Self-contained**: Uses a local ChromaDB vector store inside the backend pod.
- **0 GPUs** for AIRA (all LLMs are cloud-hosted).
- Documents are uploaded via the frontend UI and stored locally.
- Best for: quick deployment, small-to-medium document sets, environments without spare GPUs.

### Foundational RAG (FRAG) Mode

- **External RAG Blueprint**: Deploys the full NVIDIA RAG pipeline in a separate namespace.
- **6 additional GPUs** for the RAG Blueprint (embedding NIM, reranking NIM, nv-ingest GPU models).
- Documents are processed through nv-ingest (OCR, page elements, table structure, graphic elements) and stored in Milvus.
- Best for: large-scale document processing, enterprise-grade RAG, PDF-heavy workloads.

### Comparison

| Aspect | LlamaIndex | FRAG |
|--------|-----------|------|
| GPUs (AIRA) | 0 | 0 |
| GPUs (RAG) | 0 | 6 |
| Total GPUs | **0** | **6** |
| Vector DB | ChromaDB (local) | Milvus (cluster) |
| Document processing | Basic (frontend upload) | nv-ingest pipeline (OCR, table extraction, etc.) |
| Setup complexity | Low | High |
| Data persistence | Pod-local (lost on restart unless PVC added) | Milvus + MinIO (persistent) |
| External dependencies | None | RAG Blueprint namespace |

---

## Prerequisites

- OpenShift 4.12+ cluster with `oc` CLI authenticated
- `helm` v3.x installed
- **NVIDIA API Key** (`NVIDIA_API_KEY`) from [build.nvidia.com](https://build.nvidia.com) — required for hosted LLM inference
- **NGC API Key** (`NGC_API_KEY`) from [org.ngc.nvidia.com](https://org.ngc.nvidia.com/setup/api-keys) — required for pulling images from `nvcr.io`
- (Optional) **Tavily API Key** for web search functionality
- (FRAG mode only) 6 GPUs available on nodes with appropriate taints

---

## Hardware Requirements

### LlamaIndex Mode

| Resource | Requirement |
|----------|-------------|
| GPUs | **0** |
| CPU | ~3 vCPU |
| Memory | ~6 Gi |
| Storage | 10 Gi (PostgreSQL PVC) |

### FRAG Mode (additional, for RAG Blueprint)

| Component | GPUs | Memory |
|-----------|------|--------|
| Embedding NIM (llama-3.2-nv-embedqa-1b-v2) | 1 | ~16 Gi |
| Reranking NIM (llama-3.2-nv-rerankqa-1b-v2) | 1 | ~16 Gi |
| nv-ingest OCR | 1 | ~16 Gi |
| nv-ingest Page Elements | 1 | ~16 Gi |
| nv-ingest Table Structure | 1 | ~16 Gi |
| nv-ingest Graphic Elements | 1 | ~16 Gi |
| nv-ingest Runtime, Milvus, MinIO, Redis, etcd, rag-server, ingestor-server | 0 | ~30 Gi |
| **RAG Total** | **6** | **~126 Gi** |

---

## Quick Start

### LlamaIndex Mode (0 GPUs)

```bash
NGC_API_KEY=nvapi-... \
NVIDIA_API_KEY=nvapi-... \
AIRA_NAMESPACE=aira \
  bash openshift/deploy/helm/deploy-openshift.sh
```

### FRAG Mode (6 GPUs)

```bash
NGC_API_KEY=nvapi-... \
NVIDIA_API_KEY=nvapi-... \
AIRA_NAMESPACE=aira \
KNOWLEDGE_MODE=frag \
  bash openshift/deploy/helm/deploy-openshift.sh
```

### Optional Parameters

```bash
# Custom GPU tolerations (if your GPU nodes use non-default taints)
GPU_TOLERATION_KEYS=g6-gpu,p4-gpu,nvidia.com/gpu

# Custom storage class
STORAGE_CLASS=gp3-csi

# Custom RAG namespace (FRAG mode only, default: ${AIRA_NAMESPACE}-rag)
RAG_NAMESPACE=my-rag

# Custom database credentials
DB_USER_NAME=aiq
DB_USER_PASSWORD=aiq_dev

# Tavily API key for web search
TAVILY_API_KEY=tvly-...
```

---

## Deployment Files

All OpenShift-specific files are isolated in the `openshift/` directory. No upstream files are modified.

```
openshift/
├── docs/
│   └── deploy-openshift.md          # This guide
└── deploy/helm/
    ├── deploy-openshift.sh           # Main deployment script (both modes)
    ├── values-openshift.yaml         # AIRA Helm value overrides for OpenShift
    └── rag-values-openshift.yaml     # RAG Blueprint value overrides (FRAG mode)
```

### How It Works

1. The deploy script creates the namespace, secrets (with Helm ownership labels), and SCC grants.
2. For FRAG mode, it first deploys the RAG Blueprint via a pinned Helm chart URL, then applies post-deploy patches for GPU tolerations, resource tuning, and NIM bug workarounds.
3. It installs the AIRA chart (`deploy/helm/deployment-k8s/`) with OpenShift-specific overrides from `values-openshift.yaml` plus dynamic `--set` arguments for the knowledge mode and namespace.
4. It creates OpenShift Routes for the frontend (the chart has no Route template).

---

## OpenShift-Specific Challenges and Solutions

### 1. Namespace Naming Convention

**Problem**: The chart uses `ns-{appname}` as the namespace for all resources, which doesn't match custom OpenShift namespace names.

**Solution**: Set `project.deploymentTarget: kind` in values, which makes the namespace equal to `appname`. The deploy script overrides `aiq.appname` to match the target namespace.

### 2. No Route Template

**Problem**: The chart defines `route` configs in values but has no `route.yaml` template — only Ingress is supported.

**Solution**: The deploy script creates OpenShift Routes manually via `oc create route edge`.

### 3. Security Context Constraints (SCCs)

**Problem**: OpenShift's default restricted SCC blocks pods that need elevated privileges. The backend image runs processes as root, and PostgreSQL needs specific filesystem permissions.

**Solution**: The deploy script grants `anyuid` SCC to all app-specific service accounts (`aiq-backend`, `aiq-frontend`, `aiq-postgres`) before chart installation. SCC bindings to non-existent SAs are valid and take effect once the chart creates them.

### 4. Secret Helm Ownership (Re-run Safety)

**Problem**: `helm upgrade --install` fails when it encounters secrets created outside of Helm.

**Solution**: Pre-created secrets are labeled with `app.kubernetes.io/managed-by=Helm` and annotated with `meta.helm.sh/release-name` and `meta.helm.sh/release-namespace`. This lets Helm adopt them as part of the release.

### 5. FRAG Mode — GPU Tolerations

**Problem**: The RAG Blueprint's nv-ingest GPU models are deeply nested subcharts where `--set tolerations` doesn't propagate.

**Solution**: The deploy script patches tolerations directly onto Deployment resources after `helm install`.

### 6. FRAG Mode — nv-ingest Resource Oversizing

**Problem**: The nv-ingest runtime requests 24 CPU / 24 Gi by default, which is excessive for most clusters.

**Solution**: The deploy script patches resources to 2-4 CPU / 8-16 Gi.

### 7. FRAG Mode — NIM Tokenizer Parallelism Bug

**Problem**: HuggingFace tokenizers Rust library panics with `GlobalPoolAlreadyInitialized` during Triton model loading.

**Solution**: Set `TOKENIZERS_PARALLELISM=false` on embedding and reranking NIM deployments.

---

## Verification

### Check Pod Status

```bash
# AIRA pods (both modes)
oc get pods -n $AIRA_NAMESPACE

# Expected: aiq-backend, aiq-frontend, aiq-postgres — all Running

# RAG pods (FRAG mode only)
oc get pods -n ${AIRA_NAMESPACE}-rag
```

### Check Routes

```bash
oc get routes -n $AIRA_NAMESPACE

# Access the frontend
FRONTEND=$(oc get route aira-frontend -n $AIRA_NAMESPACE -o jsonpath='{.spec.host}')
echo "https://$FRONTEND"
```

### Health Check

```bash
oc port-forward svc/aiq-backend 8000:8000 -n $AIRA_NAMESPACE &
curl http://localhost:8000/health
```

---

## Testing and Data Ingestion

### LlamaIndex Mode

In LlamaIndex mode, documents are uploaded directly through the frontend UI:

1. Open the frontend URL (from the Route).
2. Use the file upload feature to add documents (PDF, DOCX, TXT, MD).
3. Documents are processed and stored in the local ChromaDB.
4. Ask questions about the uploaded content.

> **Note**: In LlamaIndex mode, uploaded data is stored inside the backend pod's filesystem. Data is lost if the pod restarts unless you configure a PersistentVolumeClaim for `/app/data/chroma`.

### FRAG Mode

In FRAG mode, documents go through the full nv-ingest pipeline:

1. **Bulk upload via script** (recommended for large datasets):

   ```bash
   # Port-forward to the ingestor service
   oc port-forward svc/ingestor-server 8082:8082 -n ${AIRA_NAMESPACE}-rag &

   # Run the upload script
   RAG_INGEST_URL="http://localhost:8082" python data/zip_to_collection.py \
     --zip_path data/Biomedical_Dataset.zip \
     --collection_name biomedical
   ```

2. **Frontend upload**: Use the web UI file upload (same as LlamaIndex mode, but files are routed to the ingestor server).

3. **Verify ingestion**: Check the Milvus collection count:
   ```bash
   oc port-forward svc/milvus 19530:19530 -n ${AIRA_NAMESPACE}-rag &
   python -c "from pymilvus import connections, Collection; connections.connect(host='localhost', port='19530'); c=Collection('biomedical'); print(f'Documents: {c.num_entities}')"
   ```

---

## Scaling Down / Scaling Up

### Scale Down (preserve data)

```bash
# AIRA
oc scale deploy/aiq-backend deploy/aiq-frontend deploy/aiq-postgres --replicas=0 -n $AIRA_NAMESPACE

# RAG (FRAG mode only)
oc scale deploy --all --replicas=0 -n ${AIRA_NAMESPACE}-rag
oc scale statefulset --all --replicas=0 -n ${AIRA_NAMESPACE}-rag
```

### Scale Up

```bash
# AIRA
oc scale deploy/aiq-backend deploy/aiq-frontend --replicas=1 -n $AIRA_NAMESPACE
oc scale deploy/aiq-postgres --replicas=1 -n $AIRA_NAMESPACE

# RAG (FRAG mode only) — scale up in order: infrastructure first, then NIMs
oc scale statefulset --all --replicas=1 -n ${AIRA_NAMESPACE}-rag
oc scale deploy --all --replicas=1 -n ${AIRA_NAMESPACE}-rag
```

---

## Uninstall

```bash
# Uninstall AIRA
helm uninstall aiq -n $AIRA_NAMESPACE
oc delete project $AIRA_NAMESPACE

# Uninstall RAG (FRAG mode only)
helm uninstall rag -n ${AIRA_NAMESPACE}-rag
oc delete project ${AIRA_NAMESPACE}-rag
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ImagePullBackOff` | Missing or invalid `ngc-secret` | Verify NGC_API_KEY and recreate the secret |
| `CrashLoopBackOff` on backend | Missing `aiq-credentials` secret or bad API key | Check `oc logs` and verify secret keys |
| `Pending` pods (FRAG mode) | Insufficient GPU or CPU resources | Check `oc describe pod` for scheduling errors |
| `CreateContainerConfigError` | Secret referenced in envFrom doesn't exist | Ensure `aiq-credentials` was created before Helm install |
| Frontend shows "Network Error" | Backend not ready or CORS issue | Wait for backend pod to be Running, check `oc logs` |
| FRAG: RAG queries return empty | Documents not ingested or Milvus not ready | Verify ingestion (see Testing section) |
| FRAG: Ingestion timeout | nv-ingest models still loading | Wait for all GPU pods in RAG namespace to be Running |
