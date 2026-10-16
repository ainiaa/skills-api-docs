# Official native diagram authoring

Use this path for a diagram type outside [typed IR v2](diagram-view-ir.md). Choose the view from the question, follow that engine's current [Mermaid](https://mermaid.js.org/intro/syntax-reference.html), [PlantUML](https://plantuml.com/), [draw.io](https://www.drawio.com/docs/diagram-types/), or [Archify](https://github.com/tt-a1i/archify/blob/1c2b42d660e4a7571813fb43839c79e3e9ca7720/archify/schemas/README.md) syntax/schema, and write its editable native file. The official engine's actual parser and exporter determine whether the requested type and output are supported by the installed version. draw.io is an open shape language; its gallery is guidance, not an exhaustive type enum.

## Archify 3.1.0 native types

All ten typed modes are accepted: `architecture`, `workflow`, `sequence`, `dataflow`, `lifecycle`, `erd`, `tree`, `class`, `timeline`, and `waterfall`. Set `schema_version: 1`, the exact `diagram_type`, `meta.title`, and a portable relative `meta.output` ending in `.html`. Use the corresponding installed official schema and examples; schema and relationship validation remain the official CLI's responsibility. This path does not add an IR v2 converter or imply exchange-format conformance.

| New type | Meaning and authored fields | Material evidence pointers |
| --- | --- | --- |
| `erd` | Entities and attributes, with relationships carrying both endpoint cardinalities | `/entities/0`, `/relationships/0` |
| `tree` | Containment hierarchy; each node has at most one `parent`, not a call graph | `/nodes/0` (including its parent relation) |
| `class` | `types` with kind, attributes and methods; typed `relationships` such as realization or dependency | `/types/0`, `/relationships/0` |
| `timeline` | Offset-bearing ISO 8601 `events[].at`, optional `lanes`, and `meta.timezone` for display | `/lanes/0`, `/events/0` |
| `waterfall` | Relative `spans[].start` and `end` or `duration`, optional parent; consistent `meta.unit` (`us`, `ms`, `s`) | `/spans/0` (including timing and parent relation) |

The five new modes require a non-empty primary collection (`entities`, `nodes`, `types`, `events`, or `spans`); missing or malformed collections fail inventory. Each material array item must be claimed, including optional arrays when present. An entity/type claim includes its nested attributes/methods; separately review every fact within it. Parent references, timing and lane membership are part of their node/event/span item, not separate pointers. Workflow and lifecycle main-path entries require `/mainPath/0`, `/mainPath/1`, etc.; their order is part of the declared path. Workflow semantic constraints require item pointers such as `/semanticChecks/allowedRoots/0`, `/semanticChecks/allowedTerminals/0`, `/semanticChecks/requiredEdges/0`, and `/semanticChecks/requiredPaths/0`. All ten modes also inventory optional explanation cards as `/cards/0`, `/cards/1`, etc.; card text can contain source claims and must be covered along with structural items. Empty or absent optional relationships/lanes/cards introduce no material items. Evidence coverage proves anchors and item coverage, not the meaning of each nested fact.

For timeline, explicitly set `meta.evidence` to `observed` or `illustrative`; for waterfall use `measured` or `illustrative`. Recorded times and durations require event-log or trace evidence, including the timezone/offset and unit. Source code alone does not establish observed ordering, timestamps or latency. Preserve supplied offsets and units, label illustrative values, and request missing observations when actual timing is required. Overlapping spans and a parent containing its children are not additive latency. Keep this timing evidence in the item claims when using the source flags below.

Native modes deliver editable JSON and interactive HTML; repeat `--export` for `svg`, `png`, `jpg`, `webp`, `pdf`, or `webm`. Set `meta.animation: "trace"` when an animated WebM is intended. `--repo-root` remains specific to architecture; use `--source-repo` with `--evidence` for source-backed diagrams of any type.

```bash
python3 scripts/render_native_diagram.py \
  --engine archify --input /tmp/orders.erd.json --output /tmp/orders-erd \
  --source-repo /path/to/repo --evidence /tmp/orders.evidence.json \
  --export png --export svg
```

## Source-based work

1. Read the user's question and choose a semantic view before choosing an engine. A class diagram answers type structure, an activity/flowchart answers branching steps, a state diagram answers lifecycle transitions, a sequence diagram answers time ordered interactions, and an architecture diagram answers system boundaries and dependencies. Use the official notation; do not relabel a generic flowchart as a different standard.
2. Gather code evidence with CodeGraph when an index exists, then verify the current files. Create each element and relationship from a cited fact or an explicitly marked inference. Omit unsupported details; call out ambiguities.
3. Author a native `.mmd`, `.puml`, `.drawio`, or Archify typed `.json` in the work directory. Create a **version 2** evidence manifest. Each material statement needs a `statement`, a verbatim `artifactQuote` within its `artifactRef`, a provenance label, and at least one exact source anchor. Use multiple anchors for inferred cross-file relationships. For Mermaid and top-level PlantUML, `artifactRef` is `line:<one-based source line>`; a local PlantUML `!include`, selected block (`file!0`/`file!ID`), or `!includesub` uses `include:<relative-path>:line:<one-based line>` for the selected content and is copied into the deliverable. For draw.io it is `cell:<mxCell id>`; for Archify it is a JSON pointer such as `/components/0` or `/connections/0`. The validator requires every inventoried material line, cell, or typed item to have a claim. Decorative text cells and common syntax/style directives are excluded. A material line containing multiple facts still needs separate human semantic review.
4. Run the official validator/exporter, inspect the image, then fix syntax, scope, labels, edges, and layout. Repeat until the actual output is readable. Deliver the editable native file, requested export(s), evidence manifest, and any unresolved interpretation.

Example `diagram.evidence.json`:

```json
{
  "version": 2,
  "engine": "mermaid",
  "diagramType": "class",
  "claims": [
    {
      "statement": "Asset is a declared type",
      "artifactRef": "line:2",
      "artifactQuote": "class Asset",
      "provenance": "INFERRED",
      "evidence": [{"path": "src/Asset.java", "line": 8, "quote": "class Asset"}]
    }
  ]
}
```

```bash
python3 scripts/render_native_diagram.py \
  --engine mermaid --input /tmp/classes.mmd --output /tmp/classes \
  --source-repo /path/to/repo --evidence /tmp/diagram.evidence.json \
  --export png
```

`--source-repo` and `--evidence` are a pair. The validator checks the engine, manifest shape, declared type, material item coverage, source path containment, one based line, and exact source quote before writing output. `EXTRACTED` statements must occur literally on cited source lines; use `INFERRED` for translated names or architectural interpretations. Version 2 reports `claimCoverage: complete` only when every inventoried item is claimed and no PlantUML include remains untracked. Standard-library, remote, or out-of-directory includes report `partial` with `untrackedIncludes`; inspect their effective content or use self-contained syntax before claiming complete coverage. Version 1 reports `not_checked`. This inventory cannot prove an inferred arrow or all facts sharing one native line. Invalid diagram-type and evidence-manifest scalar fields fail validation before output is written. A failed Archify delivery removes any partial HTML; a viewer-export failure may retain the already validated JSON/HTML and reports the failed export separately. The official engine checks syntax/rendering; the agent checks semantics and the exported image. For a diagram unrelated to source code, omit both source flags and say that code evidence was not checked.
