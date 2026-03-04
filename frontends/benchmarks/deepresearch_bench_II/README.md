# Deep Research Bench II Evaluation of NVIDIA AI-Q Blueprint

> For detailed benchmark documentation, refer to: [Deep Research Bench II GitHub Repository](https://github.com/imlrz/DeepResearch-Bench-II/tree/main)

### API Keys

```bash
export TAVILY_API_KEY=your_key              # For web search
export NVIDIA_API_KEY=your_key              # For agent execution (integrate.api.nvidia.com)
export OPENAI_API_KEY=your_key              # For frontier model in config (optional)
export ANTHROPIC_API_KEY=your_key              # For Gemini eval 
```

## Configuration Files

The following table lists the available configuration files:

| Configuration file | Description |
| --- | --- |
| `frontends/benchmarks/deepresearch_bench/configs/config_workflow_only.yml` | Runs the DeepResearch Bench II evaluation with a combination of GPT-5.2 model and nemotron. |

## Running Evaluation

### Step 1: Install the dataset

The dataset files are not included in the repository. 
To download the dataset files, run the following:

```bash
mkdir frontends/benchmarks/deepresearch_bench_II/data 
wget https://raw.githubusercontent.com/imlrz/DeepResearch-Bench-II/refs/heads/main/tasks_and_rubrics.jsonl && mv tasks_and_rubrics.jsonl frontends/benchmarks/deepresearch_bench_II/data/tasks_and_rubrics.jsonl
```

### Step 2: Generate reports using NAT evaluation harness

```bash
cd frontends/benchmarks/deepresearch_bench_II/scripts
bash run_workflow_save_per_item.sh
```

### Step 3: Run evaluation
Follow instructions in the [Deep Research Bench II Github Repository](https://github.com/imlrz/DeepResearch-Bench-II/tree/main) to run evaluation and obtain scores.

## Optional: Phoenix Tracing

If your config enables Phoenix tracing, start the Phoenix server before running `nat eval`.

Start server (separate terminal):

```bash
source .venv/bin/activate
phoenix serve
```
