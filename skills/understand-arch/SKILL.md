---
name: understand-arch
description: Generate evidence-anchored system architecture IR and Mermaid, PlantUML, draw.io, and Archify artifacts from a source repository. Use for architecture diagrams or business-domain overviews, not endpoint API documentation.
---

# Understand Arch

Produce an auditable architecture overview from a repository. The agent interprets business domains; the scripts inventory source evidence, reject invalid references, and compile diagrams. Keep generated files outside the analyzed repository unless the user asks to commit them.

## Workflow

1. Resolve this skill's real directory. The CLI is `../../scripts/generate_architecture.py` relative to that directory. Run `python3 <cli> context --source <repo> --output <workdir>/context.json`.
2. Inspect the complete context. `files`, `symbols`, `routes`, `configKeys`, and `tables` are never capped; symbol and route scans are candidates to verify, not parser proof. If `.codegraph/` exists, use CodeGraph for navigation before broad text searches. If `knowledgeGraph` exists, use its node IDs and relationships for navigation; if `domainGraph` exists and no freshness warning applies, use its domain and flow names as the primary semantic draft. Domain graph descriptions remain LLM claims, not direct code evidence. For a large context, query its arrays by module and inspect source files as needed; do not silently discard modules.
3. Write `<workdir>/architecture-ir.json` using [the IR contract](references/architecture-ir.md). Cite exact source path, one-based line, and a verbatim substring for every domain, capability, class, table, external system, and relation. Mark direct source facts `EXTRACTED`; business interpretations `INFERRED`; unresolved/conflicting claims `AMBIGUOUS`. Keep labels short for diagrams.
4. Run `python3 <cli> validate --source <repo> --ir <workdir>/architecture-ir.json`. Repair the reported assertions and validate again. Never remove a rejected assertion silently. If a supported interpretation cannot be established, keep it `AMBIGUOUS` and explain the limitation to the user.
5. Run `python3 <cli> render --source <repo> --ir <workdir>/architecture-ir.json --output <workdir>/architecture`. The CLI writes the validated IR, Mermaid, PlantUML, draw.io XML, and Archify schema-v1 JSON. When the official `archify` executable is available, it also renders HTML. Report its warning if the executable is absent or rejects the adapter output.

The source-line check proves that a cited snippet exists at that location. It does not prove a business interpretation, runtime route, or relationship. Review `INFERRED` and `AMBIGUOUS` claims against multiple code paths before presenting them as conclusions.
