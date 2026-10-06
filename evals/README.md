# 首版验证与固定资料评测

## 控制回归：不调用付费 API

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='app'
.\.venv\Scripts\python.exe -m unittest tests.test_controls -v
.\.venv\Scripts\python.exe -m evals.run --check-fixtures
```

10 条测试覆盖认证失败、正常空结果、有限重试、结构修复、无效引用/引文/疑问句、预算、重复查询、运行隔离、并行汇合、容量拒绝与事件回放。一个测试可包含多个相关场景，不等于只验证十次断言。

## PostgreSQL 集成：独立测试库

数据库名必须以 `_test` 结尾；测试会修改该库中的运行、事件和检查点。只使用专门的测试库，不指向工作数据库。使用默认本地 Compose 时：

```powershell
# 首次执行，若库已存在则跳过创建步骤。
docker compose -f docker-compose.local.yml exec postgres psql -U deepresearch -d deepresearch -c "CREATE DATABASE deepresearch_test"
$env:RESEARCH_TEST_POSTGRES_DSN='postgresql://deepresearch:deepresearch_local@127.0.0.1:5433/deepresearch_test'
.\.venv\Scripts\python.exe -m unittest tests.test_postgres -v
Remove-Item Env:RESEARCH_TEST_POSTGRES_DSN
```

3 条测试验证并发序号、终态原子提交、重开连接后的结果持久化、重启中断标记、真实 PostgreSQL 检查点隔离及事件重连。测试清理自己创建的运行记录，测试检查点保留在独立测试库中。

## 质量评测：真实模型与固定检索

`fixtures/solutions.md` 是人工编写的虚构方案资料，`cases.json` 包含十个问题、支持原文与关键词。评测替换网络与本地检索返回值，使用真实工作流和配置的模型，不调用博查、Milvus 或 Embedding。

```powershell
# 会消耗模型 API 额度。
.\.venv\Scripts\python.exe -m evals.run --live-model
# 调试一个案例：
.\.venv\Scripts\python.exe -m evals.run --live-model --case q08 --output output/eval-q08.json
```

默认每个案例独立运行、记忆关闭、最多补搜一轮。模型输出有随机性；这十个案例是小型回归样本，不能代表真实搜索质量或所有业务问题。

结果保存在忽略提交的 `output/eval-results.json`，包含报告、接受结论、来源、用量和评分：

- `citation_id_validity`：报告出现的引用 ID 是否来自实际证据池，只验证关联。
- `keyword_coverage_proxy`：接受结论是否出现预设关键词，只是覆盖率代理。
- `semantic_support`：默认 `requires_human_review`。逐条对照来源片段，检查数字、限定、否定、推断及问题覆盖；不能把前两项当准确率。

本次实现的人工检查与实际结果见 [首版调整说明](../docs/首版调整说明.md)。真实模型评测不在默认 CI 中运行。

## 前端与 CI

```powershell
cd front\agent_front
npm ci
npm run build
```

GitHub Actions 配置三项独立工作：控制回归与资料校验、前端类型检查/构建、独立 PostgreSQL 服务集成测试。配置文件已添加；未推送的本地修改不会触发 GitHub 工作流。
