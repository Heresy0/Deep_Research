"""Fixed retrieval snapshots, optional real model, no live search/embedding calls."""
import argparse
import json
import re
import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))


def fixtures():
    text = (ROOT / "evals/fixtures/solutions.md").read_text(encoding="utf-8")
    docs = {}
    for match in re.finditer(r"^## (.+)\n\n([^#]+)", text, re.M):
        label = match[1]
        key = label[0] if label[0] in "ABC" else "TEAM"
        docs[key] = {"title": label, "doc_id": f"evals/fixtures/solutions.md#{key}", "snippet": match[2].strip(),
                     "source_type": "local", "retrieval_level": "document_chunk"}
    cases = json.loads((ROOT / "evals/cases.json").read_text(encoding="utf-8"))
    assert len(cases) == 10 and len(docs) == 4
    for case in cases:
        corpus = " ".join(docs[d]["snippet"] for d in case["docs"])
        assert all(quote in corpus for quote in case["expected_quotes"]), case["id"]
    return cases, docs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-model", action="store_true", help="Use paid model API; retrieval stays fixed/offline")
    parser.add_argument("--check-fixtures", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--case", help="Run one case ID, e.g. q08")
    parser.add_argument("--output", default="output/eval-results.json")
    args = parser.parse_args()
    cases, docs = fixtures()
    if args.check_fixtures:
        print("10 quality cases and 4 manually annotated fixture sections validated")
        return
    if not args.live_model:
        parser.error("Specify --check-fixtures or --live-model; live-model consumes API credits")
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]
        if not cases:
            parser.error("unknown case ID")
    from local_run import load_local_env
    load_local_env()
    from langgraph.checkpoint.memory import InMemorySaver
    from mult_agents.config import AppConfig
    from mult_agents.main import build_agents
    from mult_agents.graph import build_app
    from mult_agents.state import create_initial_state
    from mult_agents.harness.runtime import RunContext, activate, current, register, unregister
    from mult_agents.harness.telemetry import configure_logging
    configure_logging()
    config = AppConfig.from_file()
    with patch("mult_agents.main.init_rag_system"):
        agents = build_agents(config.model, config.api_key, config)
    graph = build_app(agents, InMemorySaver())
    results = []
    for case in cases[:max(1, min(args.limit, 10))]:
        context = RunContext()
        register(context)
        def records(query, limit=4):
            ctx = current()
            if ctx:
                ctx.reserve("local")
            with ctx.span("tool", "search_knowledge") if ctx else nullcontext():
                return [docs[d] for d in case["docs"]][:limit]
        def web(query, count=4):
            ctx = current()
            if ctx:
                ctx.reserve("web")
                with ctx.span("tool", "search_web"):
                    return []
            return []
        try:
            with activate(context), patch("mult_agents.nodes.search_knowledge_base_records", side_effect=records), patch("mult_agents.nodes.bocha_web_search_records", side_effect=web):
                state = create_initial_state(case["query"], 1, "eval", "eval", run_id=context.run_id)
                result = graph.invoke(state, {"configurable": {"run_id": context.run_id, "thread_id": context.run_id}})
            findings = result.get("verified_findings", [])
            claims = " ".join(f["claim"] for f in findings)
            valid_ids = {e["source_id"] for e in result.get("evidence_pool", [])}
            refs = re.findall(r"\[((?:WEB|LOC)\d+_\d+-\d+)\]", result.get("final", ""))
            entry = {"case": case, "model": config.model, "status": result["status"], "report": result["final"],
                     "verified_findings": findings, "evidence": result.get("evidence_pool", []), "summary": context.summary(),
                     "grading": {"citation_id_validity": sum(s in valid_ids for s in refs) / len(refs) if refs else None,
                                 "keyword_coverage_proxy": sum(k.casefold() in claims.casefold() for k in case["keywords"]) / len(case["keywords"]),
                                 "semantic_support": "requires_human_review", "retrieval_mode": "fixed_fixture"}}
            results.append(entry)
            output = ROOT / args.output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"case": case["id"], "status": result["status"], "findings": len(findings), "model_calls": context.counts["model_calls"]}, ensure_ascii=False), flush=True)
        finally:
            unregister(context.run_id)


if __name__ == "__main__":
    main()
