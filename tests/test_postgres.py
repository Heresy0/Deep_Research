import asyncio
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from psycopg.conninfo import conninfo_to_dict
from langgraph.checkpoint.postgres import PostgresSaver

from backend.service.run_store import PostgresRunStore
from backend.service.workflow_service import WorkflowService
from mult_agents.graph import build_app
from tests.support import REQUEST, TestConfig, bundle


@unittest.skipUnless(os.getenv("RESEARCH_TEST_POSTGRES_DSN"), "set RESEARCH_TEST_POSTGRES_DSN to an isolated *_test database")
class PostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ["RESEARCH_TEST_POSTGRES_DSN"]
        if not conninfo_to_dict(cls.dsn).get("dbname", "").endswith("_test"):
            raise RuntimeError("integration tests require an isolated database ending in _test")

    def setUp(self):
        self.store = PostgresRunStore(self.dsn)
        self.ids = []

    def tearDown(self):
        with self.store.pool.connection() as conn:
            for run_id in self.ids:
                conn.execute("DELETE FROM research_runs WHERE run_id=%s", (run_id,))
        self.store.close()

    def create(self):
        run_id = str(uuid4()); self.ids.append(run_id)
        self.store.create(run_id, REQUEST, {})
        return run_id

    def test_events_are_ordered_finish_is_atomic_and_persistent(self):
        run_id = self.create()
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda n: self.store.append(run_id, {"type": "phase", "number": n}), range(20)))
        result = {"run_id": run_id, "status": "partial", "final": "limited", "run_summary": {}}
        self.assertTrue(self.store.finish(run_id, result))
        self.assertFalse(self.store.finish(run_id, result))
        with self.store.pool.connection() as conn:
            row = conn.execute("SELECT status,result,next_seq FROM research_runs WHERE run_id=%s", (run_id,)).fetchone()
            self.assertEqual(row["status"], "partial")
            self.assertEqual(row["next_seq"], 21)
        reopened = PostgresRunStore(self.dsn)
        try:
            events = reopened.events(run_id)
            self.assertEqual([e["seq"] for e in events], list(range(1, 22)))
            self.assertEqual(events[-1]["type"], "final")
            self.assertEqual(reopened.get(run_id)["result"], result)
        finally:
            reopened.close()

    def test_restart_marks_only_unfinished_runs_failed(self):
        interrupted = self.create(); completed = self.create()
        self.store.append(interrupted, {"type": "phase", "node": "plan"})
        self.store.finish(completed, {"status": "completed", "final": "done"})
        self.assertGreaterEqual(self.store.fail_interrupted(), 1)
        run = self.store.get(interrupted)
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["result"]["run_summary"]["termination_reason"], "PROCESS_INTERRUPTED")
        self.assertEqual(self.store.get(completed)["status"], "completed")
        self.assertEqual(self.store.events(interrupted)[0]["node"], "plan")

    def test_checkpoint_isolation_and_event_reconnect(self):
        agents = bundle({"route": "direct"})
        with PostgresSaver.from_conn_string(self.dsn) as saver:
            saver.setup()
            graph = build_app(agents, saver)
            service = WorkflowService("unused", store=self.store, workflow=graph, config=TestConfig(postgres_dsn=self.dsn))
            try:
                first = service.start_run({**REQUEST, "query": "你好"})
                second = service.start_run({**REQUEST, "query": "second query"})
                self.ids.extend([first, second])
                asyncio.run(service.wait_result(first)); asyncio.run(service.wait_result(second))
                self.assertEqual(graph.get_state({"configurable": {"thread_id": first}}).values["query"], "你好")
                self.assertEqual(graph.get_state({"configurable": {"thread_id": second}}).values["query"], "second query")
                async def replay():
                    return [e async for e in service.events(first, 3)]
                events = asyncio.run(replay())
                self.assertEqual(events[-1]["type"], "final")
                self.assertTrue(all(e["seq"] > 3 for e in events))
                self.assertEqual(agents.direct_responder.calls, 2)
            finally:
                # Store is shared with the fixture; close it after checkpoint assertions.
                service._executor.shutdown(wait=True)
