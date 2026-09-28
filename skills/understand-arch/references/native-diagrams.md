# Official native diagram authoring

Use this path for a diagram type outside [typed IR v2](diagram-view-ir.md). Choose the view from the question, follow that engine's current [Mermaid](https://mermaid.js.org/intro/syntax-reference.html), [PlantUML](https://plantuml.com/), [draw.io](https://www.drawio.com/docs/diagram-types/), or [Archify](https://github.com/tt-a1i/archify/blob/c826e6c3a7abad19c0f3cd1ca57207d54b1ad8de/archify/schemas/README.md) syntax/schema, and write its editable native file. The official engine's actual parser and exporter determine whether the requested type and output are supported by the installed version. draw.io is an open shape language; its gallery is guidance, not an exhaustive type enum.

## Source-based work

1. Read the user's question and choose a semantic view before choosing an engine. A class diagram answers type structure, an activity/flowchart answers branching steps, a state diagram answers lifecycle transitions, a sequence diagram answers time ordered interactions, and an architecture diagram answers system boundaries and dependencies. Use the official notation; do not relabel a generic flowchart as a different standard.
2. Gather code evidence with CodeGraph when an index exists, then verify the current files. Create each element and relationship from a cited fact or an explicitly marked inference. Omit unsupported details; call out ambiguities.
3. Author a native `.mmd`, `.puml`, `.drawio`, or Archify typed `.json` in the work directory. Create a **version 2** evidence manifest. Each material statement needs a `statement`, a verbatim `artifactQuote` within its `artifactRef`, a provenance label, and at least one exact source anchor. Use multiple anchors for inferred cross-file relationships. For Mermaid and PlantUML, `artifactRef` is `line:<one-based source line>`; for draw.io it is `cell:<mxCell id>`; for Archify it is a JSON pointer such as `/components/0` or `/connections/0`. The validator requires every material line, cell, or typed item to have a claim. Decorative text cells and common syntax/style directives are excluded. A material line containing multiple facts still needs separate human semantic review.
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

`--source-repo` and `--evidence` are a pair. The validator checks the engine, manifest shape, declared type, material item coverage, source path containment, one based line, and exact source quote before writing output. `EXTRACTED` statements must occur literally on cited source lines; use `INFERRED` for translated names or architectural interpretations. The receipt reports `claimCoverage: complete` only for version 2. Version 1 manifests remain readable but report `claimCoverage: not_checked`. This inventory does not parse every native grammar or prove that an inferred arrow is the right business interpretation. The official engine checks syntax/rendering; the agent checks semantics and the exported image. For a diagram unrelated to source code, omit both source flags and say that code evidence was not checked.
