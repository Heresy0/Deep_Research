# Windows 本地运行

项目目录：`D:\code\deep_research`。运行时使用 `.env.local` 中的本地服务配置，并从原有 `.env` 补充模型和搜索 Key。

## 已准备的环境

- Python 3.12 独立环境：`.venv`，按原有 `requirements.txt` 安装。
- PostgreSQL：`127.0.0.1:5433`，数据保存在专属 Docker volume。
- Milvus 2.6.4：`127.0.0.1:19530`，采用内嵌 etcd 和本地存储，仅适用于本地开发。
- 后端：`http://127.0.0.1:8002`，前端：`http://127.0.0.1:5173`。
- 记忆与知识库使用两个独立的 Milvus 集合。

本机另一个项目占用了 8000 和 5432，因此本项目使用 8002 和 5433。Redis、Neo4j、MySQL 无需启动。

## 每次启动

打开 Docker Desktop，等待引擎运行。在 PowerShell 中执行：

```powershell
cd D:\code\deep_research
docker compose -f docker-compose.local.yml up -d --wait --wait-timeout 300
.\.venv\Scripts\python.exe local_run.py check
.\.venv\Scripts\python.exe local_run.py backend
```

保持后端终端打开，再开第二个 PowerShell：

```powershell
cd D:\code\deep_research
.\.venv\Scripts\python.exe local_run.py frontend
```

浏览器打开 `http://127.0.0.1:5173`。后端接口文档为 `http://127.0.0.1:8002/docs`。

如果端口已经运行，直接访问页面，不要再重复启动；需要重启时先在对应终端按 Ctrl+C。

## Key 与首次研究

模型调用使用 `DASHSCOPE_API_KEY`，联网搜索使用 `BOCHA_API_KEY`。可在 `.env.local` 添加自己的 Key，优先于 `.env`。`local_run.py check` 只检查是否填写，不验证额度或有效性。

先发送简单问题验证模型，例如“什么是 Agent？”；再发送行业研究问题验证搜索及报告链路。研究和文本入库会调用外部 API 并消耗相应额度。

知识库初始为空，联网研究仍可使用；要验证本地 RAG，可导入自己的 UTF-8 文本：

```powershell
cd D:\code\deep_research
.\.venv\Scripts\python.exe local_run.py ingest "D:\你的资料目录"
```

支持 `.txt`、`.md`、`.markdown`，目录会递归导入；重复运行会追加文档。PDF、Word 不在此脚本支持范围内。

## 停止

前后端在各自终端按 Ctrl+C。本项目 Docker 服务可单独停止，数据保留：

```powershell
docker compose -f D:\code\deep_research\docker-compose.local.yml stop
```

## 重新安装依赖

现有 `.venv` 可直接使用。需要重建时，先安装 Python 3.12 和 uv，再执行：

```powershell
cd D:\code\deep_research
uv venv .venv --python 3.12 --cache-dir .uv-cache
uv pip install --python .venv\Scripts\python.exe --cache-dir .uv-cache -r requirements.txt
```

前端使用 Node.js 20.19+ 或 22.12+。常规 Node.js 安装包含 npm，可按锁文件重新安装：

```powershell
cd D:\code\deep_research\front\agent_front
npm ci
```

## 验证范围

2026-10-06 已验证：Python 依赖无冲突、PostgreSQL/Milvus 连接正常、数据库自动建表、Agent 工作流初始化、后端健康接口、前端页面及代理、前端类型检查与生产构建。

本地连接检查及 `local_run.py init` 不发送模型、Embedding 或搜索请求。工作流初始化成功与健康接口正常不能证明外部 Key 有效，也不能替代一次完整行业研究。

2026-10-06 实际问答检查：受限执行环境连接 DashScope 出现 TLS EOF，普通执行环境 HTTPS 连接正常。后端已切换为普通执行环境；真实模型请求返回 `401 InvalidApiKey`。需要在 `.env.local` 填写有效的 `DASHSCOPE_API_KEY` 并重启后端。普通 PowerShell 可使用上面的启动命令，无需关闭证书校验。

随后用户更新 Key 并重启，真实问答返回 `400 Arrearage`。请在 Key 所属阿里云账号检查欠费；无欠费时核对 Key 所属账号并联系阿里云支持。处理账号状态后可直接重新发送请求；若再次更换 Key，需要重启后端。

## 部署参考

Milvus 本地存储配置参照其 [官方内嵌部署脚本](https://github.com/milvus-io/milvus/blob/v2.6.4/scripts/standalone_embed.sh)。此项目把启动配置整理为 Docker Compose，以便在 Windows 使用。
