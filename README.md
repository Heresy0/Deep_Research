# Deep Research

基于 LangGraph、FastAPI 和 Vue 的多 Agent 研究助手，支持问题拆解、网络搜索、本地知识库检索、证据分析和 Markdown 报告生成。

## 功能

- 简单问题直接回答，研究问题进入多 Agent 工作流。
- 博查网络检索与 Milvus 本地知识库检索。
- 证据整理、分析、补充检索与报告生成。
- SSE 输出工作流进度和最终结果。
- PostgreSQL 保存对话记忆和工作流检查点。

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

## 当前验证状态

- 简单问答、SSE 返回、数据库连接、工作流初始化、前端类型检查和构建已验证。
- 联网研究需要有效的博查 Key；本地知识库需要自行导入资料。
- 无证据时仍可能生成长篇报告，需要增加证据不足的明确提示和输出约束。
- 搜索词生成、补搜策略、结论与引用的一致性仍需完善。

## 目录

| 路径 | 用途 |
| --- | --- |
| `app/backend/` | FastAPI 接口与 SSE |
| `app/mult_agents/` | Agent、工作流、状态与工具 |
| `app/mult_agents/rag/` | 知识库检索与入库 |
| `app/mult_agents/memory/` | 记忆管理 |
| `front/agent_front/` | Vue 前端 |
| `local_run.py` | 本地启动与检查入口 |
| `docker-compose.local.yml` | 本地 PostgreSQL 与 Milvus |

模型、检索和入库会消耗外部 API 额度。真实 Key、本地数据库、依赖目录和生成文件不提交到版本库。
