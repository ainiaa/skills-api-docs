"""Editable draw.io architecture landscape with explicit system boundaries."""

from collections import defaultdict
from html import escape
import xml.etree.ElementTree as ET


# Native draw.io shapes and styles are kept as a small reusable theme.
STAGES = (
    ("entry", "入口与触发", {"actor", "entrypoint"}),
    ("scope", "业务模块", {"service", "adapter"}),
    ("dependency", "数据设施与外部系统", {"database", "cache", "coordination_store", "external_system"}),
)
ROLE_STYLE = {
    "actor": ("shape=actor;", "#EAF1FC", "#4A6FA5"),
    "entrypoint": ("rounded=1;", "#EAF1FC", "#4A6FA5"),
    "service": ("rounded=1;", "#E6F3E8", "#467A57"),
    "adapter": ("rounded=1;", "#F0ECF8", "#76638E"),
    "database": ("shape=cylinder;", "#F1F4F7", "#60758A"),
    "cache": ("rounded=1;", "#E4F4F1", "#32837A"),
    "coordination_store": ("rounded=1;", "#E4F4F1", "#32837A"),
    "external_system": ("rounded=1;", "#FFF0E4", "#B77B4F"),
}
ROUTE_STYLE = {
    "primary": ("#DC2626", "3", ""),
    "secondary": ("#397BA9", "2", ""),
    "dependency": ("#D97706", "2", "dashed=1;dashPattern=7 4;"),
}
MAIN_LEFT = 78
MAIN_WIDTH = 1430
PANEL_X = 1580
PANEL_WIDTH = 532
PAGE_WIDTH = 2190
NODE_WIDTH = 310
NODE_HEIGHT = 100
NODE_GAP = 38
ROW_HEIGHT = 180
STAGE_GAP = 95


def _cell(root, ident, value, x, y, width, height, style, parent="1"):
    cell = ET.SubElement(root, "mxCell", {"id": ident, "value": value,
                                          "style": style, "vertex": "1", "parent": parent})
    ET.SubElement(cell, "mxGeometry", {"x": str(int(x)), "y": str(int(y)),
                                       "width": str(int(width)), "height": str(int(height)),
                                       "as": "geometry"})
    return cell


def _html_label(item):
    name = escape(item["name"])
    desc = escape(item["description"])
    return (f'<div style="font-size:17px;font-weight:bold;color:#243447">{name}</div>'
            f'<div style="font-size:12px;color:#526477;margin-top:5px">{desc}</div>')


def _stage_items(ir):
    by_stage = defaultdict(list)
    for item in ir["elements"]:
        stage = next(name for name, _, kinds in STAGES if item["type"] in kinds)
        by_stage[stage].append(item)
    scope_order = {item["id"]: index for index, item in enumerate(by_stage["scope"])}
    original_order = {item["id"]: index for index, item in enumerate(by_stage["dependency"])}
    by_stage["dependency"].sort(key=lambda item: (
        min((scope_order.get(relation["from"], 99) for relation in ir["relations"]
             if relation["to"] == item["id"]), default=99),
        original_order[item["id"]]))
    return by_stage


def _rows(stage, items):
    def chunks(group):
        return [group[index:index + 4] for index in range(0, len(group), 4)]

    if stage == "scope":
        services = [item for item in items if item["type"] == "service"]
        adapters = [item for item in items if item["type"] == "adapter"]
        if services and adapters and len(items) > 2:
            return chunks(services) + chunks(adapters)
    if stage == "dependency":
        data = [item for item in items if item["type"] in
                {"database", "cache", "coordination_store"}]
        external = [item for item in items if item["type"] == "external_system"]
        if data and external and len(items) > 4:
            return chunks(data) + chunks(external)
    return chunks(items)


def render_landscape(ir):
    """Render role layers and a numbered relation register on a dynamic canvas."""
    by_stage = _stage_items(ir)
    mx = ET.Element("mxfile", {"host": "understand-arch"})
    diagram = ET.SubElement(mx, "diagram", {"id": "architecture-landscape", "name": ir["title"]})
    model = ET.SubElement(diagram, "mxGraphModel", {"page": "1", "pageScale": "1",
                                               "pageWidth": str(PAGE_WIDTH), "pageHeight": "1200",
                                               "grid": "1", "gridSize": "10"})
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
    _cell(root, "title", ir["title"], MAIN_LEFT, 30, 1450, 44,
          "text;html=0;align=left;fontSize=29;fontStyle=1;fontColor=#1E293B;strokeColor=none;fillColor=none;")
    subtitle = ir["scope"]["system"] + "  /  " + ir["scope"].get("container", "架构总览")
    _cell(root, "subtitle", subtitle, MAIN_LEFT, 77, 1450, 30,
          "text;html=0;align=left;fontSize=14;fontColor=#64748B;strokeColor=none;fillColor=none;")
    for index, (ident, label, color) in enumerate((
            ("primary", "━━ 主链路", "#DC2626"),
            ("secondary", "━━ 辅助链路", "#397BA9"),
            ("dependency", "┄ 依赖链路", "#D97706"))):
        _cell(root, "legend_" + ident, label, PANEL_X + index * 175, 75, 170, 30,
              "text;html=0;align=left;fontSize=13;fontStyle=1;"
              f"fontColor={color};strokeColor=none;fillColor=none;")

    stage_geometry = {}
    y = 158
    for name, heading, _ in STAGES:
        items = by_stage[name]
        if not items:
            continue
        rows = len(_rows(name, items))
        height = 44 + rows * ROW_HEIGHT
        stage_geometry[name] = (y, height)
        y += height + STAGE_GAP
    page_height = max(y + 25, 150 + len(ir["relations"]) * 59)
    model.set("pageHeight", str(page_height))

    scope_start = max(125, stage_geometry.get("scope", (0, 0))[0] - 65)
    scope_end = (stage_geometry.get("scope", (0, 0))[0] +
                 stage_geometry.get("scope", (0, 0))[1] + 28)
    has_scope = "scope" in stage_geometry
    if has_scope:
        _cell(root, "scope_boundary", "模块边界  ·  " + subtitle, MAIN_LEFT - 21,
              scope_start, MAIN_WIDTH + 42, scope_end - scope_start,
              "rounded=1;arcSize=2;whiteSpace=wrap;html=0;align=left;verticalAlign=top;spacingLeft=18;spacingTop=13;fontSize=17;fontStyle=1;fontColor=#456B5A;fillColor=#F8FCF9;strokeColor=#A7C8B3;strokeWidth=2;")

    positions = {}
    for name, heading, _ in STAGES:
        if name not in stage_geometry:
            continue
        stage_y, _ = stage_geometry[name]
        in_scope = has_scope and name == "scope"
        parent = "scope_boundary" if in_scope else "1"
        x_offset = MAIN_LEFT - 21 if in_scope else 0
        y_offset = scope_start if in_scope else 0
        _cell(root, "stage_" + name, heading, MAIN_LEFT - x_offset, stage_y - y_offset,
              MAIN_WIDTH, 32,
              "text;html=0;align=left;fontSize=15;fontStyle=1;fontColor=#475569;strokeColor=none;fillColor=none;",
              parent=parent)
        for row, row_items in enumerate(_rows(name, by_stage[name])):
            row_size = len(row_items)
            row_width = row_size * NODE_WIDTH + (row_size - 1) * NODE_GAP
            first_x = MAIN_LEFT + (MAIN_WIDTH - row_width) / 2
            for column, item in enumerate(row_items):
                x = first_x + column * (NODE_WIDTH + NODE_GAP)
                node_y = stage_y + 48 + row * ROW_HEIGHT
                positions[item["id"]] = (x, node_y, NODE_WIDTH, NODE_HEIGHT, name)
                shape, fill, stroke = ROLE_STYLE[item["type"]]
                style = (shape + "whiteSpace=wrap;html=1;overflow=hidden;align=center;verticalAlign=middle;"
                         f"fillColor={fill};strokeColor={stroke};strokeWidth=2;spacing=10;shadow=0;"
                         + ("dashed=1;dashPattern=7 4;" if item.get("status") == "planned" else ""))
                _cell(root, "node_" + item["id"], _html_label(item), x - x_offset,
                      node_y - y_offset, NODE_WIDTH, NODE_HEIGHT, style, parent=parent)

    _cell(root, "relation_header", "关系索引", PANEL_X, 132, PANEL_WIDTH, 40,
          "text;html=0;align=left;fontSize=20;fontStyle=1;fontColor=#1E293B;strokeColor=none;fillColor=none;")
    names = {item["id"]: item["name"] for item in ir["elements"]}
    stage_rank = {stage: index for index, (stage, _, _) in enumerate(STAGES)}
    route_groups = defaultdict(list)
    for relation in ir["relations"]:
        route_groups[(positions[relation["from"]][4],
                      positions[relation["to"]][4])].append(relation)
    route_slots = {id(relation): index for group in route_groups.values()
                   for index, relation in enumerate(sorted(
                       group, key=lambda rel: positions[rel["to"]][0]))}
    outgoing = defaultdict(list)
    incoming = defaultdict(list)
    for relation in ir["relations"]:
        outgoing[relation["from"]].append(relation)
        incoming[relation["to"]].append(relation)
    for source, group in outgoing.items():
        group.sort(key=lambda relation: positions[relation["to"]][0])
    for target, group in incoming.items():
        group.sort(key=lambda relation: positions[relation["from"]][0])
    used_bypass_lanes = []
    for index, relation in enumerate(ir["relations"]):
        source = relation["from"]
        target = relation["to"]
        sx, sy, sw, sh, source_stage = positions[source]
        tx, ty, tw, th, target_stage = positions[target]
        rank_gap = stage_rank[target_stage] - stage_rank[source_stage]
        slot = route_slots[id(relation)]
        points = []
        if ty > sy + sh:
            source_port = (outgoing[source].index(relation) + 1) / (len(outgoing[source]) + 1)
            target_port = (incoming[target].index(relation) + 1) / (len(incoming[target]) + 1)
            ports = (f"exitX={source_port:.3f};exitY=1;"
                     f"entryX={target_port:.3f};entryY=0;")
            intervening_row = any(
                sy + sh < other_y < ty
                for other_x, other_y, other_w, other_h, other_stage in positions.values())
            if rank_gap <= 1 and not intervening_row:
                free = ty - sy - sh
                track = sy + sh + 20 + (slot + 1) * max(1, free - 40) / (len(route_groups[(source_stage, target_stage)]) + 1)
                points = [(sx + sw * source_port, track), (tx + tw * target_port, track)]
            else:
                obstacles = [(ox, ox + ow) for ox, oy, ow, oh, _ in positions.values()
                             if sy + sh < oy < ty]
                target_center = tx + tw * target_port
                candidates = [target_center, sx + sw * source_port,
                              MAIN_LEFT + 18, MAIN_LEFT + MAIN_WIDTH - 18]
                for left, right in obstacles:
                    candidates.extend((left - 16, right + 16))
                lanes = [candidate for candidate in candidates
                         if MAIN_LEFT + 12 <= candidate <= MAIN_LEFT + MAIN_WIDTH - 12
                         and all(candidate <= left - 12 or candidate >= right + 12
                                 for left, right in obstacles)]
                gutter = min(lanes, key=lambda candidate: (
                    any(abs(candidate - used) < 12 for used in used_bypass_lanes),
                    abs(candidate - target_center)))
                used_bypass_lanes.append(gutter)
                track = sy + sh + 12
                points = [(sx + sw * source_port, track), (gutter, track),
                          (gutter, ty - 12), (target_center, ty - 12)]
        elif rank_gap < 0:
            ports = "exitX=0.5;exitY=0;entryX=0.5;entryY=1;"
        else:
            ports = "exitX=1;exitY=0.5;entryX=0;entryY=0.5;" if tx >= sx else "exitX=0;exitY=0.5;entryX=1;entryY=0.5;"
        color, width, dash = ROUTE_STYLE[relation["kind"]]
        edge = ET.SubElement(root, "mxCell", {"id": "edge_" + str(index),
                                               "value": f"{index + 1:02}",
                                               "style": ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=0;"
                                                         "endArrow=block;endFill=1;labelBackgroundColor=#FFFFFF;"
                                                         "fontSize=12;fontStyle=1;" +
                                                         f"fontColor={color};strokeColor={color};strokeWidth={width};" + dash + ports),
                                               "edge": "1", "parent": "1",
                                               "source": "node_" + source,
                                               "target": "node_" + target})
        geometry = ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
        if points:
            array = ET.SubElement(geometry, "Array", {"as": "points"})
            for px, py in points:
                ET.SubElement(array, "mxPoint", {"x": str(int(px)), "y": str(int(py))})
        relation_label = (f"{index + 1:02}   {relation['label']}\n"
                          f"{names[source]} → {names[target]}")
        _cell(root, "relation_" + str(index), relation_label, PANEL_X,
              180 + index * 59, PANEL_WIDTH, 54,
              "rounded=1;whiteSpace=wrap;html=0;align=left;verticalAlign=middle;spacingLeft=14;"
              f"fontSize=13;fontColor=#334155;fillColor=#FFFFFF;strokeColor={color};strokeWidth=1.5;")

    return ET.tostring(mx, encoding="unicode") + "\n"


def check_landscape_geometry(xml):
    """Check card geometry in the editable draw.io source; image review remains required."""
    model = ET.fromstring(xml).find(".//mxGraphModel")
    if model is None:
        return ["draw.io model is missing"]
    width = float(model.get("pageWidth", "0"))
    height = float(model.get("pageHeight", "0"))
    cells = {cell.get("id"): cell for cell in model.iter("mxCell")}

    def rectangle(cell):
        box = cell.find("mxGeometry")
        x, y, w, h = (float(box.get(key, "0")) for key in ("x", "y", "width", "height"))
        if cell.get("parent") == "scope_boundary":
            parent = cells["scope_boundary"].find("mxGeometry")
            x += float(parent.get("x", "0"))
            y += float(parent.get("y", "0"))
        return x, y, w, h

    nodes = [(ident, rectangle(cell)) for ident, cell in cells.items()
             if ident and ident.startswith("node_")]
    problems = []
    for index, (ident, (x, y, w, h)) in enumerate(nodes):
        if x < 0 or y < 0 or x + w > width or y + h > height:
            problems.append(f"{ident}: outside draw.io page")
        for other, (xx, yy, ww, hh) in nodes[index + 1:]:
            if x < xx + ww and xx < x + w and y < yy + hh and yy < y + h:
                problems.append(f"{ident} and {other}: node overlap")
    for ident in ("title", "subtitle"):
        if ident in cells and "scope_boundary" in cells:
            x, y, w, h = rectangle(cells[ident])
            xx, yy, ww, hh = rectangle(cells["scope_boundary"])
            if x < xx + ww and xx < x + w and y < yy + hh and yy < y + h:
                problems.append(f"scope_boundary and {ident}: overlap")
    return problems
