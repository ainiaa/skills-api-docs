"""Deterministic renderers for the validated architecture IR."""

from html import escape as xml_escape


def _mermaid(value):
    return str(value).replace("\\", "/").replace('"', "'").replace("\n", " ").replace("\r", " ").replace("<", " ").replace(">", " ").replace(";", " ").replace("`", " ")


def _plantuml(value):
    return str(value).replace('"', "'").replace("\n", " ").replace("\r", " ").replace(";", " ").replace("{", "(").replace("}", ")")


def render_mermaid(ir):
    lines = ["flowchart LR", '  subgraph SYSTEM["' + _mermaid(ir["summary"]) + '"]']
    for domain in ir["domains"]:
        domain_id = "D_" + domain["id"]
        capabilities = "<br/>".join("· " + _mermaid(item["text"]) for item in domain["capabilities"])
        lines.append(f'    {domain_id}["{_mermaid(domain["name"])}<br/>{capabilities}"]')
        for index, table in enumerate(domain["tables"]):
            table_id = f'{domain_id}_T{index}'
            lines.append(f'    {table_id}[("{_mermaid(table["name"])}")]')
            lines.append(f"    {domain_id} --> {table_id}")
    lines.append("  end")
    for index, external in enumerate(ir["externalSystems"]):
        lines.append(f'  E{index}["{_mermaid(external["name"])}"]')
        lines.append(f'  D_{external["domain"]} -.->|"{_mermaid(external.get("kind", "external"))}"| E{index}')
    for relation in ir["relations"]:
        lines.append(f'  D_{relation["from"]} -->|"{_mermaid(relation["label"])}"| D_{relation["to"]}')
    return "\n".join(lines) + "\n"


def render_plantuml(ir):
    lines = ["@startuml", "title " + _plantuml(ir["summary"])]
    for domain in ir["domains"]:
        capabilities = "\\n".join(_plantuml(item["text"]) for item in domain["capabilities"])
        label = _plantuml(domain["name"]) + ("\\n" + capabilities if capabilities else "")
        lines.append(f'component "{label}" as D_{domain["id"]}')
        for index, table in enumerate(domain["tables"]):
            table_id = f'D_{domain["id"]}_T{index}'
            lines.append(f'database "{_plantuml(table["name"])}" as {table_id}')
            lines.append(f'D_{domain["id"]} --> {table_id}')
    for index, external in enumerate(ir["externalSystems"]):
        lines.append(f'component "{_plantuml(external["name"])}" as E{index}')
        lines.append(f'D_{external["domain"]} --> E{index} : {_plantuml(external.get("kind", "external"))}')
    for relation in ir["relations"]:
        lines.append(f'D_{relation["from"]} --> D_{relation["to"]} : {_plantuml(relation["label"])}')
    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def render_drawio(ir):
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    domain_by_id = {}
    for index, domain in enumerate(ir["domains"]):
        cell_id = "D_" + domain["id"]
        domain_by_id[domain["id"]] = cell_id
        label = domain["name"] + "\n" + "\n".join(item["text"] for item in domain["capabilities"])
        x, y = 80 + (index % 3) * 340, 100 + (index // 3) * 270
        cells.append(f'<mxCell id="{cell_id}" value="{xml_escape(label, quote=True)}" style="rounded=1;whiteSpace=wrap;html=0;" vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="270" height="150" as="geometry"/></mxCell>')
        for table_index, table in enumerate(domain["tables"]):
            table_id = f"{cell_id}_T{table_index}"
            tx, ty = x + table_index * 150, y + 175
            cells.append(f'<mxCell id="{table_id}" value="{xml_escape(table["name"], quote=True)}" style="shape=cylinder3;whiteSpace=wrap;html=0;" vertex="1" parent="1"><mxGeometry x="{tx}" y="{ty}" width="130" height="55" as="geometry"/></mxCell>')
            cells.append(f'<mxCell id="table_{cell_id}_{table_index}" edge="1" parent="1" source="{cell_id}" target="{table_id}"><mxGeometry relative="1" as="geometry"/></mxCell>')
    external_x = 80 + min(3, len(ir["domains"])) * 340
    for index, external in enumerate(ir["externalSystems"]):
        cells.append(f'<mxCell id="E{index}" value="{xml_escape(external["name"], quote=True)}" style="rounded=1;whiteSpace=wrap;html=0;" vertex="1" parent="1"><mxGeometry x="{external_x}" y="{100 + index * 130}" width="250" height="70" as="geometry"/></mxCell>')
        cells.append(f'<mxCell id="external_R{index}" value="{xml_escape(external.get("kind", "external"), quote=True)}" style="edgeStyle=orthogonalEdgeStyle;html=0;dashed=1;" edge="1" parent="1" source="{domain_by_id[external["domain"]]}" target="E{index}"><mxGeometry relative="1" as="geometry"/></mxCell>')
    for index, relation in enumerate(ir["relations"]):
        cells.append(f'<mxCell id="R{index}" value="{xml_escape(relation["label"], quote=True)}" style="edgeStyle=orthogonalEdgeStyle;html=0;" edge="1" parent="1" source="{domain_by_id[relation["from"]]}" target="{domain_by_id[relation["to"]]}"><mxGeometry relative="1" as="geometry"/></mxCell>')
    return '<mxfile host="understand-arch"><diagram id="architecture" name="Architecture"><mxGraphModel><root>' + "".join(cells) + '</root></mxGraphModel></diagram></mxfile>\n'


def render_archify(ir):
    """Produce official Archify architecture schema-v1 JSON; no custom HTML renderer."""
    components = []
    connections = []
    count = len(ir["domains"])
    cols = max(1, min(12, max(count, len(ir["externalSystems"]))))
    external_rows = (len(ir["externalSystems"]) + cols - 1) // cols
    domain_row = external_rows + (1 if external_rows else 0)
    for index, domain in enumerate(ir["domains"]):
        components.append({"id": domain["id"], "type": "backend", "label": domain["name"],
                           "sublabel": " / ".join(item["text"] for item in domain["capabilities"]),
                           "row": domain_row + index // cols, "col": index % cols})
        for table_index, table in enumerate(domain["tables"]):
            table_id = f'{domain["id"]}_table_{table_index}'
            components.append({"id": table_id, "type": "database", "label": table["name"],
                               "row": domain_row + (count - 1) // cols + 2 + index // cols, "col": index % cols})
            connections.append({"from": domain["id"], "to": table_id})
    for index, external in enumerate(ir["externalSystems"]):
        components.append({"id": f"external_{index}", "type": "external", "label": external["name"],
                           "row": index // cols, "col": index % cols})
        connections.append({"from": external["domain"], "to": f"external_{index}", "label": external.get("kind", "external")})
    for relation in ir["relations"]:
        connections.append({"from": relation["from"], "to": relation["to"], "label": relation["label"]})
    return {"schema_version": 1, "diagram_type": "architecture", "meta": {"title": ir["summary"]},
            "layout": {"mode": "grid", "cols": cols, "cellW": 280, "cellH": 110, "gapX": 70, "gapY": 90},
            "components": components, "connections": connections}
