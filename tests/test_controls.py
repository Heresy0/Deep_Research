import asyncio
import json
import os
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from backend.router.research_router import router
from backend.service import get_workflow_service
from backend.service.run_store import MemoryRunStore
from backend.service.workflow_service import WorkflowService, CapacityExceeded
from mult_agents.graph import build_app
from mult_agents.harness.runtime import ExecutionError, Limits, RunContext, activate
from mult_agents.nodes import _derive_search_plan
from tests.support import WEB, LOCAL, REQUEST, TestConfig, bundle, execute


class Controls(unittest.TestCase):
    def test_01_auth_failure_stops_provider_and_writer(self):
        agents = bundle()
        error = urllib.error.HTTPError("https://api.bocha.cn", 401, "unauthorized", {}, None)
        with patch.dict(os.environ, {"BOCHA_API_KEY": "test-only"}), patch("urllib.request.urlopen", side_effect=error) as http, patch("mult_agents.nodes.search_knowledge_base_records", return_value=[]):
            result, runtime, _ = execute(agents)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(runtime.counts["web_calls"], 1)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(agents.writer.calls, 0)
        self.assertIn("认证失败", result["final"])
        self.assertEqual(result["web_retrieval_stats"]["query_count"], 1)
        self.assertEqual(result["web_search_trace"][0]["error_code"], "AUTH_ERROR")

    def test_02_empty_results_are_partial_not_invented(self):
        agents = bundle({"route": "direct"})
        with patch("mult_agents.nodes.bocha_web_search_records", return_value=[]), patch("mult_agents.nodes.search_knowledge_base_records", return_value=[]):
            result, _, _ = execute(agents)
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["retrieval_errors"])
        self.assertEqual(agents.writer.calls, 0)
        self.assertEqual(agents.analyst.calls, 0)

    def test_03_rate_limit_has_bounded_retries(self):
        from mult_agents.tools import bocha_web_search_records
        runtime = RunContext()
        error = urllib.error.HTTPError("https://api.bocha.cn", 429, "limited", {}, None)
        with patch.dict(os.environ, {"BOCHA_API_KEY": "test-only"}), patch("urllib.request.urlopen", side_effect=error) as http, patch("mult_agents.tools.time.sleep"), activate(runtime):
            with self.assertRaises(ExecutionError) as raised:
                bocha_web_search_records("query")
        self.assertEqual(raised.exception.code, "RATE_LIMIT")
        self.assertEqual(http.call_count, 3)
        self.assertEqual(runtime.counts["web_calls"], 3)

    def test_04_invalid_analysis_repairs_once_then_fails_closed(self):
        agents = bundle({"invalid_role": "analyst"})
        with patch("mult_agents.nodes.bocha_web_search_records", return_value=[WEB]), patch("mult_agents.nodes.search_knowledge_base_records", return_value=[LOCAL]):
            result, _, _ = execute(agents)
        self.assertEqual(agents.analyst.calls, 2)
        self.assertEqual(agents.writer.calls, 0)
        self.assertEqual(result["termination_reason"], "MODEL_OUTPUT_INVALID")
        self.assertFalse(result["verified_findings"])

    def test_05_invalid_citation_and_unsupported_claim_are_removed(self):
        for scenario in ({"analysis_sources": ["WEB9_9-9"]}, {"reject_support": True}, {"bad_layout": True},
                         {"scout_reject": True}, {"bad_quote": True}, {"claim": "模拟方案 A 支持私有部署吗？"}):
            with self.subTest(scenario=scenario):
                agents = bundle(scenario)
                with patch("mult_agents.nodes.bocha_web_search_records", return_value=[WEB]), patch("mult_agents.nodes.search_knowledge_base_records", return_value=[LOCAL]):
                    result, _, _ = execute(agents)
                self.assertNotIn("WEB9_9-9", result["final"])
                self.assertNotIn("c_bad", result["final"])
                self.assertNotEqual(result["status"], "completed")
                if scenario.get("reject_support") or scenario.get("bad_quote"):
                    self.assertNotIn("模拟方案 A 支持私有部署。", result["final"])

    def test_06_budget_is_atomic_and_supplement_does_not_repeat(self):
        runtime = RunContext(limits=Limits(tool_calls=3))
        def reserve(_):
            try:
                runtime.reserve("local")
                return True
            except ExecutionError:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(reserve, range(20))), 3)
        self.assertEqual(runtime.counts["tool_calls"], 3)
        agents = bundle({"needs_more": True, "supplement_query": "模拟方案的部署说明"})
        with patch("mult_agents.nodes.bocha_web_search_records", return_value=[WEB]) as web, patch("mult_agents.nodes.search_knowledge_base_records", return_value=[LOCAL]):
            result, _, _ = execute(agents, max_iterations=1)
        self.assertEqual(web.call_count, 1)
        self.assertEqual(result["iteration"], 1)
        self.assertEqual(result["status"], "partial")
        reflection = agents.planner.prompts[-1]
        self.assertIn("补搜计划", reflection[0].content)
        low = bundle()
        result, runtime, _ = execute(low, limits=Limits(model_calls=3))
        self.assertLessEqual(runtime.counts["model_calls"], 3)
        self.assertEqual(result["termination_reason"], "BUDGET_EXCEEDED")

    def test_07_runs_use_unique_checkpoint_threads(self):
        agents = bundle({"route": "direct"})
        graph = build_app(agents, InMemorySaver())
        service = WorkflowService("unused", store=MemoryRunStore(), workflow=graph, config=TestConfig())
        try:
            first = service.start_run({**REQUEST, "query": "你好"})
            second = service.start_run({**REQUEST, "query": "另一个问题"})
            asyncio.run(service.wait_result(first)); asyncio.run(service.wait_result(second))
            self.assertNotEqual(first, second)
            one = graph.get_state({"configurable": {"thread_id": first}}).values
            two = graph.get_state({"configurable": {"thread_id": second}}).values
            self.assertEqual(one["query"], "你好")
            self.assertEqual(two["query"], "另一个问题")
        finally:
            service.close()

    def test_08_parallel_join_runs_judgment_and_analysis_once(self):
        agents = bundle()
        with patch("mult_agents.nodes.bocha_web_search_records", return_value=[WEB]), patch("mult_agents.nodes.search_knowledge_base_records", return_value=[LOCAL]):
            result, runtime, events = execute(agents)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(agents.analyst.calls, 1)
        starts = [e["name"] for e in events if e["type"] == "call_start" and e["kind"] == "node"]
        self.assertEqual(starts.count("deep_dive"), 1)
        self.assertEqual(starts.count("verify"), 1)
        self.assertEqual(runtime.tokens["known_calls"], runtime.counts["model_calls"])
        self.assertIn("WEB1_1-1", result["final"])
        refs = result["final"].split("## 参考资料")[1]
        self.assertNotIn("LOC1_1-1", refs)
        plan = _derive_search_plan([{"id": "a", "search_queries": ["甲", "甲二"]}, {"id": "b", "search_queries": ["乙"]}], [], [], "原问题")
        self.assertEqual([q["query"] for q in plan[:2]], ["甲", "乙"])

    def test_09_capacity_rejects_before_queue_or_sse_headers(self):
        entered, release = Event(), Event()
        class BlockingGraph:
            def stream(self, state, config, **kwargs):
                entered.set(); release.wait(5)
                yield {"direct_answer": {"final": "done", "intent": "direct", "status": "completed"}}
        store = MemoryRunStore()
        service = WorkflowService("unused", store=store, workflow=BlockingGraph(), config=TestConfig(), max_concurrency=1)
        app = FastAPI(); app.include_router(router)
        app.dependency_overrides[get_workflow_service] = lambda: service
        try:
            run_id = service.start_run(REQUEST)
            self.assertTrue(entered.wait(2))
            with TestClient(app) as client:
                response = client.post("/api/v1/research/stream", json=REQUEST)
                self.assertEqual(response.status_code, 429)
            self.assertEqual(len(store.runs), 1)
            release.set(); asyncio.run(service.wait_result(run_id))
        finally:
            release.set(); service.close()

    def test_10_sse_replay_does_not_invoke_again(self):
        agents = bundle({"route": "direct"})
        store = MemoryRunStore()
        service = WorkflowService("unused", store=store, workflow=build_app(agents, InMemorySaver()), config=TestConfig())
        app = FastAPI(); app.include_router(router)
        app.dependency_overrides[get_workflow_service] = lambda: service
        try:
            with TestClient(app) as client:
                response = client.post("/api/v1/research/stream", json={**REQUEST, "query": "你好"})
                self.assertEqual(response.status_code, 200)
                run_id = response.headers["X-Research-Run-ID"]
                events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
                self.assertEqual(events[-1]["type"], "final")
                replay = client.get(f"/api/v1/research/runs/{run_id}/events?after_seq=1")
                self.assertEqual(replay.status_code, 200)
                self.assertEqual(agents.direct_responder.calls, 1)
                self.assertEqual(sum(e["type"] == "final" for e in store.history[run_id]), 1)
                self.assertEqual(client.get(f"/api/v1/research/runs/{run_id}").json()["status"], "completed")
                self.assertEqual(client.get(f"/api/v1/research/runs/{run_id}/events", headers={"Last-Event-ID": "-1"}).status_code, 400)
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
