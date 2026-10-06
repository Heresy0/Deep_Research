import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from backend.schemas import ResearchRequest, ResearchResponse
from backend.service import WorkflowService, get_workflow_service
from backend.service.workflow_service import CapacityExceeded

router = APIRouter(prefix="/api/v1/research", tags=["research"])


async def _start(payload, service):
    try:
        return await asyncio.to_thread(service.start_run, payload.model_dump())
    except CapacityExceeded as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": "5"}) from exc
    except Exception as exc:
        logging.getLogger("backend.api").error("run_start_failed | exception_type=%s", type(exc).__name__)
        raise HTTPException(503, "研究服务或运行存储暂不可用。") from exc


def _response(service, run_id, after=0):
    async def stream():
        async for event in service.events(run_id, after):
            yield f"id: {event['seq']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Research-Run-ID": run_id})


@router.post("/run", response_model=ResearchResponse)
async def run_research(payload: ResearchRequest, workflow_service: WorkflowService = Depends(get_workflow_service)):
    run_id = await _start(payload, workflow_service)
    return await workflow_service.wait_result(run_id)


@router.post("/stream")
async def stream_research(payload: ResearchRequest, workflow_service: WorkflowService = Depends(get_workflow_service)):
    run_id = await _start(payload, workflow_service)
    return _response(workflow_service, run_id)


@router.get("/runs/{run_id}")
async def get_run(run_id: UUID, workflow_service: WorkflowService = Depends(get_workflow_service)):
    run = await asyncio.to_thread(workflow_service.get_run, str(run_id))
    if not run:
        raise HTTPException(404, "运行记录不存在。")
    return run


@router.get("/runs/{run_id}/events")
async def run_events(run_id: UUID, after_seq: int = Query(default=0, ge=0),
                     last_event_id: str | None = Header(default=None),
                     workflow_service: WorkflowService = Depends(get_workflow_service)):
    run_id = str(run_id)
    if not await asyncio.to_thread(workflow_service.get_run, run_id):
        raise HTTPException(404, "运行记录不存在。")
    if last_event_id is not None:
        try:
            cursor = int(last_event_id)
            if cursor < 0:
                raise ValueError()
            after_seq = max(after_seq, cursor)
        except ValueError as exc:
            raise HTTPException(400, "Last-Event-ID 必须是非负事件序号。") from exc
    return _response(workflow_service, run_id, after_seq)
