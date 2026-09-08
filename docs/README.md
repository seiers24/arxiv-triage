# arxiv-triage documentation

Start here. `AGENTS.md` at the repo root constrains agents; this folder explains
the system. Where they overlap, this folder wins.

## Contents
- `schema.md` — the record and verdict schema (the contract between scripts and agents)
- `decisions.md` — design decisions with the alternative considered
- `evaluation.md` — how output quality is checked (golden set, rubric, critic accuracy)
- `roles/orchestrator.md` — human-readable authority and boundaries for the main orchestrator
- `planning/full-text-pipeline-plan.md` — implementation plan for abstract screening and HTML/PDF/abstract source fallback
- `future_extensions.md` — deliberately deferred capabilities

## Why this design
- Deterministic steps are scripts; only reading, extraction, and critique use a model.
- One orchestrator with bounded, role-specific workers and one-level
  delegation. Easy to trace and evaluate.
- Every claim carries an arXiv ID and a verdict. Unresolved items are shown, not dropped.

## Next steps (deliberately not built)
- Vector store for cross-run retrieval
- Knowledge graph of techniques, claims, and hardware assumptions
- Productization outside Claude Code (LangGraph or the Claude Agent SDK)
