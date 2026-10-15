# Architecture IR v1

The skill writes JSON with this shape. Domain IDs use letters, digits, and underscores, starting with a letter. Paths are relative to the analyzed repository; line numbers start at 1. `quote` must occur verbatim on that source line.

```json
{
  "version": 1,
  "summary": "订单服务按业务域组织，通过 HTTP 提供下单能力。",
  "domains": [{
    "id": "orders",
    "name": "订单",
    "responsibility": "接收并处理订单请求",
    "provenance": "INFERRED",
    "evidence": [{"path": "src/OrderController.java", "line": 2, "quote": "class OrderController"}],
    "capabilities": [{"text": "创建订单", "provenance": "INFERRED", "evidence": [{"path": "src/OrderController.java", "line": 3, "quote": "createOrder"}]}],
    "keyClasses": [{"name": "OrderController", "provenance": "EXTRACTED", "evidence": [{"path": "src/OrderController.java", "line": 2, "quote": "class OrderController"}]}],
    "tables": []
  }],
  "externalSystems": [],
  "relations": []
}
```

- A table entry has `name`, `provenance: "EXTRACTED"`, and `evidence` pointing to its declaration or mapping.
- An external system entry has `name`, `kind`, `via` (non-empty client class names), `domain` (owning domain ID), `provenance`, and `evidence`. Include the client declaration in its evidence.
- A relation entry has `from` and `to` domain IDs, `label`, `provenance`, and `evidence` supporting the interaction.
- `EXTRACTED` means a literal fact exists in cited source. `INFERRED` means an interpretation backed by cited source. `AMBIGUOUS` preserves uncertainty; do not hide it in the diagram summary.
- Reuse current domain-graph names and flows when they agree with source. If its commit differs from the repository or the relevant source is changed, treat it as a lead to verify, not authority.
