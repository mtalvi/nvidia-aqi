# ruff: noqa: E501
#!/usr/bin/env python3
"""
Batch rewrite articles using Claude Opus with concurrency.

Supports resuming: already-written IDs in the output file are skipped.

Usage:
    python rewrite_report.py data/test_data/raw_data/gpt_nemotron_ensemble.jsonl -c 5
"""

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed

from openai import OpenAI
from tqdm import tqdm

REWRITE_PROMPT = """You are an expert research report editor. Your task is to substantially enhance the following research report to maximize its analytical depth, evidentiary rigor, and actionable value by replacing vague claims with concrete specifics, strengthening causal reasoning, and ensuring every section delivers substantive findings rather than procedural filler.

EXPANSION INSTRUCTIONS:

1. QUANTIFY EVERY EVALUATIVE CLAIM: Replace vague qualitative descriptions ("significant growth," "substantial market," "rapidly increasing") with specific numbers, percentages, or benchmarks drawn from your knowledge of the topics already discussed in the report. For example, if the report says "the market has grown significantly," replace with "the market grew 23% year-over-year to $4.7B in 2023, according to industry estimates." If the report mentions a technology's "improved performance," specify the metric (e.g., "latency reduced from 120ms to 15ms"). When you are not confident in a specific figure for a claim already in the report, reframe the claim with directional precision and analytical context rather than leaving it vague or inventing a number.

2. DEEPEN ENTITY AND CASE STUDY COVERAGE: For every landscape survey, competitive analysis, or categorical breakdown already in the report, check whether major well-known entities, sub-sectors, product lines, or landmark case studies that are directly relevant have been omitted. Add brief but substantive coverage of any missing major players or examples that you are confident belong in the discussion. For instance, if the report surveys cloud providers but omits a top-3 player, add them. Do NOT introduce entirely new domains or topics — only fill gaps within categories the report already addresses. When uncertain whether an entity is significant enough to include, err on the side of inclusion with a brief mention rather than omission.

3. CUT SCAFFOLDING AND ELIMINATE REDUNDANCY: Reduce methodological exposition, framework descriptions, evidence-grading rubrics, and meta-commentary (e.g., "In this section we will analyze...") to no more than 15-20% of total report length. If the report states the same finding or conclusion in multiple sections, consolidate it into the single most appropriate location and cross-reference elsewhere. Replace procedural descriptions of what the report *could* do with actual executed analysis. For example, transform "We propose a four-quadrant framework for evaluating X" into a completed four-quadrant analysis with entities placed and justified.

4. EXECUTE FRAMEWORKS WITH WORKED EXAMPLES: Wherever the report proposes a scoring model, classification system, evaluation matrix, or analytical method without demonstrating it, add at least one fully worked end-to-end example using entities or data already mentioned in the report. Show concrete inputs, any intermediate steps, and the specific output or score. For instance, if the report describes a risk-scoring rubric, pick one entity already discussed and walk through its score calculation step by step. This transforms theoretical frameworks into demonstrated, credible tools.

5. GROUND RISKS IN REAL INCIDENTS: For every risk category, failure mode, or governance concern discussed in the report, add at least one specific, named real-world incident, enforcement action, or documented failure with quantified consequences (e.g., financial losses, affected users, regulatory penalties). Replace abstract warnings like "data breaches pose significant risks" with "the 2017 Equifax breach exposed 147 million records and resulted in a $700M settlement." Only reference incidents you are confident actually occurred. If you cannot recall a specific incident for a given risk, strengthen the analytical framing of why that risk matters with concrete mechanistic detail instead.

6. SPECIFY REGULATORY AND STANDARDS CONTENT: When the report references a regulation, policy, or technical standard by name, extract and present its specific quantitative thresholds, compliance timelines, key provision numbers, and operational requirements. Transform "GDPR requires data protection measures" into "GDPR Article 33 requires breach notification to supervisory authorities within 72 hours; Article 83 authorizes fines up to 20M EUR or 4% of global annual turnover." Draw on your knowledge of well-known regulations already mentioned in the report. When you are unsure of specific provision details, note the regulation's general operative requirements rather than guessing at numbers.

7. UPDATE STALE REFERENCE POINTS: Scan the report for data points, benchmarks, rankings, or scenario ranges that appear outdated relative to what you know. If the report presents already-surpassed levels as future targets, or uses older figures when more recent ones from the same domain are widely known, update them. For example, if the report cites a 2020 market size as current, and you know the 2023 figure, replace it. Flag any update you make by contextualizing it (e.g., "as of 2023, this figure has reached X, up from the Y cited in earlier analyses"). Do not fabricate precise figures you are uncertain about — instead note that the reference point may be outdated and frame the analytical implication.

8. BUILD CONSOLIDATED COMPARISON TABLES: Where the report compares multiple items (tools, methods, companies, policies, technologies) across scattered prose sections, create a single unified comparison table that consolidates all key dimensions side by side. Organize the table by the user's decision criteria or goal, not by the items themselves. Include a clear tiered recommendation or ranking row. If the report already has multiple overlapping ranked lists, merge them into one coherent hierarchy with explicit justification for the ordering.

9. STRENGTHEN CAUSAL REASONING: Where the report makes macro-level claims (e.g., "AI adoption is transforming healthcare"), connect them to specific micro-level mechanisms — the behavioral changes, technical processes, or economic dynamics through which the effect actually operates. For example: "AI-assisted radiology reduces diagnostic turnaround from 48 hours to under 1 hour by automating preliminary scan classification, allowing radiologists to focus on ambiguous cases." When the report notes that a historical relationship or core assumption has shifted or broken down, explicitly assess what this means for the report's overall conclusions rather than treating it as a footnote.

10. IMPROVE SOURCE QUALITY FRAMING: Where the report cites generic or secondary sources for entity-specific claims, note the type of primary source that would be most authoritative (e.g., "per the company's 10-K filing," "according to the FDA's 510(k) clearance database"). Do NOT fabricate citations or add fake reference numbers. Do reframe existing claims to indicate the caliber of evidence behind them. For example, transform "Company X has strong revenue growth [3]" into "Company X reported $12.4B in FY2023 revenue, up 18% year-over-year per its annual filing [3]" — enriching the claim while preserving the original citation.

CONTENT SOURCING RULES:
- You MUST preserve all existing factual content from the original report
- You MAY and SHOULD expand on topics already covered in the report with additional relevant context, examples, and explanations drawn from your knowledge, PROVIDED they are directly relevant to the report's existing subject matter
- Do NOT introduce entirely new topics or tangential discussions not connected to the report's scope
- When adding context from your knowledge, present it as established knowledge, NOT as new research findings
- Keep the same language as the original report (if the report is in Chinese, write expansions in Chinese; if English, write in English)
- DATA PROVENANCE: Do NOT invent specific numerical data (revenue figures, market sizes, growth rates, financial metrics) that are not already in the original report. You MAY restructure, tabularize, and synthesize data that IS in the report. You MAY add widely known public facts (e.g., company founding dates, headquarters locations, well-known product names). When the report has data gaps, improve the analytical framing around the gap rather than filling it with ungrounded estimates.

CITATION RULES:
- Preserve ALL existing citations, references, footnotes, and source links EXACTLY as they appear
- Do NOT remove, renumber, or modify any citation markers
- New sentences you add should NOT include fabricated citations — only original content retains its citations

LENGTH TARGET:
- The enhanced report should be approximately 50% longer than the original — no more, no less
- Do NOT produce a report that is more than 60% longer than the original
- Every section should feel complete and well-developed, not summarized
- Prioritize replacing weak content with strong content over adding bulk

ORIGINAL REPORT:
{article}"""


def create_client():
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise ValueError("NVIDIA_API_KEY environment variable is required")
    return OpenAI(
        api_key=api_key,
        base_url="https://inference-api.nvidia.com",
        default_headers={"anthropic-beta": "context-1m-2025-08-07"},
    )


def rewrite_article(client, article, max_retries=6):
    user_prompt = REWRITE_PROMPT.format(article=article)
    for attempt in range(max_retries):
        try:
            stream = client.chat.completions.create(
                model="aws/anthropic/bedrock-claude-opus-4-6",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert research report editor specializing in analytical depth, structural clarity, and evidence-based writing.",
                    },
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.6,
                max_tokens=128000,
                stream=True,
            )
            chunks = []
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta is not None:
                    chunks.append(delta)
            result = "".join(chunks)
            if len(result.strip()) < 100:
                raise ValueError(f"Response too short ({len(result)} chars)")
            return result
        except Exception as e:
            if attempt < max_retries - 1:
                wait = min(10 * (2**attempt), 120)
                print(f"  Retry {attempt + 1}/{max_retries} after error: {e} (waiting {wait}s)")
                time.sleep(wait)
            else:
                raise


def process_one(client, item, output_file, file_lock, done_ids, done_lock, min_ratio=0.9):
    item_id = item["id"]
    prompt = item["prompt"]
    article = item["article"]
    orig_len = len(article)

    try:
        rewritten = rewrite_article(client, article)
        new_len = len(rewritten)
        pct = 100 * (new_len - orig_len) / orig_len

        if new_len < orig_len * min_ratio:
            print(f"  ID {item_id}: REJECTED (truncated {pct:+.1f}%), keeping original")
            rewritten = article

        result = {"id": item_id, "prompt": prompt, "article": rewritten}

        with file_lock:
            with open(output_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            with done_lock:
                done_ids.add(item_id)

        status = "OK" if rewritten != article else "KEPT_ORIG"
        print(f"  ID {item_id}: {status} ({orig_len:,} -> {new_len:,}, {pct:+.1f}%)")
        return item_id, True

    except Exception as e:
        print(f"  ID {item_id}: FAILED - {e}")
        return item_id, False


def load_done_ids(output_file):
    done = set()
    if os.path.exists(output_file):
        with open(output_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        done.add(json.loads(line)["id"])
                    except (json.JSONDecodeError, KeyError):
                        pass
    return done


def main():
    parser = argparse.ArgumentParser(description="Batch rewrite articles with Claude Opus")
    parser.add_argument("input_file", help="Input JSONL file")
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output JSONL file (default: <input_dir>/rewritten/<input_name>)",
    )
    parser.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=10,
        help="Number of concurrent requests (default: 10)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.input_file):
        print(f"Input file not found: {args.input_file}")
        sys.exit(1)

    if args.output:
        output_file = args.output
    else:
        input_dir = os.path.dirname(args.input_file) or "."
        input_name = os.path.basename(args.input_file)
        output_dir = os.path.join(input_dir, "rewritten")
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, input_name)

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

    all_items = []
    with open(args.input_file, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                all_items.append(json.loads(line))

    done_ids = load_done_ids(output_file)
    to_process = [item for item in all_items if item["id"] not in done_ids]

    print(f"Input:       {args.input_file} ({len(all_items)} articles)")
    print(f"Output:      {output_file}")
    print(f"Already done: {len(done_ids)}")
    print(f"To process:  {len(to_process)}")
    print(f"Concurrency: {args.concurrency}")
    print()

    if not to_process:
        print("Nothing to do.")
        return

    client = create_client()
    file_lock = threading.Lock()
    done_lock = threading.Lock()
    succeeded = 0
    failed = 0
    failed_ids = []

    try:
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {
                executor.submit(
                    process_one,
                    client,
                    item,
                    output_file,
                    file_lock,
                    done_ids,
                    done_lock,
                ): item
                for item in to_process
            }
            with tqdm(total=len(to_process), desc="Rewriting", unit="article") as pbar:
                for future in as_completed(futures):
                    item_id, ok = future.result()
                    if ok:
                        succeeded += 1
                    else:
                        failed += 1
                        failed_ids.append(item_id)
                    pbar.set_postfix(ok=succeeded, fail=failed)
                    pbar.update(1)
    except KeyboardInterrupt:
        print("\n\nInterrupted! Waiting for in-flight requests to finish saving...")
        executor.shutdown(wait=False, cancel_futures=True)

    total_done = len(load_done_ids(output_file))
    print(f"\nDone. Succeeded: {succeeded}, Failed: {failed}, Total in output: {total_done}/{len(all_items)}")
    if failed_ids:
        print(f"Failed IDs (will be retried on next run): {sorted(failed_ids)}")
    if total_done < len(all_items):
        print(f"Re-run the same command to retry {len(all_items) - total_done} remaining articles.")


if __name__ == "__main__":
    main()
