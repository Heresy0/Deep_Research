# Deep Research

基于 LangGraph、FastAPI 和 Vue 的多 Agent 研究助手，支持问题拆解、网络搜索、本地知识库检索、证据分析和 Markdown 报告生成。

## 功能

- 保留 8 个角色，用 LangGraph 固定流程编排；快速问答与研究请求分流。
- 博查网络检索、Milvus 本地检索并行汇合，最多补搜 1 轮。
- Harness 控制模型/工具预算、结构校验、有限重试、证据支持与引用。
- 没有有效证据时返回有限结果或失败说明，停止事实性报告写作。
- PostgreSQL 保存运行、事件、结果与检查点；SSE 支持按序号回放。
- 页面显示运行 ID、状态、调用次数、已知 Token、错误与引用片段；刷新读取原运行。
- JSON 滚动日志、应用级调用轨迹、Prometheus 格式 `/metrics`。
- 会话记忆保留，API/页面默认关闭，可按需启用。

首版修改、实际验证和范围说明见 [首版调整说明](docs/首版调整说明.md)。

## 本地运行

需要 Python 3.12、Node.js 20.19+ 或 22.12+、Docker Desktop，以及有效的百炼和博查 API Key。

在项目根目录的 PowerShell 中执行：

```powershell
Copy-Item .env.local.example .env.local
# 编辑 .env.local，填写 DASHSCOPE_API_KEY 和 BOCHA_API_KEY。
uv venv .venv --python 3.12 --cache-dir .uv-cache
uv pip install --python .venv\Scripts\python.exe --cache-dir .uv-cache -r requirements.txt
docker compose -f docker-compose.local.yml up -d --wait --wait-timeout 300
.\.venv\Scripts\python.exe local_run.py check
.\.venv\Scripts\python.exe local_run.py backend
```

在另一个 PowerShell 中安装前端依赖并启动：

```powershell
cd front\agent_front
npm ci
cd ..\..
.\.venv\Scripts\python.exe local_run.py frontend
```

访问前端 `http://127.0.0.1:5173`，接口文档 `http://127.0.0.1:8002/docs`。PostgreSQL 使用 5433 端口，Milvus 使用 19530 端口。

## 导入知识库

```powershell
.\.venv\Scripts\python.exe local_run.py ingest "D:\资料目录"
```

支持 UTF-8 `.txt`、`.md`、`.markdown` 文件，目录递归导入。重复导入会追加文档。

## 首版默认预算

| 项目 | 默认值 |
| --- | --- |
| 补搜 | 最多 1 轮 |
| 模型调用 | 16 次，包含结构修复与支持性检查 |
| 博查 HTTP 尝试 | 12 次，包含失败与重试 |
| 工具调用 | 24 次，包含检索、记忆操作和 Embedding 批次 |
| 活动时间 | 180 秒；研究阶段预留 15 秒和 2 次模型调用收尾 |
| 并发研究 | 2 个；繁忙返回 HTTP 429 |
| 模型输入 | 28,000 字符；共享证据池最多 10 条 |

在 `.env.local` 中设置 `RESEARCH_MAX_*`，修改后重启后端。时间预算在调用边界检查，不会立即中断在途请求；用量未知时明确标记，费用不作估算。

## API 与运行记录

- `POST /api/v1/research/run`：启动并等待结果。
- `POST /api/v1/research/stream`：启动一次研究；响应头 `X-Research-Run-ID`，SSE 带 `id`/`seq`。
- `GET /api/v1/research/runs/{run_id}`：查看运行状态与结果。
- `GET /api/v1/research/runs/{run_id}/events?after_seq=10`：读取后续事件，也支持 `Last-Event-ID`。
- `GET /health`：应用存活检查；`GET /metrics`：进程内聚合指标。

终态包括 `completed`、`partial`、`failed`。刷新或断线后用 GET 读取原运行；再次 POST 会创建新运行。首版仅支持单后端进程，重启后将未完成运行标记为 `PROCESS_INTERRUPTED`，不自动恢复执行。

## 验证

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='app'
.\.venv\Scripts\python.exe -m unittest tests.test_controls -v
.\.venv\Scripts\python.exe -m evals.run --check-fixtures
```

以上控制测试不调用付费模型、博查或 Embedding。PostgreSQL 集成测试需设置 `RESEARCH_TEST_POSTGRES_DSN`，数据库名必须以 `_test` 结尾，详细步骤见 `evals/README.md`。

```powershell
# 使用真实模型，消耗模型 API 额度；检索固定为离线资料，不调用博查/Embedding。
.\.venv\Scripts\python.exe -m evals.run --live-model
cd front\agent_front
npm run build
```

`.github/workflows/checks.yml` 配置控制测试、隔离 PostgreSQL 集成测试和前端构建；CI 不运行付费模型评测。语义支持需人工复核，引用 ID 有效不等于事实准确。

## 首版范围

网络证据来自搜索摘要，未抓取网页正文；本地入库沿用 TXT/Markdown，重复导入会追加。首版未增加 Redis、持久化队列、取消/续跑、OTel 采集平台或多用户认证。用户/租户字段是记忆键，不构成访问控制；按默认地址用于本地开发与演示。

运行与事件可以手动清理：`python scripts/cleanup_runs.py --days 14`。该脚本只删除到期终态运行及其事件，不清理检查点、知识库或记忆。

## 目录

| 路径 | 用途 |
| --- | --- |
| `app/backend/` | FastAPI 接口与 SSE |
| `app/mult_agents/` | Agent、工作流、状态与工具 |
| `app/mult_agents/harness/` | 预算、校验、日志、指标和 Embedding 边界 |
| `app/mult_agents/rag/` | 知识库检索与入库 |
| `app/mult_agents/memory/` | 记忆管理 |
| `front/agent_front/` | Vue 前端 |
| `tests/`、`evals/` | 控制回归、数据库集成、固定资料质量评测 |
| `local_run.py` | 本地启动与检查入口 |
| `docker-compose.local.yml` | 本地 PostgreSQL 与 Milvus |

模型、检索和入库会消耗外部 API 额度。真实 Key、本地数据库、依赖目录和生成文件不提交到版本库。
