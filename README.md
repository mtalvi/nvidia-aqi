<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

-->
<h1>NVIDIA AI-Q Blueprint</h1>

> **⚠️ IMPORTANT – Active Research Branch**
>
> You are currently viewing the **`drb2`** branch for the pre-release version of **AI-Q v2.0**.
> 
> This branch contains features and experimental updates that we are submitting to the Deep Research Bench II Leaderboard and may contain breaking changes.
>
> For production use, switch to the **v1.2.1 stable release** on the [`main branch`](https://github.com/NVIDIA-AI-Blueprints/aiq/tree/main).


## Table of Contents
- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [API Keys](#api-keys)
- [Running Evaluation](#running-evaluation)
- [Optional: Phoenix Tracing](#optional-phoenix-tracing)
- [License](#license)

## Overview

NVIDIA AI-Q provides a multi-agent deep research system that produces comprehensive, cited research reports. It uses an orchestrator that delegates to a planner (evidence-grounded planning via web search) and researcher subagents, then synthesizes findings into a final report. It is built using [NVIDIA NAT](https://github.com/NVIDIA/NeMo-Agent-Toolkit) and the [deepagents](https://github.com/langchain-ai/deepagents) library.

## Prerequisites

- Python 3.11-3.13
- [uv](https://github.com/astral-sh/uv) package manager
- NVIDIA API key from [NVIDIA Build](https://build.nvidia.com/)

Recommended for research quality:
- Tavily API key (web search)
- Serper API key (paper search)

## Setup

Clone and set up the environment:

```bash
git clone https://github.com/NVIDIA-AI-Blueprints/aiq.git && cd aiq
git checkout drb2
./scripts/setup.sh
```

Create your environment file:

```bash
cp deploy/.env.example deploy/.env
```

## API Keys

Set the keys in `deploy/.env`:

| API | Environment Variable | Purpose | Required |
| --- | --- | --- | --- |
| NVIDIA Build | `NVIDIA_API_KEY` | Agent LLM inference | Required |
| Anthropic | `ANTHROPIC_API_KEY` | Agent LLM inference | Required |
| Tavily | `TAVILY_API_KEY` | Web search backend | Required |
| Serper | `SERPER_API_KEY` | Academic paper search | Required |

#### Obtain an NVIDIA API Key

1. Sign in to [NVIDIA Build](https://build.nvidia.com/)
2. Click on any model, then select "Deploy" > "Get API Key" > "Generate Key"

#### Obtain a Tavily API Key

1. Sign in to [Tavily](https://tavily.com/)
2. Navigate to your dashboard
3. Generate an API key

#### Obtain a Serper API Key

1. Sign in to [Serper](https://serper.dev/)
2. Generate an API key from your dashboard

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

Default UI endpoint: `http://localhost:6006`

For detailed benchmark documentation, refer to:
- [Deep Research Bench README](frontends/benchmarks/deepresearch_bench_II/README.md)

## License

This project will download and install additional third-party open source software projects. Review the license terms of these open source projects before use, found in [LICENSE-THIRD-PARTY](LICENSE-THIRD-PARTY). 

GOVERNING TERMS: AIQ blueprint software and materials are governed by the [Apache License, Version 2.0](https://www.apache.org/licenses/LICENSE-2.0)
