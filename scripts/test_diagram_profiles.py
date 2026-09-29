"""Regression tests for source-backed, typed diagram views."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from codegraph_context import load_codegraph
from diagram_profiles import render_view, validate_view
from generate_architecture import _check_diagram


class DiagramProfilesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "Demo.java").write_text(
            "class Demo {\n  void receive() { service.save(); }\n  void save() {}\n}\n",
            encoding="utf-8")
        self.evidence = [{"path": "src/Demo.java", "line": 2,
                          "quote": "service.save()"}]

    def tearDown(self):
        self.temp.cleanup()

    def item(self, item_id, kind, name, **extra):
        return {"id": item_id, "type": kind, "name": name,
                "provenance": "INFERRED", "evidence": self.evidence, **extra}

    def relation(self, source, target, label, **extra):
        return {"from": source, "to": target, "label": label,
                "provenance": "INFERRED", "evidence": self.evidence, **extra}

    def view(self, profile, elements, relations, **extra):
        return {"version": 2, "profile": profile, "title": "Demo architecture",
                "scope": {"system": "Demo", "container": "Demo service"},
                "elements": elements, "relations": relations, **extra}

    def test_landscape_draws_scope_roles_routes_and_relation_register(self):
        ir = self.view("architecture-landscape", [
            self.item("admin", "entrypoint", "管理接口", description="资产管理入口"),
            self.item("job", "entrypoint", "定时任务", description="同步资产"),
            self.item("asset", "service", "资产服务", description="处理资产事件"),
            self.item("book", "service", "账簿服务", description="管理账簿"),
            self.item("repo", "adapter", "数据访问", description="读写资产"),
            self.item("ebs_client", "adapter", "EBS 适配", description="调用 EBS"),
            self.item("db", "database", "业务库", description="持久化资产"),
            self.item("cache", "coordination_store", "Redis", description="账簿写入加锁"),
            self.item("ebs", "external_system", "EBS", description="资产财务系统")], [
            self.relation("admin", "asset", "查询资产", kind="primary"),
            self.relation("job", "asset", "定时推送", kind="primary"),
            self.relation("admin", "book", "维护账簿", kind="secondary"),
            self.relation("asset", "repo", "读写台账", kind="dependency"),
            self.relation("book", "cache", "缓存账簿", kind="dependency"),
            self.relation("repo", "db", "MyBatis SQL", kind="dependency"),
            self.relation("asset", "ebs_client", "推送资产", kind="dependency"),
            self.relation("ebs_client", "ebs", "Feign HTTP", kind="dependency")])
        self.assertEqual(validate_view(ir, self.root), [])
        xml = ET.fromstring(render_view(ir, "drawio"))
        cells = {cell.get("id"): cell for cell in xml.iter("mxCell")}
        self.assertIn("Demo service", cells["scope_boundary"].get("value"))
        self.assertIn("shape=cylinder", cells["node_db"].get("style"))
        self.assertNotEqual(cells["node_cache"].get("style"), cells["node_db"].get("style"))
        self.assertIn("#DC2626", cells["edge_0"].get("style"))
        self.assertIn("#D97706", cells["edge_3"].get("style"))
        self.assertEqual(cells["edge_0"].get("value"), "01")
        self.assertIn("查询资产", cells["relation_0"].get("value"))
        self.assertGreater(float(cells["node_repo"].find("mxGeometry").get("y")),
                           float(cells["node_asset"].find("mxGeometry").get("y")))
        cache_route = cells["edge_4"].findall(".//mxPoint")
        self.assertGreaterEqual(len(cache_route), 4)
        boxes = []
        for ident, cell in cells.items():
            if ident and ident.startswith("node_"):
                box = cell.find("mxGeometry")
                x, y, width, height = (float(box.get(k)) for k in
                                       ("x", "y", "width", "height"))
                if cell.get("parent") == "scope_boundary":
                    boundary = cells["scope_boundary"].find("mxGeometry")
                    x += float(boundary.get("x"))
                    y += float(boundary.get("y"))
                boxes.append((x, y, width, height))
        for index, (x, y, w, h) in enumerate(boxes):
            for xx, yy, ww, hh in boxes[index + 1:]:
                self.assertFalse(x < xx + ww and xx < x + w and y < yy + hh and yy < y + h)

    def test_landscape_rejects_unknown_roles_and_unclassified_routes(self):
        ir = self.view("architecture-landscape", [
            self.item("entry", "entrypoint", "入口", description="接收请求"),
            self.item("service", "service", "服务", description="处理请求")],
            [self.relation("entry", "service", "调用", kind="primary")])
        self.assertEqual(validate_view(ir, self.root), [])
        ir["relations"][0]["kind"] = ""
        self.assertTrue(any("landscape relation kind" in p for p in validate_view(ir, self.root)))
        ir["relations"][0]["kind"] = "primary"
        ir["elements"][0]["type"] = "gateway"
        self.assertTrue(any("not allowed" in p for p in validate_view(ir, self.root)))
        with self.assertRaisesRegex(ValueError, "unsupported"):
            render_view(ir, "mermaid")

    def test_extracted_view_claims_must_match_cited_source_text(self):
        ir = self.view("architecture-landscape", [
            self.item("api", "entrypoint", "支付网关", description="处理支付",
                      provenance="EXTRACTED"),
            self.item("db", "database", "交易库", description="存储交易",
                      provenance="EXTRACTED")], [
            self.relation("api", "db", "清算资金", kind="primary",
                          provenance="EXTRACTED")])
        problems = validate_view(ir, self.root)
        self.assertTrue(any("EXTRACTED" in problem and "name" in problem for problem in problems))
        self.assertTrue(any("EXTRACTED" in problem and "label" in problem for problem in problems))
        ir["elements"][0]["name"] = "Demo"
        ir["elements"][0]["evidence"] = [{"path": "src/Demo.java", "line": 1,
                                          "quote": "class Demo"}]
        ir["elements"][1]["name"] = "service.save()"
        ir["relations"][0]["label"] = "service.save()"
        self.assertEqual(validate_view(ir, self.root), [])

    def test_landscape_requires_overview_density(self):
        elements = [self.item("entry", "entrypoint", "入口", description="接收请求")]
        elements.extend(self.item(f"service{index}", "service", f"服务{index}",
                                  description="处理请求") for index in range(13))
        relations = [self.relation("entry", item["id"], "调用", kind="primary")
                     for item in elements[1:]]
        ir = self.view("architecture-landscape", elements, relations)
        problems = validate_view(ir, self.root)
        self.assertTrue(any("too dense" in problem for problem in problems))

    def test_landscape_rejects_labels_that_cannot_fit_cards(self):
        ir = self.view("architecture-landscape", [
            self.item("entry", "entrypoint", "入口" * 30, description="接收请求"),
            self.item("service", "service", "服务", description="处理请求")],
            [self.relation("entry", "service", "调用", kind="primary")])
        self.assertTrue(any("too long" in problem for problem in validate_view(ir, self.root)))

    def test_landscape_separates_three_services_from_one_adapter(self):
        ir = self.view("architecture-landscape", [
            self.item("pay", "service", "付款", description="处理付款"),
            self.item("flow", "service", "流水", description="处理流水"),
            self.item("finance", "service", "融资", description="处理融资"),
            self.item("dao", "adapter", "数据访问", description="持久化")],
            [self.relation("pay", "dao", "读写", kind="dependency")])
        self.assertEqual(validate_view(ir, self.root), [])
        xml = ET.fromstring(render_view(ir, "drawio"))
        cells = {cell.get("id"): cell for cell in xml.iter("mxCell")}
        self.assertGreater(float(cells["node_dao"].find("mxGeometry").get("y")),
                           float(cells["node_pay"].find("mxGeometry").get("y")))

    def test_landscape_routes_past_adapter_inside_canvas(self):
        ir = self.view("architecture-landscape", [
            self.item("pay", "service", "付款", description="处理付款"),
            self.item("flow", "service", "流水", description="处理流水"),
            self.item("finance", "service", "融资", description="处理融资"),
            self.item("dao", "adapter", "数据访问", description="持久化"),
            self.item("cache", "cache", "Redis", description="缓存")], [
            self.relation("pay", "dao", "读写", kind="dependency"),
            self.relation("pay", "cache", "缓存", kind="dependency")])
        self.assertEqual(validate_view(ir, self.root), [])
        xml = ET.fromstring(render_view(ir, "drawio"))
        cells = {cell.get("id"): cell for cell in xml.iter("mxCell")}
        boundary = cells["scope_boundary"].find("mxGeometry")
        left = float(boundary.get("x"))
        right = left + float(boundary.get("width"))
        dao = cells["node_dao"].find("mxGeometry")
        dao_left = left + float(dao.get("x"))
        dao_right = dao_left + float(dao.get("width"))
        points = cells["edge_1"].findall(".//mxPoint")
        self.assertGreaterEqual(len(points), 4)
        lane = float(points[1].get("x"))
        self.assertGreater(lane, left)
        self.assertLess(lane, right)
        self.assertTrue(lane < dao_left or lane > dao_right)

    def test_landscape_separates_data_facilities_from_external_systems(self):
        ir = self.view("architecture-landscape", [
            self.item("service", "service", "付款", description="处理付款"),
            self.item("db", "database", "MySQL", description="存储"),
            self.item("cache", "cache", "Redis", description="缓存"),
            self.item("engine", "external_system", "会计引擎", description="记账"),
            self.item("bank", "external_system", "银行服务", description="查余额"),
            self.item("order", "external_system", "单据中心", description="收流水")], [
            self.relation("service", "engine", "记账", kind="primary")])
        self.assertEqual(validate_view(ir, self.root), [])
        xml = ET.fromstring(render_view(ir, "drawio"))
        cells = {cell.get("id"): cell for cell in xml.iter("mxCell")}
        db_y = float(cells["node_db"].find("mxGeometry").get("y"))
        cache_y = float(cells["node_cache"].find("mxGeometry").get("y"))
        engine_y = float(cells["node_engine"].find("mxGeometry").get("y"))
        bank_y = float(cells["node_bank"].find("mxGeometry").get("y"))
        self.assertEqual(db_y, cache_y)
        self.assertEqual(engine_y, bank_y)
        self.assertGreater(engine_y, db_y)

    def test_landscape_keeps_four_dependencies_on_one_row(self):
        ir = self.view("architecture-landscape", [
            self.item("service", "service", "付款", description="处理付款"),
            self.item("db", "database", "MySQL", description="存储"),
            self.item("engine", "external_system", "会计引擎", description="记账"),
            self.item("bank", "external_system", "银行服务", description="查余额"),
            self.item("order", "external_system", "单据中心", description="收流水")], [
            self.relation("service", "engine", "记账", kind="primary")])
        self.assertEqual(validate_view(ir, self.root), [])
        xml = ET.fromstring(render_view(ir, "drawio"))
        cells = {cell.get("id"): cell for cell in xml.iter("mxCell")}
        ys = {float(cells["node_" + name].find("mxGeometry").get("y"))
              for name in ("db", "engine", "bank", "order")}
        self.assertEqual(len(ys), 1)

    def test_landscape_keeps_separate_lanes_for_long_cross_row_edges(self):
        ir = self.view("architecture-landscape", [
            self.item("pay", "service", "付款", description="处理付款"),
            self.item("flow", "service", "流水", description="处理流水"),
            self.item("finance", "service", "融资", description="处理融资"),
            self.item("dao", "adapter", "数据访问", description="持久化"),
            self.item("cache", "cache", "Redis", description="缓存"),
            self.item("db", "database", "MySQL", description="存储"),
            self.item("engine", "external_system", "会计引擎", description="记账"),
            self.item("bank", "external_system", "银行服务", description="查余额"),
            self.item("order", "external_system", "单据中心", description="收流水")], [
            self.relation("pay", "dao", "读写付款", kind="dependency"),
            self.relation("pay", "cache", "缓存", kind="dependency"),
            self.relation("pay", "engine", "会计推送", kind="primary"),
            self.relation("flow", "dao", "读写流水", kind="dependency"),
            self.relation("flow", "bank", "查余额", kind="dependency"),
            self.relation("flow", "order", "推送流水", kind="dependency"),
            self.relation("dao", "db", "持久化", kind="dependency")])
        self.assertEqual(validate_view(ir, self.root), [])
        xml = ET.fromstring(render_view(ir, "drawio"))
        cells = {cell.get("id"): cell for cell in xml.iter("mxCell")}
        lanes = []
        for edge in ("edge_2", "edge_4", "edge_5"):
            points = cells[edge].findall(".//mxPoint")
            self.assertGreaterEqual(len(points), 4)
            lanes.append(float(points[1].get("x")))
        self.assertTrue(all(abs(a - b) >= 12 for index, a in enumerate(lanes)
                            for b in lanes[index + 1:]), lanes)

    def test_landscape_detail_scope_does_not_cover_subtitle(self):
        ir = self.view("architecture-landscape", [
            self.item("pay", "service", "Payment", description="Handles payments"),
            self.item("redis", "cache", "Redis", description="Locks payments")], [
            self.relation("pay", "redis", "Locks", kind="dependency")])
        xml = ET.fromstring(render_view(ir, "drawio"))
        cells = {cell.get("id"): cell for cell in xml.iter("mxCell")}
        subtitle = cells["subtitle"].find("mxGeometry")
        boundary = cells["scope_boundary"].find("mxGeometry")
        self.assertGreaterEqual(float(boundary.get("y")),
                                float(subtitle.get("y")) + float(subtitle.get("height")) + 12)

    def test_c4_component_is_source_backed_and_drawio_layout_has_no_node_overlap(self):
        ir = self.view("c4-component", [
            self.item("api", "component", "API", description="Receives requests",
                      technology="Spring MVC", band="entry"),
            self.item("service", "component", "Service", description="Saves data",
                      technology="Java", band="application"),
            self.item("db", "container", "Database", description="Stores records",
                      technology="MySQL", band="storage")],
            [self.relation("api", "service", "Calls save"),
             self.relation("service", "db", "Persists records", technology="JDBC")])
        self.assertEqual(validate_view(ir, self.root), [])
        xml = ET.fromstring(render_view(ir, "drawio"))
        labels = [cell.get("value", "") for cell in xml.iter("mxCell")]
        self.assertIn("Demo architecture", labels)
        self.assertIn("Legend: component / supporting container; arrows show calls or data flow", labels)
        self.assertNotIn("api", labels)
        self.assertNotIn("service", labels)
        boxes = []
        for cell in xml.iter("mxCell"):
            if cell.get("id", "").startswith("node_"):
                box = cell.find("mxGeometry")
                boxes.append(tuple(float(box.get(k)) for k in ("x", "y", "width", "height")))
        for i, (x, y, w, h) in enumerate(boxes):
            for xx, yy, ww, hh in boxes[i + 1:]:
                self.assertFalse(x < xx + ww and xx < x + w and y < yy + hh and yy < y + h)
        edges = [cell for cell in xml.iter("mxCell") if cell.get("edge") == "1"]
        self.assertTrue(all("exitY=1;" in cell.get("style", "") and
                            "entryY=0;" in cell.get("style", "") for cell in edges))
        self.assertTrue(all(len(cell.findall(".//mxPoint")) >= 2 for cell in edges))
        self.assertIn("!include <C4/C4_Component>", render_view(ir, "plantuml"))
        self.assertIn("C4Component", render_view(ir, "mermaid"))

    def test_c4_scope_is_visible_and_contains_the_scoped_level(self):
        for profile, member_type, boundary in (
                ("c4-container", "container", "System_Boundary"),
                ("c4-component", "component", "Container_Boundary")):
            with self.subTest(profile=profile):
                ir = self.view(profile, [
                    self.item("inside", member_type, "Inside", description="Works",
                              technology="Java", band="application"),
                    self.item("outside", "external_system", "Outside",
                              description="External", band="external")], [])
                ir["scope"] = {"system": "Scoped System", "container": "Scoped Service"}
                self.assertEqual(validate_view(ir, self.root), [])
                xml = ET.fromstring(render_view(ir, "drawio"))
                cells = {cell.get("id"): cell for cell in xml.iter("mxCell")}
                scope = cells["scope_boundary"]
                expected = "Scoped System" if profile == "c4-container" else "Scoped Service"
                self.assertIn(expected, scope.get("value"))
                self.assertEqual(cells["node_inside"].get("parent"), "scope_boundary")
                self.assertNotEqual(cells["node_outside"].get("parent"), "scope_boundary")
                for engine in ("plantuml", "mermaid"):
                    rendered = render_view(ir, engine)
                    self.assertIn(boundary, rendered)
                    self.assertIn(expected, rendered)

    def test_chinese_c4_view_has_chinese_legend(self):
        ir = self.view("c4-component", [
            self.item("api", "component", "接口", description="接收请求", technology="Java"),
            self.item("erp", "external_system", "ERP", description="处理资产")], [])
        ir["title"] = "模块架构图"
        xml = ET.fromstring(render_view(ir, "drawio"))
        self.assertTrue(any("图例" in cell.get("value", "") for cell in xml.iter("mxCell")))
        self.assertFalse(any("external_system" in cell.get("value", "") for cell in xml.iter("mxCell")))
        self.assertTrue(any("外部系统" in cell.get("value", "") for cell in xml.iter("mxCell")))

    def test_c4_long_edges_route_around_middle_band_within_canvas(self):
        ir = self.view("c4-container", [
            self.item("app", "container", "App", description="Processes requests",
                      technology="Java", band="application"),
            self.item("db", "container", "DB", description="Stores data",
                      technology="MyBatis", band="storage"),
            self.item("left", "external_system", "MD", description="Master data", band="external"),
            self.item("right", "external_system", "EBS", description="ERP", band="external")],
            [self.relation("app", "db", "Writes", technology="JDBC"),
             self.relation("app", "left", "Reads"),
             self.relation("app", "right", "Sends")])
        xml = ET.fromstring(render_view(ir, "drawio"))
        routed = [cell for cell in xml.iter("mxCell") if cell.get("target") in
                  {"node_left", "node_right"}]
        self.assertEqual(len(routed), 2)
        for cell in routed:
            points = cell.findall(".//mxPoint")
            self.assertGreaterEqual(len(points), 4)
            self.assertTrue(all(45 < float(point.get("x")) < 1825 for point in points))
        self.assertIn("exitX=0.25;", routed[0].get("style"))
        self.assertIn("exitX=0.75;", routed[1].get("style"))

    def test_c4_rejects_mixed_level_and_missing_source_evidence(self):
        ir = self.view("c4-component", [self.item("table", "entity", "fa_asset")], [])
        self.assertTrue(any("not allowed" in problem for problem in validate_view(ir, self.root)))
        ir["elements"][0]["type"] = "component"
        ir["elements"][0]["description"] = "Stores events"
        ir["elements"][0]["technology"] = "Java"
        ir["elements"][0]["evidence"] = []
        self.assertTrue(any("evidence" in problem for problem in validate_view(ir, self.root)))

    def test_malformed_v2_types_are_reported_without_exception(self):
        self.assertTrue(validate_view({"version": 2, "profile": []}, self.root))
        ir = self.view("c4-component", [self.item("api", "component", "API",
                                                  description="Receives", technology="Java")],
                       [self.relation("api", [], "Calls")])
        ir["elements"][0]["provenance"] = []
        self.assertTrue(validate_view(ir, self.root))

    def test_v2_rejects_characters_invalid_in_diagram_xml(self):
        ir = self.view("c4-component", [self.item("api", "component", "API",
                                                  description="Receives", technology="Java")], [])
        ir["title"] = "Bad\x01Title"
        self.assertTrue(any("XML" in problem for problem in validate_view(ir, self.root)))

    def test_sequence_order_and_renderer_capability(self):
        ir = self.view("uml-sequence", [
            self.item("api", "participant", "API"),
            self.item("service", "participant", "Service")],
            [self.relation("api", "service", "Save", order=1, kind="call"),
             self.relation("service", "api", "Saved", order=2, kind="return")])
        self.assertEqual(validate_view(ir, self.root), [])
        self.assertLess(render_view(ir, "plantuml").index("Save"),
                        render_view(ir, "plantuml").index("Saved"))
        self.assertIn("sequenceDiagram", render_view(ir, "mermaid"))
        drawio = ET.fromstring(render_view(ir, "drawio"))
        messages = [cell for cell in drawio.iter("mxCell") if cell.get("id", "").startswith("message_")]
        self.assertEqual([cell.get("value") for cell in messages], ["Save", "Saved"])
        self.assertLess(float(messages[0].find(".//mxPoint[@as='sourcePoint']").get("y")),
                        float(messages[1].find(".//mxPoint[@as='sourcePoint']").get("y")))
        self.assertIn("dashed=1", messages[1].get("style"))
        self.assertEqual(len([cell for cell in drawio.iter("mxCell")
                              if cell.get("id", "").startswith("lifeline_")]), 2)
        self.assertLess(float(next(cell for cell in drawio.iter("mxCell")
                                   if cell.get("id") == "title").find("mxGeometry").get("width")), 1000)
        ir["relations"][1]["order"] = 1
        self.assertTrue(any("order" in problem for problem in validate_view(ir, self.root)))

    def test_drawio_sequence_has_open_async_arrow_and_self_message(self):
        ir = self.view("uml-sequence", [
            self.item("api", "participant", "API"),
            self.item("service", "participant", "Service")],
            [self.relation("api", "service", "Dispatch", order=1, kind="async"),
             self.relation("service", "service", "Validate", order=2, kind="call")])
        self.assertEqual(validate_view(ir, self.root), [])
        xml = ET.fromstring(render_view(ir, "drawio"))
        messages = [cell for cell in xml.iter("mxCell") if cell.get("id", "").startswith("message_")]
        self.assertIn("endArrow=open", messages[0].get("style"))
        self.assertEqual(len(messages[1].findall(".//mxPoint")), 4)

    def test_bpmn_visual_subset_enforces_pools_and_flow_types(self):
        ir = self.view("bpmn-process", [
            self.item("start", "start_event", "Received", pool="FMS", lane="API"),
            self.item("work", "task", "Validate", pool="FMS", lane="Service"),
            self.item("end", "end_event", "Saved", pool="FMS", lane="Service")],
            [self.relation("start", "work", "Request", kind="sequence"),
             self.relation("work", "end", "Valid", kind="sequence")])
        self.assertEqual(validate_view(ir, self.root), [])
        xml = ET.fromstring(render_view(ir, "drawio"))
        event_cells = [cell for cell in xml.iter("mxCell") if cell.get("id") in {"node_start", "node_end"}]
        self.assertTrue(all("ellipse" in cell.get("style", "") and
                            cell.find("mxGeometry").get("width") == cell.find("mxGeometry").get("height")
                            for cell in event_cells))
        self.assertIn("strokeWidth=3", next(cell for cell in event_cells if cell.get("id") == "node_end").get("style"))
        with self.assertRaisesRegex(ValueError, "unsupported"):
            render_view(ir, "mermaid")
        ir["elements"][2]["pool"] = "External"
        self.assertTrue(any("different pools" in problem for problem in validate_view(ir, self.root)))

    def test_bpmn_groups_multiple_lanes_inside_one_pool(self):
        ir = self.view("bpmn-process", [
            self.item("start", "start_event", "Received", pool="FMS", lane="API"),
            self.item("work", "task", "Validate", pool="FMS", lane="Service"),
            self.item("end", "end_event", "Saved", pool="FMS", lane="Service")],
            [self.relation("start", "work", "Pass", kind="sequence"),
             self.relation("work", "end", "Done", kind="sequence")])
        xml = ET.fromstring(render_view(ir, "drawio"))
        pools = [cell for cell in xml.iter("mxCell") if cell.get("id", "").startswith("pool_")]
        lanes = [cell for cell in xml.iter("mxCell") if cell.get("id", "").startswith("lane_")]
        self.assertEqual(len(pools), 1)
        self.assertEqual(len(lanes), 2)
        self.assertEqual(pools[0].get("value"), "FMS")
        self.assertEqual({cell.get("value") for cell in lanes}, {"API", "Service"})

    def test_bpmn_message_flow_rejects_gateway_endpoint(self):
        ir = self.view("bpmn-process", [
            self.item("start", "start_event", "Received", pool="FMS", lane="API"),
            self.item("decision", "exclusive_gateway", "Approved?", pool="FMS", lane="API"),
            self.item("end", "end_event", "Done", pool="Partner", lane="Partner")],
            [self.relation("start", "decision", "Next", kind="sequence"),
             self.relation("decision", "end", "Notify", kind="message")])
        self.assertTrue(any("gateway" in problem for problem in validate_view(ir, self.root)))

    def test_bpmn_long_lane_wraps_inside_pool(self):
        elements = [self.item("start", "start_event", "Start", pool="FMS", lane="Work")]
        elements += [self.item(f"task{index}", "task", f"Task {index}", pool="FMS", lane="Work")
                     for index in range(8)]
        elements.append(self.item("end", "end_event", "End", pool="FMS", lane="Work"))
        relations = [self.relation(elements[index]["id"], elements[index + 1]["id"], "Next", kind="sequence")
                     for index in range(len(elements) - 1)]
        ir = self.view("bpmn-process", elements, relations)
        xml = ET.fromstring(render_view(ir, "drawio"))
        pool = next(cell for cell in xml.iter("mxCell") if cell.get("id") == "pool_0")
        outer = pool.find("mxGeometry")
        right = float(outer.get("x")) + float(outer.get("width"))
        bottom = float(outer.get("y")) + float(outer.get("height"))
        for cell in xml.iter("mxCell"):
            if cell.get("id", "").startswith("node_"):
                box = cell.find("mxGeometry")
                self.assertLessEqual(float(box.get("x")) + float(box.get("width")), right)
                self.assertLessEqual(float(box.get("y")) + float(box.get("height")), bottom)

    def test_erd_requires_cardinality_and_supports_three_renderers(self):
        ir = self.view("erd", [
            self.item("asset", "entity", "Asset", fields=[{"name": "id", "type": "bigint", "key": "PK"}]),
            self.item("event", "entity", "Event", fields=[{"name": "asset_id", "type": "bigint", "key": "FK"}])],
            [self.relation("asset", "event", "has", fromCardinality="1", toCardinality="0..*")])
        self.assertEqual(validate_view(ir, self.root), [])
        self.assertIn("erDiagram", render_view(ir, "mermaid"))
        self.assertIn("||--o{", render_view(ir, "mermaid"))
        self.assertIn("entity", render_view(ir, "plantuml"))
        drawio = ET.fromstring(render_view(ir, "drawio"))
        self.assertEqual(drawio.tag, "mxfile")
        edge = next(cell for cell in drawio.iter("mxCell") if cell.get("edge") == "1")
        self.assertIn("startArrow=ERmandOne", edge.get("style"))
        self.assertIn("endArrow=ERzeroToMany", edge.get("style"))
        entity = next(cell for cell in drawio.iter("mxCell") if cell.get("id") == "node_asset")
        self.assertNotIn("swimlane", entity.get("style"))
        del ir["relations"][0]["toCardinality"]
        self.assertTrue(any("cardinality" in problem for problem in validate_view(ir, self.root)))

    def test_codegraph_reads_fresh_structured_nodes_and_focused_calls(self):
        (self.root / ".codegraph").mkdir()
        outside = self.root.parent / (self.root.name + "-outside.java")
        outside.write_text("class Outside {}\n", encoding="utf-8")
        calls = []
        def runner(argv, **_kwargs):
            calls.append(argv)
            class Result:
                returncode = 0
                stderr = ""
                stdout = ""
            result = Result()
            if "status" in argv:
                result.stdout = json.dumps({"initialized": True, "pendingChanges":
                                            {"added": 0, "modified": 0, "removed": 0},
                                            "worktreeMismatch": None, "index": {"reindexRecommended": False}})
            elif "query" in argv:
                kind = argv[argv.index("--kind") + 1]
                result.stdout = json.dumps([{"node": {"id": kind + ":1", "kind": kind,
                                                        "name": "Demo", "filePath": "src/Demo.java",
                                                        "startLine": 1}},
                                            {"node": {"id": kind + ":2", "kind": kind,
                                                       "name": "Outside", "filePath": "../" + outside.name,
                                                       "startLine": 1}}])
            else:
                result.stdout = json.dumps({"symbol": "receive", "callees": [
                    {"name": "save", "kind": "method", "filePath": "src/Demo.java", "startLine": 3}]})
            return result
        try:
            graph, warnings = load_codegraph(self.root, focus=["receive"], executable="codegraph", run=runner)
            self.assertEqual(warnings, [])
            self.assertEqual(len(graph["classes"]), 1)
            self.assertEqual(graph["calls"]["receive"][0]["name"], "save")
            self.assertTrue(any("callees" in command for command in calls))
        finally:
            outside.unlink()

    def test_codegraph_rejects_stale_index_without_querying_nodes(self):
        (self.root / ".codegraph").mkdir()
        commands = []
        def runner(argv, **_kwargs):
            commands.append(argv)
            class Result:
                returncode = 0
                stderr = ""
                stdout = json.dumps({"initialized": True, "pendingChanges":
                                     {"added": 0, "modified": 1, "removed": 0}})
            return Result()
        graph, warnings = load_codegraph(self.root, executable="codegraph", run=runner)
        self.assertIsNone(graph)
        self.assertTrue(any("stale" in warning for warning in warnings))
        self.assertEqual(len(commands), 1)

    def test_codegraph_handles_malformed_status_as_warning(self):
        (self.root / ".codegraph").mkdir()
        def runner(_argv, **_kwargs):
            class Result:
                returncode = 0
                stderr = ""
                stdout = "[]"
            return Result()
        graph, warnings = load_codegraph(self.root, executable="codegraph", run=runner)
        self.assertIsNone(graph)
        self.assertTrue(warnings)

    def test_cli_validates_and_renders_v2_without_changing_v1_contract(self):
        ir = self.view("c4-component", [
            self.item("api", "component", "API", description="Receives events",
                      technology="Spring MVC", band="entry"),
            self.item("service", "component", "Service", description="Saves events",
                      technology="Java", band="application")],
            [self.relation("api", "service", "Calls save")])
        ir_path = self.root / "view.json"
        ir_path.write_text(json.dumps(ir), encoding="utf-8")
        cli = Path(__file__).with_name("generate_architecture.py")
        base = [sys.executable, str(cli)]
        valid = subprocess.run([*base, "validate", "--source", str(self.root),
                                "--ir", str(ir_path)], capture_output=True, text=True)
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        out = self.root / "output"
        render = subprocess.run([*base, "render", "--source", str(self.root),
                                 "--ir", str(ir_path), "--output", str(out),
                                 "--format", "drawio"], capture_output=True, text=True)
        self.assertEqual(render.returncode, 0, render.stdout + render.stderr)
        self.assertEqual(json.loads(render.stdout)["visualReview"], "required")
        self.assertTrue((out / "architecture.drawio").is_file())
        self.assertIn("Demo architecture", (out / "architecture.drawio").read_text())
        mermaid = subprocess.run([*base, "render", "--source", str(self.root),
                                  "--ir", str(ir_path), "--output", str(out),
                                  "--format", "mermaid"], capture_output=True, text=True)
        self.assertEqual(mermaid.returncode, 0, mermaid.stdout + mermaid.stderr)
        self.assertTrue(any("experimental" in warning for warning in
                            json.loads(mermaid.stdout).get("warnings", [])))
        wrong = subprocess.run([*base, "render", "--source", str(self.root),
                                "--ir", str(ir_path), "--output", str(out),
                                "--format", "archify"], capture_output=True, text=True)
        self.assertNotEqual(wrong.returncode, 0)
        self.assertIn("unsupported", wrong.stdout + wrong.stderr)

    def test_landscape_omission_requires_a_valid_companion_view(self):
        overview = self.view("architecture-landscape", [
            self.item("pay", "service", "Payment", description="Handles payments"),
            self.item("db", "database", "Database", description="Stores payments")], [
            self.relation("pay", "db", "Persists", kind="dependency")],
            coverage={"omitted": [{"element": "redis",
                                    "relation": {"from": "pay", "to": "redis",
                                                 "label": "Locks"},
                                    "reason": "Detailed runtime dependency",
                                    "detailView": "payment-detail.json",
                                    "evidence": self.evidence}]})
        detail = self.view("architecture-landscape", [
            self.item("pay", "service", "Payment", description="Handles payments"),
            self.item("redis", "cache", "Redis", description="Locks payments")], [
            self.relation("pay", "redis", "Locks", kind="dependency")])
        overview_path = self.root / "overview.json"
        detail_path = self.root / "payment-detail.json"
        overview_path.write_text(json.dumps(overview), encoding="utf-8")
        detail_path.write_text(json.dumps(detail), encoding="utf-8")
        cli = Path(__file__).with_name("generate_architecture.py")
        command = [sys.executable, str(cli), "validate", "--source", str(self.root),
                   "--ir", str(overview_path)]
        good = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertEqual(json.loads(good.stdout)["coverageCheck"], "declared_only")
        strict = subprocess.run([*command, "--strict-coverage"], capture_output=True, text=True)
        self.assertNotEqual(strict.returncode, 0)
        self.assertIn("strict coverage", strict.stdout + strict.stderr)
        detail["coverage"] = {"omitted": [{"element": "other", "detailView": "other.json"}]}
        detail_path.write_text(json.dumps(detail), encoding="utf-8")
        nested = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(nested.returncode, 0)
        self.assertIn("nested detail", nested.stdout + nested.stderr)
        detail.pop("coverage")
        detail["relations"] = []
        detail_path.write_text(json.dumps(detail), encoding="utf-8")
        bad = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("missing relation", bad.stdout + bad.stderr)
        detail_path.unlink()
        missing = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("detailView", missing.stdout + missing.stderr)

    @unittest.skipUnless(all(os.environ.get(name) or shutil.which(binary) for name, binary in
                             (("DRAWIO_OFFICIAL_CLI", "drawio"),
                              ("MERMAID_OFFICIAL_CLI", "mmdc"),
                              ("PLANTUML_OFFICIAL_CLI", "plantuml"))),
                         "official diagram CLIs are unavailable")
    def test_supported_profiles_parse_in_official_engines(self):
        cases = [
            (self.view("architecture-landscape", [
                self.item("api", "entrypoint", "API", description="Receives events"),
                self.item("service", "service", "Service", description="Handles events"),
                self.item("db", "database", "Database", description="Stores events")],
                [self.relation("api", "service", "Calls", kind="primary"),
                 self.relation("service", "db", "Writes", kind="dependency")]), ("drawio",)),
            (self.view("c4-component", [
                self.item("api", "component", "API", description="Receives events", technology="Java"),
                self.item("service", "component", "Service", description="Stores events", technology="Java")],
                [self.relation("api", "service", "Calls")]), ("drawio", "plantuml", "mermaid")),
            (self.view("c4-container", [
                self.item("app", "container", "Application", description="Handles events",
                          technology="Java"),
                self.item("db", "container", "Database", description="Stores events",
                          technology="MySQL")],
                [self.relation("app", "db", "Writes", technology="JDBC")]),
             ("drawio", "plantuml", "mermaid")),
            (self.view("uml-sequence", [self.item("api", "participant", "API"),
                                         self.item("service", "participant", "Service")],
                [self.relation("api", "service", "Calls", kind="call", order=1),
                 self.relation("service", "service", "Checks", kind="call", order=2),
                 self.relation("service", "api", "Notifies", kind="async", order=3),
                 self.relation("service", "api", "Returns", kind="return", order=4)]),
             ("plantuml", "mermaid", "drawio")),
            (self.view("bpmn-process", [
                self.item("start", "start_event", "Start", pool="FMS", lane="API"),
                self.item("end", "end_event", "End", pool="FMS", lane="API")],
                [self.relation("start", "end", "Next", kind="sequence")]), ("drawio",)),
            (self.view("erd", [
                self.item("asset", "entity", "Asset", fields=[{"name": "id", "type": "bigint", "key": "PK"}]),
                self.item("event", "entity", "Event", fields=[{"name": "id", "type": "bigint", "key": "PK"}])],
                [self.relation("asset", "event", "has", fromCardinality="1", toCardinality="0..*")]),
             ("drawio", "plantuml", "mermaid")),
        ]
        names = {"drawio": "drawio", "plantuml": "puml", "mermaid": "mmd"}
        for ir, engines in cases:
            for engine in engines:
                with self.subTest(profile=ir["profile"], engine=engine):
                    source = self.root / (ir["profile"] + "." + names[engine])
                    source.write_text(render_view(ir, engine), encoding="utf-8")
                    command = {"drawio": ("DRAWIO_OFFICIAL_CLI", "drawio"),
                               "plantuml": ("PLANTUML_OFFICIAL_CLI", "plantuml"),
                               "mermaid": ("MERMAID_OFFICIAL_CLI", "mmdc")}[engine]
                    executable = os.environ.get(command[0]) or shutil.which(command[1])
                    self.assertIsNone(_check_diagram(engine, executable, source))


if __name__ == "__main__":
    unittest.main()
