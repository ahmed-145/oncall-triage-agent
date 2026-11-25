# PRD: oncall-triage-agent, an incident triage agent for Kubernetes services

- **Owner:** Ahmed Mahmoud Abbas (software engineer targeting backend, DevOps and SRE roles)
- **Status:** Draft v1 (Nov 25, 2026)
- **Build time:** about 4 to 5 weeks at 10 to 15 h/week. Cut list in section 9 if time runs short.
- **Budget:** $0 (local Kubernetes via kind or k3d, Prometheus, Grafana, Loki, free LLM tier or local Ollama, GitHub Actions free minutes)
- **Related repo:** `essi-mcp` (same owner). Build that first; this repo reuses the MCP tool-building skills from it.


## 0. Summary for a reader with no context

**What it is.** A demo system plus an AI agent that investigates incidents. A small web shop runs on a local Kubernetes cluster. When something breaks, an alert fires, and the agent gathers evidence (metrics, logs, cluster events, recent deploys), ranks the likely root causes and writes an incident report with a proposed next step. A human approves any fix. The agent changes nothing by itself.

**The problem.** When a production service breaks, on-call engineers lose their first 10 to 30 minutes jumping between dashboards, logs and cluster commands to work out what is wrong. This is repetitive, error-prone work, especially at 3 a.m. Teams want AI help here, but an agent that can run commands in production is dangerous, and most AI demos never measure whether the agent is actually right.

**The solution.** A triage agent built around three ideas: (1) read-only tools only, with a human approval gate for any action; (2) deterministic rules first, with the LLM refining and explaining on top, so the agent still works when the model is down or wrong; (3) an evaluation harness that scores the agent against known injected faults and publishes the measured results, including failures.

**Who it is for.**
1. Small teams and on-call engineers who want a safe starting point for AI-assisted incident response.
2. Hiring managers and engineers reviewing the owner's portfolio for junior backend, DevOps or SRE roles. The repo is designed to show the full loop: services, containers, Kubernetes, monitoring, alerting, an agent with guardrails, and honest evaluation.

**Terms.** Kubernetes (k8s): system that runs containers. kind/k3d: tools that run a Kubernetes cluster inside Docker on a laptop. Prometheus: metrics and alert rules. Alertmanager: sends alerts to webhooks. Loki: log storage. Grafana: dashboards. LangGraph: Python framework for building agent workflows as graphs. MCP: standard for exposing tools to AI agents. RBAC: Kubernetes permissions. Root cause: the underlying reason an incident happened. Runbook: documented steps to handle a known problem.

## 1. Why this exists

Target roles: junior backend, DevOps, SRE, with AI as the differentiator. Most junior portfolios show a CRUD app or a chatbot. This repo shows the actual SRE loop: a service breaks, an alert fires, evidence is gathered, a cause is ranked, a human approves a fix. It builds on the owner's earlier work: a containerized URL shortener with monitoring, and a code-analysis project (ACR-QA) built on the idea that deterministic checks come first and the LLM is used only where it adds value.

What it proves to a recruiter:
- Backend: FastAPI services, Postgres, Redis, tests, clean API design.
- DevOps/SRE: Docker, Kubernetes manifests, CI, Prometheus alerts, Grafana, logs, runbooks.
- AI engineering: an agent with bounded tools, a human approval gate, and an evaluation harness with measured results.

## 2. Goals

- A small demo system ("shop": API, worker, Postgres, Redis) running on a local Kubernetes cluster with metrics, logs and alerts.
- A fault injection kit that breaks it in 8 to 10 known ways.
- A triage agent that receives an Alertmanager webhook, collects evidence through read-only tools, ranks likely root causes, and writes an incident report.
- An evaluation harness that scores the agent against the known faults and reports real numbers.
- Everything reproducible with one `make demo`.

## 3. Non-goals

- No autonomous remediation. The agent only proposes; a human approves any change, and v1 executes nothing mutating.
- No cloud accounts, no paid APIs, no multi-cluster, no real production traffic.
- No custom LLM training.

## 4. System overview

```
shop (FastAPI + worker + Postgres + Redis) on kind
   -> Prometheus + Loki -> Alertmanager --webhook--> triage-agent (FastAPI)
triage-agent: LangGraph graph
   ingest alert -> collect evidence -> hypothesize -> rank -> propose runbook step -> approval gate -> report
tools (own MCP server, read-only): query_prometheus, query_logs, k8s_get/describe/events, recent_deploys
report -> markdown file + GitHub issue (optional) + metrics about the agent itself
```

## 5. Functional requirements

P0
- Shop services with health endpoints, Prometheus metrics, structured JSON logs.
- Alert rules: high error rate, high latency (P95), pod crash loop, memory near limit, DB connections exhausted.
- Fault kit: `faultctl inject <name>` and `faultctl clear`. Faults: bad deploy (5xx), slow query, DB connection leak, OOM kill, crash loop from bad config, Redis down, dependency timeout, noisy neighbor CPU throttle.
- Agent tools are read-only and allowlisted. No shell passthrough. Arguments validated.
- A deterministic rules engine runs first (for example an OOMKilled event maps to a memory limit problem). The LLM refines and explains; if the LLM is down, the rules engine alone still produces a report.
- Report contains: summary, timeline, evidence with links to the exact queries, ranked hypotheses with confidence, proposed next step, what was NOT checked.
- Approval gate: the proposed action is written as a command plus rollback, waiting for a human yes. v1 only prints it.

P1
- Agent observability: metrics for tool calls, latency, token use, failures; traces for each investigation.
- Prompt-injection hardening: log lines and alert labels are treated as untrusted data. Add a test where a log line tries to instruct the agent and the agent ignores it.
- Replay mode: run an investigation from saved evidence so tests need no cluster and no LLM.

P2
- Runbook retrieval from a folder of markdown runbooks the owner writes.
- A Grafana dashboard for agent results.

## 6. Evaluation (the part recruiters remember)

- 8 to 10 scenarios with a ground-truth root cause each.
- Metrics: top-1 and top-3 root cause accuracy, time from alert to report, tool calls per investigation, token cost, and false-confidence rate (confident but wrong).
- Compare three modes: rules only, LLM only, rules plus LLM. Report all three honestly, including where the agent fails.
- Publish only measured numbers, with the command that reproduces them. No target numbers presented as results.

## 7. Technical choices

- Python 3.12, FastAPI, LangGraph, pydantic, pytest, ruff, mypy. Verify current LangGraph API docs before starting; it changes often.
- LLM: a free-tier provider (Gemini, Groq) or local Ollama, behind one small interface so it can be swapped. Keep the key in env, never in the repo.
- Kubernetes: kind or k3d, plain manifests with kustomize. Read-only ServiceAccount for the agent (RBAC with get, list, watch only). Show the RBAC file in the README.
- CI: lint, type check, unit tests, replay-mode eval on every push. Full cluster eval is a manual `make eval`.
- Reuse the MCP SDK experience from `essi-mcp` for the tool layer.

## 8. Milestones

| # | Milestone | Done when | Time |
|---|---|---|---|
| M0 | Repo, CI, Makefile, kind cluster script | `make cluster` works from a clean clone | 6 h |
| M1 | Shop services with metrics and logs, deployed to kind | dashboards show live traffic | 10 h |
| M2 | Prometheus, Loki, Alertmanager, alert rules, fault kit | each fault triggers its alert | 10 h |
| M3 | Agent v0: webhook, read-only tools, rules engine, report file | report produced for 3 faults without any LLM | 12 h |
| M4 | LangGraph flow with LLM refinement, approval gate, prompt-injection test | report quality beats rules-only on at least some scenarios | 12 h |
| M5 | Evaluation harness, replay mode, measured results table in README | `make eval` prints the table | 8 h |
| M6 | Agent observability, README with architecture diagram, 2 min demo video, decisions and limits section | a stranger can run the demo | 8 h |

Total about 66 h. At 12 h/week that is roughly 5 to 6 weeks, so use the cut list.

## 9. Cut list if time runs short (cut in this order)

1. Runbook retrieval and the Grafana agent dashboard (P2).
2. Agent traces (keep metrics).
3. Half the faults (keep 5: bad deploy, OOM, crash loop, DB connections, Redis down).
Do not cut: the rules engine, the approval gate, the evaluation table, the injection test.

## 10. Definition of done

- `make demo` brings everything up; `faultctl inject oom` produces a report within a minute.
- README has the architecture diagram, the measured eval table, limits, and a "what I would do next" list.
- The owner can explain every component and design choice without notes. The decisions log is written by hand as the project goes; it doubles as interview preparation.

## 11. Risks

- Scope. This would be the owner's largest project. Ship M0 to M3 first; that already stands on its own.
- Laptop resources: kind plus Prometheus plus Loki is heavy. Set resource limits early; consider k3d and a trimmed stack.
- LLM free-tier rate limits. Replay mode and the rules engine keep the project alive without them.
- Framework churn (LangGraph). Pin versions.
- Honesty: do not claim autonomous remediation or production use. It is a triage assistant over a demo system.
