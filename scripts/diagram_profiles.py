"""Typed source-backed diagram views and their supported renderers."""

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

from architecture_ir import _check_evidence, _xml_safe


CAPABILITIES = {
    "architecture-landscape": {"drawio"},
    "c4-context": {"drawio", "plantuml", "mermaid"},
    "c4-container": {"drawio", "plantuml", "mermaid"},
    "c4-component": {"drawio", "plantuml", "mermaid"},
    "uml-sequence": {"plantuml", "mermaid", "drawio"},
    "bpmn-process": {"drawio"},
    "erd": {"mermaid", "plantuml", "drawio"},
}
C4_TYPES = {
    "c4-context": {"person", "software_system", "external_system"},
    "c4-container": {"person", "software_system", "container", "external_system"},
    "c4-component": {"person", "component", "container", "software_system", "external_system"},
}
BPMN_TYPES = {"start_event", "end_event", "task", "exclusive_gateway", "parallel_gateway"}
LANDSCAPE_TYPES = {"actor", "entrypoint", "service", "adapter", "database", "cache",
                   "coordination_store", "external_system"}
CARDINALITIES = {"1", "0..1", "0..*", "1..*"}
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
BANDS = ("entry", "application", "integration", "storage", "external")


def _word(value):
    return isinstance(value, str) and bool(value.strip())


def _display_units(value):
    if not isinstance(value, str):
        return 0
    return sum(2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
               for char in value)


def _oneof(value, allowed):
    return isinstance(value, str) and value in allowed


def _check_xml_text(value, label, problems):
    if isinstance(value, str) and not _xml_safe(value):
        problems.append(f"{label}: contains characters unsupported by XML")


def validate_view(ir, root):
    """Validate view semantics and literal source anchors before rendering."""
    root = Path(root).resolve()
    problems = []
    if not isinstance(ir, dict) or ir.get("version") != 2:
        return ["view IR version must be 2"]
    profile = ir.get("profile")
    if not _oneof(profile, CAPABILITIES):
        return [f"unsupported diagram profile: {profile}"]
    if not _word(ir.get("title")):
        problems.append("title is required")
    _check_xml_text(ir.get("title"), "title", problems)
    scope = ir.get("scope")
    if not isinstance(scope, dict) or not _word(scope.get("system")):
        problems.append("scope.system is required")
    if isinstance(scope, dict):
        for key in ("system", "container"):
            _check_xml_text(scope.get(key), f"scope.{key}", problems)
    if profile == "c4-component" and (not isinstance(scope, dict) or not _word(scope.get("container"))):
        problems.append("c4-component requires one scope.container")
    elements = ir.get("elements")
    relations = ir.get("relations")
    if not isinstance(elements, list) or not elements:
        return problems + ["elements must be a non-empty list"]
    if not isinstance(relations, list):
        return problems + ["relations must be a list"]
    if profile == "architecture-landscape" and (len(elements) > 12 or len(relations) > 12):
        problems.append("architecture-landscape too dense: limit overview to 12 elements and 12 relations; split focused details into another view")
    by_id = {}
    for index, item in enumerate(elements):
        label = f"elements[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{label}: expected object")
            continue
        ident = item.get("id")
        if not isinstance(ident, str) or not IDENTIFIER.fullmatch(ident):
            problems.append(f"{label}: stable alphabetic id is required")
        elif ident in by_id:
            problems.append(f"{label}: duplicate id {ident}")
        else:
            by_id[ident] = item
        if not _word(item.get("name")):
            problems.append(f"{label}: name is required")
        for key in ("name", "description", "technology", "pool", "lane"):
            _check_xml_text(item.get(key), f"{label}.{key}", problems)
        if not _oneof(item.get("provenance"), {"EXTRACTED", "INFERRED", "AMBIGUOUS"}):
            problems.append(f"{label}: invalid provenance")
        cited_lines = _check_evidence(item.get("evidence"), root, label, problems)
        if item.get("provenance") == "EXTRACTED" and _word(item.get("name")) and cited_lines:
            if not any(item["name"] in line for line in cited_lines):
                problems.append(f"{label}: EXTRACTED name is not literal on cited source lines")
        kind = item.get("type")
        allowed = (C4_TYPES[profile] if profile in C4_TYPES else
                   LANDSCAPE_TYPES if profile == "architecture-landscape" else
                   {"participant"} if profile == "uml-sequence" else
                   BPMN_TYPES if profile == "bpmn-process" else {"entity"})
        if not _oneof(kind, allowed):
            problems.append(f"{label}: type {kind} is not allowed in {profile}")
        if profile in C4_TYPES:
            if not _word(item.get("description")):
                problems.append(f"{label}: C4 element description is required")
            if _oneof(kind, {"container", "component"}) and not _word(item.get("technology")):
                problems.append(f"{label}: C4 {kind} technology is required")
            if item.get("band", "application") not in BANDS:
                problems.append(f"{label}: unknown layout band")
        elif profile == "architecture-landscape":
            if not _word(item.get("description")):
                problems.append(f"{label}: landscape element description is required")
            if _display_units(item.get("name")) > 34 or _display_units(item.get("description")) > 54:
                problems.append(f"{label}: landscape card text too long; shorten the label or split the view")
            if item.get("status", "active") not in {"active", "planned"}:
                problems.append(f"{label}: invalid landscape status")
        elif profile == "bpmn-process":
            if not _word(item.get("pool")) or not _word(item.get("lane")):
                problems.append(f"{label}: BPMN pool and lane are required")
        elif profile == "erd":
            fields = item.get("fields", [])
            if not isinstance(fields, list):
                problems.append(f"{label}: fields must be a list")
            else:
                for field in fields:
                    if not isinstance(field, dict) or not _word(field.get("name")) or not _word(field.get("type")) or not _oneof(field.get("key", ""), {"", "PK", "FK", "UK"}):
                        problems.append(f"{label}: invalid entity field")
                    if isinstance(field, dict):
                        for key in ("name", "type"):
                            _check_xml_text(field.get(key), f"{label}.fields.{key}", problems)
    if profile == "c4-component" and not any(item.get("type") == "component" for item in elements if isinstance(item, dict)):
        problems.append("c4-component needs a component inside the scoped container")
    if profile == "c4-container" and not any(item.get("type") == "container" for item in elements if isinstance(item, dict)):
        problems.append("c4-container needs a container inside the scoped system")
    if profile == "bpmn-process":
        kinds = {item.get("type") for item in elements if isinstance(item, dict) and
                 isinstance(item.get("type"), str)}
        if not {"start_event", "end_event"}.issubset(kinds):
            problems.append("BPMN process needs start and end events")
    orders = set()
    for index, item in enumerate(relations):
        label = f"relations[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{label}: expected object")
            continue
        source, target = item.get("from"), item.get("to")
        if not isinstance(source, str) or not isinstance(target, str) or source not in by_id or target not in by_id:
            problems.append(f"{label}: missing relationship endpoint")
            continue
        if not _word(item.get("label")):
            problems.append(f"{label}: relationship label is required")
        for key in ("label", "technology"):
            _check_xml_text(item.get(key), f"{label}.{key}", problems)
        if not _oneof(item.get("provenance"), {"EXTRACTED", "INFERRED", "AMBIGUOUS"}):
            problems.append(f"{label}: invalid provenance")
        cited_lines = _check_evidence(item.get("evidence"), root, label, problems)
        if item.get("provenance") == "EXTRACTED" and _word(item.get("label")) and cited_lines:
            if not any(item["label"] in line for line in cited_lines):
                problems.append(f"{label}: EXTRACTED label is not literal on cited source lines")
        if profile in C4_TYPES:
            if source == target:
                problems.append(f"{label}: C4 self relationship is not allowed")
            if (profile == "c4-container" and by_id[source].get("type") == "container" and
                    by_id[target].get("type") == "container" and not _word(item.get("technology"))):
                    problems.append(f"{label}: container communication technology is required")
        elif profile == "architecture-landscape":
            if source == target:
                problems.append(f"{label}: landscape self relationship is not allowed")
            if not _oneof(item.get("kind"), {"primary", "secondary", "dependency"}):
                problems.append(f"{label}: invalid landscape relation kind")
            if _display_units(item.get("label")) > 56:
                problems.append(f"{label}: landscape relation label too long")
            if (_display_units(by_id[source].get("name")) +
                    _display_units(by_id[target].get("name")) > 60):
                problems.append(f"{label}: landscape endpoint labels too long for relation register")
        elif profile == "uml-sequence":
            order = item.get("order")
            if not isinstance(order, int) or isinstance(order, bool) or order < 1 or order in orders:
                problems.append(f"{label}: unique positive message order is required")
            orders.add(order)
            if not _oneof(item.get("kind"), {"call", "async", "return"}):
                problems.append(f"{label}: invalid message kind")
        elif profile == "bpmn-process":
            kind = item.get("kind")
            different = by_id[source].get("pool") != by_id[target].get("pool")
            if not _oneof(kind, {"sequence", "message"}):
                problems.append(f"{label}: invalid BPMN flow kind")
            elif kind == "sequence" and different:
                problems.append(f"{label}: sequence flow cannot connect different pools")
            elif kind == "message" and not different:
                problems.append(f"{label}: message flow requires different pools")
            if kind == "message" and (str(by_id[source].get("type", "")).endswith("gateway") or
                                      str(by_id[target].get("type", "")).endswith("gateway")):
                problems.append(f"{label}: BPMN gateway cannot be a message flow endpoint")
            if by_id[source].get("type") == "end_event" or by_id[target].get("type") == "start_event":
                problems.append(f"{label}: invalid event flow direction")
        elif profile == "erd":
            if (not _oneof(item.get("fromCardinality"), CARDINALITIES) or
                    not _oneof(item.get("toCardinality"), CARDINALITIES)):
                problems.append(f"{label}: explicit Crow's Foot cardinality is required")
    return problems


def validate_companion_views(ir, root, ir_path):
    """Verify declared overview omissions are present in a nearby detail IR."""
    if ir.get("profile") != "architecture-landscape":
        return "not_applicable", []
    coverage = ir.get("coverage")
    if coverage is None:
        return "not_declared", []
    if not isinstance(coverage, dict) or not isinstance(coverage.get("omitted"), list):
        return "fail", ["coverage.omitted must be a list"]
    problems = []
    base = Path(ir_path).resolve().parent
    for index, item in enumerate(coverage["omitted"]):
        label = f"coverage.omitted[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{label}: expected object")
            continue
        if not _word(item.get("reason")):
            problems.append(f"{label}: reason is required")
        _check_evidence(item.get("evidence"), Path(root).resolve(), label, problems)
        element = item.get("element")
        relation = item.get("relation")
        if not _word(element) and not isinstance(relation, dict):
            problems.append(f"{label}: element or relation is required")
        detail_name = item.get("detailView")
        if not _word(detail_name):
            problems.append(f"{label}: detailView is required")
            continue
        detail_path = (base / detail_name).resolve()
        if not detail_path.is_relative_to(base) or detail_path == Path(ir_path).resolve():
            problems.append(f"{label}: detailView must be another IR within {base}")
            continue
        try:
            detail = json.loads(detail_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            problems.append(f"{label}: detailView is unreadable: {error}")
            continue
        detail_problems = validate_view(detail, root)
        if detail_problems:
            problems.append(f"{label}: detailView is invalid: {'; '.join(detail_problems)}")
            continue
        if _word(element) and not any(node["id"] == element for node in detail["elements"]):
            problems.append(f"{label}: detailView is missing element {element}")
        if isinstance(relation, dict):
            if not all(_word(relation.get(key)) for key in ("from", "to", "label")):
                problems.append(f"{label}: relation needs from, to, and label")
            elif not any(all(link.get(key) == relation[key] for key in
                             ("from", "to", "label")) for link in detail["relations"]):
                problems.append(f"{label}: detailView is missing relation {relation}")
    return ("fail" if problems else "pass"), problems


def _safe(value):
    return str(value).replace("\\", "/").replace('"', "'").replace("\n", " ").replace("\r", " ").replace("<", "(").replace(">", ")").replace(";", " ").replace("`", "'")


def _xml(ir, title, legend=""):
    mx = ET.Element("mxfile", {"host": "understand-arch"})
    diagram = ET.SubElement(mx, "diagram", {"id": "view", "name": title})
    model = ET.SubElement(diagram, "mxGraphModel", {"page": "1", "pageScale": "1",
                                               "pageWidth": "1920", "pageHeight": "1200"})
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
    _cell(root, "title", title, 60, 24, 1760, 48,
          "text;html=0;strokeColor=none;fillColor=none;fontSize=25;fontStyle=1;")
    if legend:
        _cell(root, "legend", legend, 60, 82, 1760, 32,
              "text;html=0;strokeColor=none;fillColor=none;fontSize=13;fontColor=#475569;")
    return mx, root


def _cell(root, ident, value, x, y, width, height, style, parent="1"):
    cell = ET.SubElement(root, "mxCell", {"id": ident, "value": value, "style": style,
                                          "vertex": "1", "parent": parent})
    ET.SubElement(cell, "mxGeometry", {"x": str(x), "y": str(y), "width": str(width),
                                       "height": str(height), "as": "geometry"})
    return cell


def _edge(root, ident, value, source, target, style, points=()):
    edge = ET.SubElement(root, "mxCell", {"id": ident, "value": value, "style": style,
                                          "edge": "1", "parent": "1", "source": "node_" + source,
                                          "target": "node_" + target})
    geometry = ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
    if points:
        route = ET.SubElement(geometry, "Array", {"as": "points"})
        for x, y in points:
            ET.SubElement(route, "mxPoint", {"x": str(int(x)), "y": str(int(y))})


def _drawio(ir):
    profile = ir["profile"]
    if profile == "architecture-landscape":
        from architecture_landscape import render_landscape
        return render_landscape(ir)
    chinese = bool(re.search(r"[\u3400-\u9fff]", ir["title"]))
    legend = ("Legend: component / supporting container; arrows show calls or data flow"
              if profile == "c4-component" else
              "Legend: system / container; arrows show directed relationships"
              if profile.startswith("c4-") else
              "Legend: time flows down; solid=call, open arrow=async, dashed=return"
              if profile == "uml-sequence" else
              "Legend: pool and lane show responsibility; circle=event, rounded box=task, diamond=gateway"
              if profile == "bpmn-process" else
              "Legend: boxes=entities; relationship labels show Crow's Foot cardinality")
    if chinese:
        legend = ("图例：组件／外部容器；箭头表示调用或数据流向"
                  if profile == "c4-component" else
                  "图例：系统／容器；箭头表示有方向的关系"
                  if profile.startswith("c4-") else
                  "图例：时间自上而下；实线为调用，空心箭头为异步，虚线为返回"
                  if profile == "uml-sequence" else
                  "图例：泳道表示责任方；圆形为事件，圆角矩形为任务，菱形为网关"
                  if profile == "bpmn-process" else
                  "图例：方框表示实体；连线标签标明两端基数")
    mx, root = _xml(ir, ir["title"], legend)
    positions = {}
    if profile.startswith("c4-"):
        grouped = {band: [] for band in BANDS}
        for item in ir["elements"]:
            default = ("entry" if item["type"] == "person" else
                       "external" if item["type"] == "external_system" else
                       "application")
            grouped[item.get("band", default)].append(item)
        y = 145
        for band in BANDS:
            items = grouped[band]
            if not items:
                continue
            columns = min(4, len(items))
            rows = (len(items) + columns - 1) // columns
            height = rows * 160 + 52
            band_label = ({"entry": "入口", "application": "业务处理", "integration": "集成与支撑",
                           "storage": "持久化", "external": "外部系统"}[band] if chinese else band.title())
            _cell(root, "band_" + band, band_label, 45, y, 1780, height,
                  "rounded=1;whiteSpace=wrap;html=0;fillColor=#F8FAFC;strokeColor=#CBD5E1;align=left;verticalAlign=top;fontSize=16;fontStyle=1;spacing=14;")
            for index, item in enumerate(items):
                row_items = min(columns, len(items) - (index // columns) * columns)
                start_x = (1920 - (row_items * 350 + (row_items - 1) * 70)) / 2
                x = start_x + (index % columns) * 420
                yy = y + 45 + (index // columns) * 160
                positions[item["id"]] = (x, yy, 350, 110)
            y += height + 24
        scoped_type = ("container" if profile == "c4-container" else
                       "component" if profile == "c4-component" else None)
        scope_origin = None
        if scoped_type:
            scoped_positions = [positions[item["id"]] for item in ir["elements"]
                                if item["type"] == scoped_type]
            left = min(x for x, _, _, _ in scoped_positions) - 24
            top = min(y for _, y, _, _ in scoped_positions) - 42
            right = max(x + width for x, _, width, _ in scoped_positions) + 24
            bottom = max(y + height for _, y, _, height in scoped_positions) + 24
            scope_origin = (left, top)
            scope_name = (ir["scope"]["system"] if profile == "c4-container" else
                          ir["scope"]["container"])
            _cell(root, "scope_boundary", scope_name, left, top, right - left,
                  bottom - top,
                  "rounded=1;whiteSpace=wrap;html=0;align=left;verticalAlign=top;"
                  "spacingLeft=14;spacingTop=10;fontSize=16;fontStyle=1;"
                  "fillColor=#F8FCF9;strokeColor=#8DB7A0;strokeWidth=2;")
        edge_groups = {}
        for relation in ir["relations"]:
            key = (positions[relation["from"]][1], positions[relation["to"]][1])
            edge_groups.setdefault(key, []).append(relation)
        edge_slots = {id(relation): (index, len(group)) for group in edge_groups.values()
                      for index, relation in enumerate(group)}
        for index, relation in enumerate(ir["relations"]):
            sx, sy, sw, sh = positions[relation["from"]]
            tx, ty, tw, th = positions[relation["to"]]
            points = ()
            if ty > sy + sh:
                ports = "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"
                slot, total = edge_slots[id(relation)]
                if ty - sy > 300:
                    left = tx + tw / 2 < sx + sw / 2
                    source_port = 0.25 if left else 0.75
                    gutter = 465 if left else 1455
                    ports = f"exitX={source_port};exitY=1;entryX=0.5;entryY=0;"
                    offset = slot * 12
                    points = ((sx + sw * source_port, sy + sh + 28 + offset),
                              (gutter, sy + sh + 28 + offset),
                              (gutter, ty - 28 - offset),
                              (tx + tw / 2, ty - 28 - offset))
                else:
                    track = sy + sh + 18 + (slot + 1) * max(10, ty - sy - sh - 36) / (total + 1)
                    points = ((sx + sw / 2, track), (tx + tw / 2, track))
            elif sy > ty + th:
                ports = "exitX=0.5;exitY=0;entryX=0.5;entryY=1;"
            elif tx > sx:
                ports = "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"
            else:
                ports = "exitX=0;exitY=0.5;entryX=1;entryY=0.5;"
            _edge(root, "edge_" + str(index), relation["label"], relation["from"], relation["to"],
                  "edgeStyle=orthogonalEdgeStyle;rounded=0;html=0;endArrow=block;endFill=1;strokeColor=#2563EB;strokeWidth=2;fontSize=12;labelBackgroundColor=#FFFFFF;" + ports,
                  points)
        for item in ir["elements"]:
            x, y, width, height = positions[item["id"]]
            kind_label = ({"person": "使用者", "software_system": "软件系统",
                           "external_system": "外部系统"} if chinese else
                          {"person": "Person", "software_system": "Software system",
                           "external_system": "External system"})
            label = (item["name"] + "\n[" + item.get("technology", kind_label.get(item["type"], item["type"])) +
                     "]\n" + item["description"])
            fill = "#DBEAFE" if item["type"] in {"component", "container"} else "#F1F5F9"
            parent = "scope_boundary" if item["type"] == scoped_type else "1"
            node_x, node_y = ((x - scope_origin[0], y - scope_origin[1])
                              if parent == "scope_boundary" else (x, y))
            _cell(root, "node_" + item["id"], label, node_x, node_y, width, height,
                  f"rounded=1;whiteSpace=wrap;html=0;fillColor={fill};strokeColor=#475569;fontSize=15;spacing=8;",
                  parent=parent)
    elif profile == "uml-sequence":
        ordered = sorted(ir["relations"], key=lambda relation: relation["order"])
        centers = {item["id"]: 200 + index * 300 for index, item in enumerate(ir["elements"])}
        width = max(900, 300 * len(centers) + 40)
        mx.find("diagram/mxGraphModel").set("pageWidth", str(width + 120))
        for cell_id in ("title", "legend"):
            next(cell for cell in root.findall("mxCell") if cell.get("id") == cell_id).find("mxGeometry").set("width", str(width))
        bottom = 300 + 90 * len(ordered)
        for index, item in enumerate(ir["elements"]):
            x = centers[item["id"]]
            _cell(root, "participant_" + item["id"], item["name"], x - 105, 145, 210, 62,
                  "rounded=0;whiteSpace=wrap;html=0;fillColor=#DBEAFE;strokeColor=#475569;fontSize=16;fontStyle=1;")
            line = ET.SubElement(root, "mxCell", {"id": "lifeline_" + item["id"], "value": "",
                          "style": "dashed=1;dashPattern=4 4;endArrow=none;strokeColor=#94A3B8;strokeWidth=1.5;",
                          "edge": "1", "parent": "1"})
            geometry = ET.SubElement(line, "mxGeometry", {"relative": "1", "as": "geometry"})
            ET.SubElement(geometry, "mxPoint", {"x": str(x), "y": "207", "as": "sourcePoint"})
            ET.SubElement(geometry, "mxPoint", {"x": str(x), "y": str(bottom), "as": "targetPoint"})
        for index, relation in enumerate(ordered):
            source_x = centers[relation["from"]]
            target_x = centers[relation["to"]]
            y = 255 + index * 90
            kind = relation["kind"]
            style = ("html=0;strokeColor=#1D4ED8;strokeWidth=2;fontSize=13;"
                     "labelBackgroundColor=#FFFFFF;endArrow=" +
                     ("block;endFill=1;" if kind == "call" else "open;endFill=0;") +
                     ("dashed=1;" if kind == "return" else ""))
            message = ET.SubElement(root, "mxCell", {"id": "message_" + str(index),
                              "value": relation["label"], "style": style, "edge": "1", "parent": "1"})
            geometry = ET.SubElement(message, "mxGeometry", {"relative": "1", "as": "geometry"})
            if source_x == target_x:
                ET.SubElement(geometry, "mxPoint", {"x": str(source_x), "y": str(y), "as": "sourcePoint"})
                route = ET.SubElement(geometry, "Array", {"as": "points"})
                ET.SubElement(route, "mxPoint", {"x": str(source_x + 90), "y": str(y)})
                ET.SubElement(route, "mxPoint", {"x": str(source_x + 90), "y": str(y + 34)})
                ET.SubElement(geometry, "mxPoint", {"x": str(source_x), "y": str(y + 34),
                                                    "as": "targetPoint"})
            else:
                ET.SubElement(geometry, "mxPoint", {"x": str(source_x), "y": str(y),
                                                    "as": "sourcePoint"})
                ET.SubElement(geometry, "mxPoint", {"x": str(target_x), "y": str(y),
                                                    "as": "targetPoint"})
    elif profile == "bpmn-process":
        pools = {}
        for item in ir["elements"]:
            pools.setdefault(item["pool"], {}).setdefault(item["lane"], []).append(item)
        next_y = 145
        for pool_index, (pool, lanes) in enumerate(pools.items()):
            lane_heights = {lane: max(160, 50 + ((len(items) + 5) // 6) * 120)
                            for lane, items in lanes.items()}
            pool_height = 42 + sum(lane_heights.values())
            _cell(root, "pool_" + str(pool_index), pool, 45, next_y, 1780, pool_height,
                  "rounded=0;html=0;fillColor=#F1F5F9;strokeColor=#64748B;fontSize=17;align=left;verticalAlign=top;spacing=12;")
            lane_y = next_y + 42
            for lane_index, (lane, items) in enumerate(lanes.items()):
                height = lane_heights[lane]
                _cell(root, f"lane_{pool_index}_{lane_index}", lane, 105, lane_y, 1720, height,
                      "swimlane;html=0;rounded=0;fillColor=#FFFFFF;strokeColor=#94A3B8;fontSize=16;")
                for index, item in enumerate(items):
                    positions[item["id"]] = (240 + (index % 6) * 250,
                                             lane_y + 50 + (index // 6) * 120, 180, 72)
                lane_y += height
            next_y += pool_height + 28
        for index, relation in enumerate(ir["relations"]):
            style = ("edgeStyle=orthogonalEdgeStyle;html=0;endArrow=block;strokeWidth=2;" +
                     ("dashed=1;" if relation["kind"] == "message" else ""))
            _edge(root, "edge_" + str(index), relation["label"], relation["from"], relation["to"], style)
        for item in ir["elements"]:
            x, y, width, height = positions[item["id"]]
            kind = item["type"]
            style = ("ellipse;" if kind.endswith("event") else
                     "rhombus;" if kind.endswith("gateway") else "rounded=1;")
            if kind.endswith("event"):
                x += 54
                width = height = 72
            elif kind.endswith("gateway"):
                x += 47
                width = height = 86
            _cell(root, "node_" + item["id"], item["name"], x, y, width, height,
                  style + "whiteSpace=wrap;html=0;fillColor=#FFFFFF;strokeColor=#334155;fontSize=15;" +
                  ("strokeWidth=3;" if kind == "end_event" else "strokeWidth=1.5;"))
    else:
        markers = {"1": "ERmandOne", "0..1": "ERzeroToOne",
                   "0..*": "ERzeroToMany", "1..*": "ERoneToMany"}
        for index, relation in enumerate(ir["relations"]):
            label = (relation["fromCardinality"] + " " + relation["label"] + " " +
                     relation["toCardinality"])
            _edge(root, "edge_" + str(index), label, relation["from"], relation["to"],
                  "edgeStyle=entityRelationEdgeStyle;html=0;startArrow=" +
                  markers[relation["fromCardinality"]] + ";endArrow=" +
                  markers[relation["toCardinality"]] + ";strokeWidth=2;")
        for index, item in enumerate(ir["elements"]):
            fields = "\n".join(field["name"] + ": " + field["type"] +
                               (" [" + field["key"] + "]" if field.get("key") else "")
                               for field in item.get("fields", []))
            label = item["name"] + ("\n" + fields if fields else "")
            _cell(root, "node_" + item["id"], label, 100 + (index % 4) * 420,
                  170 + (index // 4) * 230, 330, max(90, 55 + 28 * len(item.get("fields", []))),
                  "rounded=0;html=0;whiteSpace=wrap;fillColor=#EFF6FF;strokeColor=#475569;fontSize=15;align=left;verticalAlign=top;spacing=12;")
    return ET.tostring(mx, encoding="unicode") + "\n"


def _plantuml(ir):
    profile = ir["profile"]
    lines = ["@startuml"]
    if profile.startswith("c4-"):
        level = profile.split("-")[1].title()
        lines.append(f"!include <C4/C4_{level}>")
        lines.append("LAYOUT_WITH_LEGEND()")
        lines.append("title " + _safe(ir["title"]))
        mapping = {"person": "Person", "software_system": "System",
                   "external_system": "System_Ext", "container": "Container",
                   "component": "Component"}
        scoped_type = ("container" if profile == "c4-container" else
                       "component" if profile == "c4-component" else None)
        scoped = [item for item in ir["elements"] if item["type"] == scoped_type]
        supporting = [item for item in ir["elements"] if item["type"] != scoped_type]
        boundary_alias = "view_scope"
        while any(item["id"] == boundary_alias for item in ir["elements"]):
            boundary_alias += "_"
        if scoped_type:
            macro = "System_Boundary" if profile == "c4-container" else "Container_Boundary"
            scope_name = ir["scope"]["system" if profile == "c4-container" else "container"]
            lines.append(f'{macro}({boundary_alias}, "{_safe(scope_name)}") {{')
        for index, item in enumerate(scoped + supporting):
            if scoped_type and index == len(scoped):
                lines.append("}")
            macro = mapping[item["type"]]
            args = [item["id"], '"' + _safe(item["name"]) + '"']
            if item["type"] in {"container", "component"}:
                args.append('"' + _safe(item["technology"]) + '"')
            args.append('"' + _safe(item["description"]) + '"')
            lines.append(macro + "(" + ", ".join(args) + ")")
        if scoped_type and not supporting:
            lines.append("}")
        for relation in ir["relations"]:
            args = [relation["from"], relation["to"], '"' + _safe(relation["label"]) + '"']
            if relation.get("technology"):
                args.append('"' + _safe(relation["technology"]) + '"')
            lines.append("Rel(" + ", ".join(args) + ")")
    elif profile == "uml-sequence":
        lines.append("title " + _safe(ir["title"]))
        for item in ir["elements"]:
            lines.append(f'participant "{_safe(item["name"])}" as {item["id"]}')
        for relation in sorted(ir["relations"], key=lambda item: item["order"]):
            arrow = "-->" if relation["kind"] == "return" else "->>" if relation["kind"] == "async" else "->"
            lines.append(f'{relation["from"]} {arrow} {relation["to"]} : {_safe(relation["label"])}')
    else:
        lines.append("hide circle")
        lines.append("skinparam linetype ortho")
        lines.append("title " + _safe(ir["title"]))
        for item in ir["elements"]:
            lines.append(f'entity "{_safe(item["name"])}" as {item["id"]} {{')
            for field in item.get("fields", []):
                lines.append("  " + ("*" if field.get("key") == "PK" else "") +
                             _safe(field["name"]) + " : " + _safe(field["type"]) +
                             (" <<" + field["key"] + ">>" if field.get("key") else ""))
            lines.append("}")
        left = {"1": "||", "0..1": "o|", "0..*": "}o", "1..*": "}|"}
        right = {"1": "||", "0..1": "o|", "0..*": "o{", "1..*": "|{"}
        for relation in ir["relations"]:
            lines.append(f'{relation["from"]} {left[relation["fromCardinality"]]}--{right[relation["toCardinality"]]} {relation["to"]} : {_safe(relation["label"])}')
    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def _mermaid(ir):
    profile = ir["profile"]
    if profile.startswith("c4-"):
        lines = ["C4" + profile.split("-")[1].title(), "title " + _safe(ir["title"])]
        mapping = {"person": "Person", "software_system": "System",
                   "external_system": "System_Ext", "container": "Container",
                   "component": "Component"}
        scoped_type = ("container" if profile == "c4-container" else
                       "component" if profile == "c4-component" else None)
        scoped = [item for item in ir["elements"] if item["type"] == scoped_type]
        supporting = [item for item in ir["elements"] if item["type"] != scoped_type]
        boundary_alias = "view_scope"
        while any(item["id"] == boundary_alias for item in ir["elements"]):
            boundary_alias += "_"
        if scoped_type:
            macro = "System_Boundary" if profile == "c4-container" else "Container_Boundary"
            scope_name = ir["scope"]["system" if profile == "c4-container" else "container"]
            lines.append(f'{macro}({boundary_alias}, "{_safe(scope_name)}") {{')
        for index, item in enumerate(scoped + supporting):
            if scoped_type and index == len(scoped):
                lines.append("}")
            args = [item["id"], '"' + _safe(item["name"]) + '"']
            if item["type"] in {"container", "component"}:
                args.append('"' + _safe(item["technology"]) + '"')
            args.append('"' + _safe(item["description"]) + '"')
            lines.append(mapping[item["type"]] + "(" + ", ".join(args) + ")")
        if scoped_type and not supporting:
            lines.append("}")
        for relation in ir["relations"]:
            lines.append(f'Rel({relation["from"]}, {relation["to"]}, "{_safe(relation["label"])}")')
    elif profile == "uml-sequence":
        lines = ["sequenceDiagram"]
        for item in ir["elements"]:
            lines.append(f'participant {item["id"]} as {_safe(item["name"])}')
        for relation in sorted(ir["relations"], key=lambda item: item["order"]):
            arrow = "-->>" if relation["kind"] == "return" else "-)" if relation["kind"] == "async" else "->>"
            lines.append(f'{relation["from"]}{arrow}{relation["to"]}: {_safe(relation["label"])}')
    else:
        lines = ["erDiagram"]
        for item in ir["elements"]:
            lines.append("  " + item["id"] + " {")
            for field in item.get("fields", []):
                key = " " + field["key"] if field.get("key") else ""
                lines.append(f'    {_safe(field["type"])} {_safe(field["name"])}{key}')
            lines.append("  }")
        left = {"1": "||", "0..1": "o|", "0..*": "}o", "1..*": "}|"}
        right = {"1": "||", "0..1": "o|", "0..*": "o{", "1..*": "|{"}
        for relation in ir["relations"]:
            lines.append(f'  {relation["from"]} {left[relation["fromCardinality"]]}--{right[relation["toCardinality"]]} {relation["to"]} : {_safe(relation["label"])}')
    return "\n".join(lines) + "\n"


def render_view(ir, engine):
    """Render a supported, already validated IR v2 view."""
    profile = ir.get("profile")
    if engine not in CAPABILITIES.get(profile, ()):
        raise ValueError(f"unsupported {profile} diagram with {engine}; choose {sorted(CAPABILITIES.get(profile, []))}")
    return {"drawio": _drawio, "plantuml": _plantuml, "mermaid": _mermaid}[engine](ir)
