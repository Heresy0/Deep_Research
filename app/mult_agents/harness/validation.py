import json
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from .runtime import ExecutionError


class Plan(BaseModel):
    objective: str = ""
    sub_questions: list[str] = Field(min_length=1, max_length=5)
    outline: list[dict] = Field(default_factory=list, max_length=6)
    research_questions: list[str] = Field(default_factory=list)
    budget: dict = Field(default_factory=dict)


class EvidenceBatch(BaseModel):
    summary: str = ""
    evidence: list[dict] = Field(max_length=24)
    gaps: list[str] = Field(default_factory=list)
    rejected_source_ids: list[str] = Field(default_factory=list)
    reject_reason: str = ""


class Audit(BaseModel):
    summary: str = ""
    evidence_pool: list[dict] = Field(max_length=48)
    audit_flags: list[dict] = Field(default_factory=list)


class Finding(BaseModel):
    claim_id: str = Field(min_length=1, max_length=80)
    claim: str = Field(min_length=1, max_length=1200)
    confidence: Literal["high", "medium", "low"] = "low"
    source_ids: list[str] = Field(min_length=1, max_length=6)
    kind: Literal["fact", "inference", "recommendation"] = "fact"


class Analysis(BaseModel):
    analysis_summary: str = ""
    needs_more_research: bool = Field(default=False, strict=True)
    missing_gaps: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(max_length=12)
    claim_map: list[dict] = Field(default_factory=list)


class Query(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    section_id: str = "gap"
    source_preference: Literal["web", "local", "hybrid"] = "hybrid"
    reason: str = ""


class Reflection(BaseModel):
    reflection_summary: str = ""
    supplementary_queries: list[Query] = Field(max_length=6)


class EvidenceQuote(BaseModel):
    source_id: str
    quote: str = Field(min_length=4, max_length=600)


class SupportDecision(BaseModel):
    claim_id: str
    verdict: Literal["supported", "unsupported", "uncertain"]
    source_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    evidence_quotes: list[EvidenceQuote] = Field(min_length=1, max_length=6)


class Support(BaseModel):
    decisions: list[SupportDecision] = Field(max_length=12)


class Section(BaseModel):
    heading: Literal["核心结论", "方案比较", "部署与集成", "成本与维护", "风险与限制", "实施建议"]
    claim_ids: list[str] = Field(min_length=1, max_length=12)


class ReportLayout(BaseModel):
    sections: list[Section] = Field(min_length=1, max_length=6)


SCHEMAS = {"intent": None, "plan": Plan, "web_search": EvidenceBatch, "local_rag": EvidenceBatch,
           "deep_dive": Audit, "analyze": Analysis, "reflect": Reflection, "verify": Support, "write": ReportLayout}


def parse_output(text, node):
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value)
    try:
        data = json.loads(value)
        schema = SCHEMAS.get(node)
        if schema:
            return schema.model_validate(data).model_dump()
        if not isinstance(data, dict) or data.get("route") not in {"direct", "multiagent"}:
            raise ValueError("route")
        return data
    except (ValueError, TypeError, ValidationError) as exc:
        raise ExecutionError("MODEL_OUTPUT_INVALID", "model") from exc


def supported_findings(findings, evidence):
    valid = {e["source_id"] for e in evidence if e.get("source_id") and e.get("snippet")}
    accepted, seen = [], set()
    for finding in findings:
        ids = finding.get("source_ids", [])
        claim_id = finding.get("claim_id")
        if claim_id and claim_id not in seen and ids and set(ids) <= valid and not re.search(r"[?？]", finding.get("claim", "")):
            accepted.append(finding)
            seen.add(claim_id)
    return accepted


def render_report(state, sections=None, limited=False):
    findings = state.get("verified_findings", [])
    by_id = {f["claim_id"]: f for f in findings}
    sections = list(sections or [{"heading": "核心结论", "claim_ids": list(by_id)}])
    selected = {cid for section in sections for cid in section.get("claim_ids", [])}
    omitted = [cid for cid in by_id if cid not in selected]
    if omitted:
        sections.append({"heading": "核心结论", "claim_ids": omitted})
    lines = ["# 研究结果", "", "本报告依据检索摘要与本地资料片段；网络来源未抓取全文。", ""]
    used, rendered = [], set()
    for section in sections:
        items = [by_id[cid] for cid in section.get("claim_ids", []) if cid in by_id and cid not in rendered]
        if not items:
            continue
        lines.extend([f"## {section['heading']}", ""])
        for finding in items:
            refs = " ".join(f"[{sid}]" for sid in finding["source_ids"])
            label = {"fact": "事实", "inference": "推断", "recommendation": "建议"}.get(finding.get("kind", "fact"), "事实")
            # Model text cannot insert arbitrary links/citations into deterministic output.
            claim = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", finding["claim"])
            claim = re.sub(r"\[(?:WEB|LOC)[^]]*\]", "", claim).replace("\n", " ")
            lines.append(f"- 【{label}】{claim} {refs}")
            used.extend(finding["source_ids"])
            rendered.add(finding["claim_id"])
        lines.append("")
    lines.extend(["## 研究限制", ""])
    if not findings:
        lines.append("未取得可支持结论的证据，未生成事实性研究报告。")
    if limited:
        lines.append("本次返回有限结果，尚未完整回答全部研究问题。")
    for gap in state.get("missing_gaps", [])[:8]:
        lines.append(f"- 未覆盖：{gap}")
    for error in state.get("retrieval_errors", []):
        lines.append(f"- {error.get('provider', 'workflow')}：{error.get('message', '执行失败')}")
    if state.get("termination_reason"):
        from .runtime import MESSAGES
        lines.append(f"- 停止原因：{MESSAGES.get(state['termination_reason'], state['termination_reason'])}")
    lines.extend(["", "## 参考资料", ""])
    lookup = {e["source_id"]: e for e in state.get("evidence_pool", []) if e.get("source_id")}
    for sid in dict.fromkeys(used):
        e = lookup[sid]
        title = str(e.get("title") or sid).replace("\n", " ")
        locator = str(e.get("url") or e.get("doc_id") or "")
        if locator.startswith(("http://", "https://")):
            # Percent-encode characters which would break a Markdown URL.
            locator = locator.replace("(", "%28").replace(")", "%29").replace(" ", "%20")
            lines.append(f"- [{sid}] [{title.replace('[', '').replace(']', '')}]({locator})")
        else:
            lines.append(f"- [{sid}] {title}（本地资料：{locator}）")
    if not used:
        lines.append("- 无已引用来源。")
    return "\n".join(lines)
