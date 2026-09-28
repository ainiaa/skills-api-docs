# Typed diagram view IR v2

Use IR v2 for new source-based diagrams whose profile is listed here. Use [official native authoring](native-diagrams.md) for other official diagram types. IR v1 remains readable for previously generated artifacts but is not the default for new architecture work. Each file represents **one diagram view**. Run the CLI separately for overview and detailed views; do not merge unrelated questions onto one canvas.

```json
{
  "version": 2,
  "profile": "c4-component",
  "title": "FA 资产模块组件架构",
  "scope": {"system": "FMS", "container": "fms-ce-service"},
  "elements": [
    {
      "id": "asset_api", "type": "component", "name": "资产事件接口",
      "description": "接收资产事件", "technology": "Spring MVC", "band": "entry",
      "provenance": "INFERRED",
      "evidence": [{"path": "src/AssetController.java", "line": 12, "quote": "assetService.receive"}]
    }
  ],
  "relations": []
}
```

`evidence` always uses a path relative to the analysed repository, a one-based line number, and a verbatim substring of that line. Every element and relation needs evidence and `EXTRACTED`, `INFERRED`, or `AMBIGUOUS` provenance. Graph IDs may help find evidence, but must not appear as visible diagram labels.

## Profiles

| `profile` | Element `type` | Relation-specific fields | Supported engines |
| --- | --- | --- | --- |
| `architecture-landscape` | `actor`, `entrypoint`, `service`, `adapter`, `database`, `cache`, `coordination_store`, `external_system` | required `kind`: `primary`, `secondary`, `dependency` | drawio |
| `c4-context` | `person`, `software_system`, `external_system` | `technology` optional | drawio, plantuml, mermaid (experimental C4 syntax) |
| `c4-container` | `person`, `software_system`, `container`, `external_system` | `technology` for container-to-container communication | drawio, plantuml, mermaid (experimental C4 syntax) |
| `c4-component` | `person`, `component`, `container`, `software_system`, `external_system` | `scope.container` required | drawio, plantuml, mermaid (experimental C4 syntax) |
| `uml-sequence` | `participant` | `order` (unique positive integer), `kind`: `call`, `async`, `return` | plantuml, mermaid, drawio |
| `bpmn-process` | `start_event`, `task`, `exclusive_gateway`, `parallel_gateway`, `end_event` | each element has `pool` and `lane`; each relation `kind`: `sequence` or `message` | drawio visual notation |
| `erd` | `entity` | `fromCardinality`, `toCardinality`: `1`, `0..1`, `0..*`, `1..*` | mermaid, plantuml, drawio |

C4 elements need `description`; components and containers also need `technology`. The optional `band` changes draw.io layout, not C4 meaning: `entry`, `application`, `integration`, `storage`, `external`. Choose it from actual responsibility. A C4 component view describes one container and needs at least one component inside it. A C4 container view needs at least one container inside the system. Supporting elements may show direct dependencies outside the scope. Do not place raw database tables or methods as C4 components.

`architecture-landscape` is an overview convention for code-derived architecture when the user has not asked for strict C4. It displays source-backed entrances, an editable `scope.container` boundary around services and adapters, and a combined data/external dependency row. Node role controls native draw.io shape and color; relation `kind` controls red primary, blue secondary, or dashed orange dependency lines. Numbers on edges refer to a relation register with the full label and endpoints, keeping the canvas readable. `status: planned` is optional and requires direct evidence; never copy planned elements from a reference diagram into a code-derived view. A landscape needs concise `name` and `description` text, at most 12 elements and 12 relations. If larger, create an overview and focused views; do not omit evidence-backed details without a companion view. This profile is only supported by draw.io and does not claim C4 conformance.

Sequence messages must be ordered. BPMN sequence flow may cross lanes within one pool but cannot cross pools; message flow connects different pools. The implemented BPMN subset does not claim executable BPMN XML conformance. An ERD entity may have `fields: [{"name":"id","type":"bigint","key":"PK"}]`; keys may be `PK`, `FK`, `UK`, or omitted. Only assert cardinality when repository evidence establishes it; if it does not, explain the gap instead of guessing.

The draw.io sequence renderer creates editable participant headers, lifelines, and ordered call/async/return messages, including self-messages. Activation bars and UML combined fragments (`alt`, `loop`, etc.) are not yet represented by IR v2 or this renderer.

Unsupported profile/engine combinations fail. The CLI's `rendererChecks` checks official engine parsing and export only. Inspect each exported image before delivery; if labels, arrows, or boundaries are unclear, split or revise the view and render again.
