# AI and retrieval evaluation

This is the original evaluation design, including proposed held-out, baseline and
broader retrieval experiments. Those proposals are not measured results. The
implemented offline eight-case replay and its limits are documented in the
[evaluation report](AI_EVALUATION_REPORT.md); subsequent local live checks are in
[initial evidence](../evidence/p6_live_validation.json) and
[completed Combined checks](../evidence/p6_combined_repair.json).

## v0.1 commentary

The model reads only bounded validated metrics and evidence. Evaluate schema validity, exact metric references, numerical consistency, unsupported claims, appropriate abstention and human usefulness. Compare its commentary with the deterministic template using the same report requirements. A model-generated judgment is a helper, not the only ground truth.

Keep separate development and held-out cases. Freeze prompt, model/revision, context budget, decoding options and validator before the final run. Save failures as well as successes. The ten-case G0/v0.1 trials are feasibility checks, not a broad benchmark.

## v0.2 agent

Evaluate actual tool selection and argument correctness, unauthorized-tool rejection, evidence retrieval, step limits, recovery and task completion. A hardcoded tool call cannot be counted as model-driven tool calling. Use the same deterministic permissions in every agent experiment.

## RAG admission and corpus

A small stable policy set may fit directly in a prompt. Keep that as a baseline. Candidate tasks include locating the correct version of a KPI rule and answering product questions using real product codes/descriptions plus relevant transaction evidence. Product similarity alone is semantic search, not proof of a useful generative RAG system.

Start with real permitted source material and clearly labelled project-authored policy documents. For each item record origin, license/access, fetched time, hash, valid period, parser/chunk settings, source locator and embedding version. Do not invent merchant policies.

Compare keyword/full-text, full-context where feasible, vector, hybrid and optional reranking under the same frozen questions and resource budget. GraphRAG is admitted only if relationship-based questions expose a measurable gap in the simpler baseline. Similar descriptions never authorize merging StockCode identities.

## Evaluation set

Define expected answer/evidence before examining held-out outputs. Include absent answers, ambiguous products, changes/deletions, stale rules and hostile text. Report n and coverage. Twenty-five RAG questions are a small diagnostic set, not an assurance of broad accuracy.

Measures: retrieval recall/precision at declared k where labels exist, source correctness, answer support, abstention, latency and memory. Reranking/another vector store must change one experimental factor at a time. Account for correlated questions in uncertainty estimates.

## Tools

A small Python evaluator and human-reviewed examples are sufficient initially. Ragas is an optional adapter with explicitly configured local models; never activate a default paid judge/provider. Langfuse is an optional tracing profile after the lightweight evidence schema works.
