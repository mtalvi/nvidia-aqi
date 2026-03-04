#!/bin/bash
# DeepResearchBench_2: Run deep research workflow for each dataset item and save each result to a separate file.
#
# 1. Runs nat eval (workflow only, no evaluators) to produce workflow_output.json.
# 2. Splits workflow_output.json into output_dir/items/<idx>.json (one file per item; task-id and idx preserved).
#
# Prerequisites:
#   - Virtual environment activated
#   - deploy/.env with required API keys (SERPER_API_KEY, etc.)
#
# Usage:
#   ./run_workflow_save_per_item.sh                         # Run full dataset, output to aggregated_results_YYYYMMDD_HHMMSS
#   ./run_workflow_save_per_item.sh "experiment-name"       # Run with custom output dir name
#   ./run_workflow_save_per_item.sh --test                  # Run single item (id "0") for testing
#   ./run_workflow_save_per_item.sh --output-dir my_run     # Explicit output path (relative to project root)
#   ./run_workflow_save_per_item.sh --env deploy/.env

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(cd "$BENCHMARK_DIR/../../.." && pwd)"

# Create timestamp for directory naming (same pattern as run_drb_multi_eval_seq.sh)
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')

CONFIG_FILE="frontends/benchmarks/deepresearch_bench_II/configs/config_workflow_only.yml"
ENV_FILE="deploy/.env"
PREFIX=""
TEST_FILTER_ID=1

while [[ $# -gt 0 ]]; do
    case $1 in
        --test)
            RUN_TEST=1
            shift
            ;;
        --output-dir)
            OUTPUT_DIR_REL="$2"
            shift 2
            ;;
        --env)
            ENV_FILE="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS] [PREFIX]"
            echo ""
            echo "Arguments:"
            echo "  PREFIX          Optional prefix for output directory name (e.g., 'experiment-1')"
            echo ""
            echo "Options:"
            echo "  --test          Run a single item (idx=$TEST_FILTER_ID) for testing"
            echo "  --output-dir D  Output directory relative to project root (overrides PREFIX)"
            echo "  --env E         Env file path (default: $ENV_FILE)"
            echo "  --help, -h      Show this help"
            echo ""
            echo "Examples:"
            echo "  $0                              # Output to aggregated_results_${TIMESTAMP}/"
            echo "  $0 \"my-experiment\"              # Output to my-experiment/"
            exit 0
            ;;
        *)
            if [ -z "${PREFIX}" ]; then
                PREFIX="$1"
                shift
            else
                echo "Unknown option: $1" >&2
                exit 1
            fi
            ;;
    esac
done

# Construct output directory (after argument parsing)
if [ -z "${OUTPUT_DIR_REL:-}" ]; then
    if [ -n "$PREFIX" ]; then
        OUTPUT_DIR_REL="${BENCHMARK_DIR#$PROJECT_ROOT/}/${PREFIX}"
    else
        OUTPUT_DIR_REL="${BENCHMARK_DIR#$PROJECT_ROOT/}/aggregated_results_${TIMESTAMP}"
    fi
fi

cd "$PROJECT_ROOT"

if [ -z "${VIRTUAL_ENV:-}" ]; then
    echo "Warning: VIRTUAL_ENV not set. Activate your venv before running." >&2
fi

ENV_PATH="${PROJECT_ROOT}/${ENV_FILE}"
if [ ! -f "$ENV_PATH" ]; then
    echo "Error: Env file not found: $ENV_PATH" >&2
    exit 1
fi

NAT_OVERRIDES=(
    --override "eval.general.output_dir" "$OUTPUT_DIR_REL"
)
if [ -n "${RUN_TEST:-}" ]; then
    # Override dataset filter to a single id (value parsed as YAML)
    NAT_OVERRIDES+=(--override "eval.general.dataset.filter.allowlist.field.idx" "[\"$TEST_FILTER_ID\"]")
fi

OUTPUT_DIR_ABS="${PROJECT_ROOT}/${OUTPUT_DIR_REL}"
mkdir -p "$OUTPUT_DIR_ABS"
cp "${PROJECT_ROOT}/${CONFIG_FILE}" "$OUTPUT_DIR_ABS/config.yml"
echo "Saved config snapshot: ${OUTPUT_DIR_REL}/config.yml"

GIT_BRANCH=$(git -C "$PROJECT_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
GIT_COMMIT=$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || echo "unknown")
GIT_STATUS=$(git -C "$PROJECT_ROOT" status --short 2>/dev/null)
{
    echo "branch: $GIT_BRANCH"
    echo "commit: $GIT_COMMIT"
    echo "timestamp: $(date '+%Y-%m-%dT%H:%M:%S')"
    if [ -n "$GIT_STATUS" ]; then
        echo "dirty: true"
        echo "uncommitted_changes: |"
        echo "$GIT_STATUS" | sed 's/^/  /'
    else
        echo "dirty: false"
    fi
} > "$OUTPUT_DIR_ABS/git_info.yml"
echo "Saved git info: ${OUTPUT_DIR_REL}/git_info.yml (branch=$GIT_BRANCH, commit=${GIT_COMMIT:0:8})"

echo "Running workflow (output_dir=$OUTPUT_DIR_REL)..."
if ! dotenv -f "$ENV_PATH" run -- nat eval --config_file "$CONFIG_FILE" "${NAT_OVERRIDES[@]}"; then
    echo "nat eval failed." >&2
    exit 1
fi

WORKFLOW_JSON="${OUTPUT_DIR_ABS}/workflow_output.json"
if [ ! -f "$WORKFLOW_JSON" ]; then
    echo "Error: Expected $WORKFLOW_JSON after nat eval." >&2
    exit 1
fi

DATASET_JSONL="${BENCHMARK_DIR}/data/tasks_and_rubrics.jsonl"
echo "Splitting workflow_output.json into per-item files..."
python "${BENCHMARK_DIR}/scripts/split_workflow_output_to_per_item.py" \
    --input "$WORKFLOW_JSON" \
    --output-dir "$OUTPUT_DIR_ABS" \
    --dataset "$DATASET_JSONL"

echo "Done. Results: ${OUTPUT_DIR_ABS}/items/"
