# Business analysis brief

## Problem and stakeholders

This is a reproducible analyst pilot. The historical retailer is not a client and has not provided stakeholder interviews or internal operating procedures.

| Role | Need | Acceptance responsibility |
| --- | --- | --- |
| Analyst (owner playing the role) | Prepare consistent reports and investigate exceptions efficiently | Correct figures, traceability and usable commentary |
| Reviewer (owner or a consenting participant) | Approve the exact content and follow-up action | Decision clarity, accountability and no unapproved publication |
| Operator/developer | Run, diagnose and recover the system | Installation, security and failure recovery |
| Portfolio reviewer | Assess skills and reproduce the result | Clear evidence, limitations and setup |

The owner owns scope, KPI definitions and acceptance. Codex supports implementation and testing; it does not substitute for stakeholder evidence or measured human work.

## AS-IS manual procedure

For a given archive snapshot and date range: load the records, check validity/completeness, classify adjustments, calculate KPIs, compare a valid prior period, inspect relevant records, write a summary, review it, save the final report and record a follow-up item. Time this actual procedure. Its duration is unknown before measurement.

## TO-BE

A request invokes n8n. Deterministic validation/SQL creates the evidence bundle and report. Optional AI drafts bounded commentary. A human checks the report, approves/rejects the exact revision, and the system publishes and audits the authorized action. Exceptions and unavailable services route to a defined recovery/manual path.

Create actual AS-IS and TO-BE BPMN 2.0 files in v0.1. Include analyst/reviewer/system lanes, start/end events, quality and approval gateways, timeout, rejection and recovery. A Mermaid flowchart is an architecture aid, not evidence of BPMN compliance.

## User stories

| ID | Story | Primary acceptance |
| --- | --- | --- |
| US-01 | As an analyst, I can request an explicit period on a known snapshot so results are reproducible | AC-02, AC-04, AC-06 |
| US-02 | As an analyst, I can inspect source and policy evidence behind a number | AC-05, AC-22 |
| US-03 | As a reviewer, I can reject or approve only the current report revision | AC-11 through AC-15 |
| US-04 | As an operator, I can identify and recover a failed case without duplicate publication | AC-16 through AC-23 |
| US-05 | As an evaluator, I can compare manual, deterministic and AI-assisted work fairly | AC-25 |
| US-06 | As a portfolio reviewer, I can run the demo and understand its limitations | AC-24, AC-26, AX-07 |

## Requirements discovery questions

What report decision is supported? Which KPIs and exclusions are acceptable? What is the period/cadence? What must a reviewer verify? Which errors invalidate a report? What level of manual review is acceptable? Which account owns the final action? What data may be published? What is the existing manual method? Which costs and volumes are observed versus assumed?

Answer with actual observations or explicit scenario assumptions. Do not invent stakeholder quotes. Keep decisions, questions and changes in a dated log.

## Prioritisation and rules

Core: correct data/metrics, source evidence, approval, recovery and measurements. Next: tools/RAG/MCP and relevant connectors. Experiments: alternate orchestrators/databases and heavy infrastructure.

Model decision rules in a small versioned table first: invalid evidence -> manual review; invalid model output -> repair once then manual review; changed/expired approval -> no action; duplicate event -> return existing case; uncertain write -> reconciliation. A later DMN artifact must agree with executable tests.

## Portfolio narrative

Explain the business problem, requirements, design, implementation, reliability and measured effect in that order. List only demonstrated technologies as implemented skills. Describe the use of AI assistance and actual author contribution candidly.
