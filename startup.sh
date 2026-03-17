#!/usr/bin/env bash
set -euo pipefail

# Use the venv directly — no uv project file needed
VLLM=/workspace/.venv/bin/vllm

exec "$VLLM" serve nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16 \
  --async-scheduling \
  --dtype auto \
  --kv-cache-dtype fp8 \
  --tensor-parallel-size 8 \
  --pipeline-parallel-size 1 \
  --data-parallel-size 1 \
  --swap-space 0 \
  --trust-remote-code \
  --gpu-memory-utilization 0.9 \
  --enable-chunked-prefill \
  --max-num-seqs 512 \
  --served-model-name nemotron-super \
  --max-model-len 131072 \
  --host 0.0.0.0 \
  --port 8080 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser-plugin "./super_v3_reasoning_parser.py" \
  --reasoning-parser super_v3
