<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'

type RunSummary = {
  model_calls?: number; web_calls?: number; tool_calls?: number; duration_ms?: number
  termination_reason?: string; errors?: { code: string; provider: string; message: string }[]
  token_usage?: { input_tokens: number; output_tokens: number; status: string }
}
type Source = { source_id: string; title: string; url?: string; doc_id?: string; snippet: string; retrieval_level?: string }
type RunResult = { run_id: string; status: string; final: string; run_summary: RunSummary; sources: Source[] }
type StreamEvent = Partial<RunResult> & {
  type: string; seq?: number; message?: string; node?: string; kind?: string; name?: string
}
type SavedRun = { runId: string; query: string; seq: number; userId: string; threadId: string; tenantId: string }

type ChatMessage = {
  id: string
  role: 'user' | 'assistant' | 'status'
  content: string
}

const userId = ref('user01')
const threadId = ref('thread01')
const tenantId = ref('default_tenant')
const query = ref('')
const loading = ref(false)
const errorMessage = ref('')
const messageListRef = ref<HTMLElement | null>(null)
const composerRef = ref<HTMLTextAreaElement | null>(null)
const progressLogs = ref<string[]>([])
const runId = ref('')
const runStatus = ref('')
const runSummary = ref<RunSummary>({})
const runSources = ref<Source[]>([])
const enableMemory = ref(false)
let activeRun: SavedRun | null = null
const storageKey = 'deepresearch.latest-run'
const statusLabels: Record<string, string> = { running: '执行中', completed: '已完成', partial: '有限结果', failed: '执行失败' }
const nodeLabels: Record<string, string> = {
  intent: '识别意图', direct_answer: '快速回答', plan: '规划问题', web_search: '网络取证', local_rag: '知识库取证',
  deep_dive: '审计证据', analyze: '分析结论', reflect: '规划补搜', verify: '检查证据支持', write: '组织报告', finish: '返回有限结果',
}
const saveRun = () => { if (activeRun) localStorage.setItem(storageKey, JSON.stringify(activeRun)) }
const safeUrl = (url?: string) => url?.startsWith('https://') || url?.startsWith('http://') ? url : undefined
const starterPrompts = [
  {
    title: '深度调研',
    prompt:
      '请调研“企业知识库 Agent 平台”市场，按市场规模、主要竞品、收费模式三部分输出，并在每部分附上可追溯来源链接。',
  },
  {
    title: '方案对比',
    prompt:
      '我们要做多 Agent 研究助手，请对比“纯大模型直答”“RAG 单 Agent”“多 Agent 协作”三种方案，给出优缺点、适用场景与推荐结论。',
  },
  {
    title: '知识问答',
    prompt: '请解释这个项目里“意图分流”的作用，以及简单问题和复杂问题分别会走哪条链路。',
  },
  {
    title: '落地计划',
    prompt: '请把“上线一个可用的 DeepResearch MVP”拆成两周计划，按每天输出任务、验收标准和风险点。',
  },
]
const capabilityHighlights = [
  {
    title: '多智能体编排',
    desc: '自动完成规划、检索、证据裁判、分析与写作，减少手工研究路径。',
  },
  {
    title: '双源检索融合',
    desc: '网络信息与本地知识库并行召回，输出结论同时保留来源可追溯性。',
  },
  {
    title: '会话记忆增强',
    desc: '跨轮次继承用户偏好与历史任务，持续提升回答一致性和效率。',
  },
]
const landingMetrics = [
  { label: '执行模式', value: 'Quick + Deep' },
  { label: '检索来源', value: 'Web + Local' },
  { label: '输出风格', value: '结论 + 证据' },
]
const messages = ref<ChatMessage[]>([
  {
    id: `m-${Date.now()}`,
    role: 'assistant',
    content: '你好，我是 DeepResearch。你可以直接提问，我会根据意图自动走快速回答或完整研究链路。',
  },
])

const escapeHtml = (value: string): string =>
  value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')

const markdownToHtml = (markdown: string): string => {
  const codeBlocks: string[] = []
  let text = markdown.replace(/```([\s\S]*?)```/g, (_, block) => {
    const index = codeBlocks.length
    codeBlocks.push(`<pre><code>${escapeHtml(String(block).trim())}</code></pre>`)
    return `@@CODE_BLOCK_${index}@@`
  })
  const lines = text.split('\n')
  const out: string[] = []
  let inList = false
  const closeList = () => {
    if (inList) {
      out.push('</ul>')
      inList = false
    }
  }
  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line) {
      closeList()
      continue
    }
    if (line.startsWith('# ')) {
      closeList()
      out.push(`<h1>${escapeHtml(line.slice(2))}</h1>`)
      continue
    }
    if (line.startsWith('## ')) {
      closeList()
      out.push(`<h2>${escapeHtml(line.slice(3))}</h2>`)
      continue
    }
    if (line.startsWith('### ')) {
      closeList()
      out.push(`<h3>${escapeHtml(line.slice(4))}</h3>`)
      continue
    }
    if (line.startsWith('- ') || line.startsWith('* ')) {
      if (!inList) {
        out.push('<ul>')
        inList = true
      }
      out.push(`<li>${escapeHtml(line.slice(2))}</li>`)
      continue
    }
    closeList()
    out.push(`<p>${escapeHtml(line)}</p>`)
  }
  closeList()
  let html = out.join('')
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')
  html = html.replace(/\[([^[\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
  html = html.replace(/@@CODE_BLOCK_(\d+)@@/g, (_, idx) => codeBlocks[Number(idx)] || '')
  return html
}

const renderMessageHtml = (message: ChatMessage) => markdownToHtml(message.content || '')

const scrollToBottom = async () => {
  await nextTick()
  const el = messageListRef.value
  if (el) {
    el.scrollTop = el.scrollHeight
  }
}

const createNewChat = () => {
  messages.value = [
    {
      id: `m-${Date.now()}`,
      role: 'assistant',
      content: '已开始新会话。你可以继续提问。',
    },
  ]
  progressLogs.value = []
  errorMessage.value = ''
  query.value = ''
  threadId.value = crypto.randomUUID()
  activeRun = null
  runId.value = ''
  runStatus.value = ''
  runSummary.value = {}
  runSources.value = []
  localStorage.removeItem(storageKey)
}

const usePrompt = async (prompt: string) => {
  query.value = prompt
  errorMessage.value = ''
  await nextTick()
  composerRef.value?.focus()
}

const applyStarterByIndex = (index: number) => {
  const target = starterPrompts[index]
  if (!target) return
  usePrompt(target.prompt)
}

const pushProgress = (message: string) => {
  const msg = message.trim()
  if (!msg) return
  const last = progressLogs.value[progressLogs.value.length - 1]
  if (last === msg) return
  progressLogs.value.push(msg)
  if (progressLogs.value.length > 6) {
    progressLogs.value = progressLogs.value.slice(-6)
  }
}

const showProgress = (statusId: string) => {
  const message = messages.value.find(m => m.id === statusId)
  if (message) message.content = ['研究正在执行...', ...progressLogs.value].map(line => `- ${line}`).join('\n')
}

const applyResult = (result: RunResult, statusId: string) => {
  runId.value = result.run_id
  runStatus.value = result.status
  runSummary.value = result.run_summary || {}
  runSources.value = result.sources || []
  messages.value = messages.value.filter(m => m.id !== statusId && m.id !== `a-${result.run_id}`)
  messages.value.push({ id: `a-${result.run_id}`, role: 'assistant', content: result.final })
  errorMessage.value = ''
}

const consume = async (response: Response, statusId: string): Promise<boolean> => {
  if (!response.ok) throw new Error((await response.text()) || `请求失败: ${response.status}`)
  if (!response.body) throw new Error('流式响应不可用')
  const headerRun = response.headers.get('X-Research-Run-ID')
  if (headerRun && activeRun) { activeRun.runId = headerRun; runId.value = headerRun; saveRun() }
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = '', finished = false
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split(/\r?\n\r?\n/)
      buffer = parts.pop() || ''
      for (const part of parts) {
        const data = part.split(/\r?\n/).find(line => line.startsWith('data: '))
        if (!data) continue
        const event = JSON.parse(data.slice(6)) as StreamEvent
        if (event.run_id && activeRun) {
          activeRun.runId = event.run_id
          activeRun.seq = event.seq || activeRun.seq
          runId.value = event.run_id
          saveRun()
        }
        if (event.type === 'call_start' && event.kind === 'node') pushProgress(`开始：${nodeLabels[event.name || ''] || event.name}`)
        if (event.type === 'phase') pushProgress(`完成：${nodeLabels[event.node || ''] || event.node}`)
        if (event.type === 'warning') pushProgress(event.message || '执行出现问题，正在返回可用结果')
        if (event.type === 'status') pushProgress(event.message || '研究已接收')
        showProgress(statusId)
        if (event.type === 'final') {
          applyResult(event as RunResult, statusId)
          finished = true
        }
      }
      await scrollToBottom()
    }
  } finally { reader.releaseLock() }
  return finished
}

const reconnect = async (statusId: string) => {
  if (!activeRun?.runId) throw new Error('连接中断且未取得运行 ID；不会自动重复提交研究。')
  let lastError: unknown
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const response = await fetch(`/api/v1/research/runs/${activeRun.runId}`)
      if (!response.ok) throw new Error(`运行查询失败: ${response.status}`)
      const record = await response.json() as { status: string; result: RunResult | null }
      if (record.status !== 'running' && record.result) { applyResult(record.result, statusId); return }
      const events = await fetch(`/api/v1/research/runs/${activeRun.runId}/events?after_seq=${activeRun.seq}`)
      if (await consume(events, statusId)) return
    } catch (error) { lastError = error }
    await new Promise(resolve => setTimeout(resolve, 500 * (attempt + 1)))
  }
  throw lastError || new Error('连接暂不可用；研究可能仍在执行，可稍后点击重新连接。')
}

const reportError = (error: unknown, statusId: string) => {
  errorMessage.value = error instanceof Error ? error.message : '请求失败'
  messages.value = messages.value.filter(m => m.id !== statusId)
}

const runResearch = async () => {
  const userText = query.value.trim()
  if (!userText || loading.value) return
  loading.value = true
  errorMessage.value = ''
  progressLogs.value = []
  runSummary.value = {}
  runSources.value = []
  runStatus.value = 'running'
  runId.value = ''
  query.value = ''
  activeRun = { runId: '', query: userText, seq: 0, userId: userId.value, threadId: threadId.value, tenantId: tenantId.value }
  localStorage.removeItem(storageKey)
  messages.value.push({ id: `u-${Date.now()}`, role: 'user', content: userText })
  const statusId = `s-${Date.now()}`
  messages.value.push({ id: statusId, role: 'status', content: '正在提交研究...' })
  await scrollToBottom()
  try {
    const response = await fetch('/api/v1/research/stream', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: userText, user_id: userId.value.trim() || 'default_user',
        thread_id: threadId.value.trim() || 'default_thread', tenant_id: tenantId.value.trim() || 'default_tenant',
        max_iterations: 1, enable_memory: enableMemory.value }),
    })
    const acceptedRun = response.headers.get('X-Research-Run-ID')
    if (acceptedRun && activeRun) { activeRun.runId = acceptedRun; runId.value = acceptedRun; saveRun() }
    if (!await consume(response, statusId)) await reconnect(statusId)
  } catch (error) {
    if (activeRun?.runId) {
      try { await reconnect(statusId) } catch (reconnectError) { reportError(reconnectError, statusId) }
    } else { runStatus.value = ''; reportError(error, statusId) }
  } finally { loading.value = false; await scrollToBottom() }
}

const reconnectLatest = async () => {
  if (loading.value || !activeRun?.runId) return
  loading.value = true
  errorMessage.value = ''
  const statusId = `s-${Date.now()}`
  messages.value.push({ id: statusId, role: 'status', content: '正在读取运行记录，不会重新执行研究...' })
  try { await reconnect(statusId) } catch (error) { reportError(error, statusId) }
  finally { loading.value = false; await scrollToBottom() }
}

onMounted(async () => {
  const saved = localStorage.getItem(storageKey)
  if (!saved) return
  try {
    activeRun = JSON.parse(saved) as SavedRun
    if (!activeRun || !/^[0-9a-f-]{36}$/i.test(activeRun.runId) || !Number.isInteger(activeRun.seq) || activeRun.seq < 0
      || ![activeRun.query, activeRun.userId, activeRun.threadId, activeRun.tenantId].every(v => typeof v === 'string')) {
      activeRun = null
      localStorage.removeItem(storageKey)
      return
    }
    runId.value = activeRun.runId
    userId.value = activeRun.userId
    threadId.value = activeRun.threadId
    tenantId.value = activeRun.tenantId
    messages.value.push({ id: `u-${activeRun.runId}`, role: 'user', content: activeRun.query })
    await reconnectLatest()
  } catch { localStorage.removeItem(storageKey) }
})
</script>

<template>
  <div class="chat-shell">
    <aside class="chat-sidebar">
      <div class="sidebar-brand">
        <p class="brand-badge">AI Copilot</p>
        <h1>DeepResearch</h1>
        <p class="brand-desc">多智能体研究工作台，支持快速回答与深度调研。</p>
      </div>
      <div class="sidebar-head">
        <button class="new-chat-btn" :disabled="loading" @click="createNewChat">新建会话</button>
      </div>
      <div class="quick-entry">
        <p class="section-title">推荐起手问题</p>
        <button
          v-for="item in starterPrompts.slice(0, 3)"
          :key="item.title"
          class="quick-entry-btn"
          @click="usePrompt(item.prompt)"
        >
          {{ item.title }}
        </button>
      </div>
      <div class="settings-group">
        <label>User ID</label>
        <input v-model="userId" class="sidebar-input" />
      </div>
      <div class="settings-group">
        <label>Thread ID</label>
        <input v-model="threadId" class="sidebar-input" />
      </div>
      <div class="settings-group">
        <label>Tenant ID</label>
        <input v-model="tenantId" class="sidebar-input" />
      </div>
      <label class="memory-toggle"><input v-model="enableMemory" type="checkbox" />启用会话记忆（默认关闭）</label>
      <p class="hint-text">当前会话记忆键：{{ userId }} / {{ threadId }}</p>
    </aside>

    <main class="chat-main">
      <header class="main-header">
        <div>
          <h2>DeepResearch Enterprise Workspace</h2>
          <p>技术选型与资料研究：展示结论、证据与执行限制。网络来源基于搜索摘要。</p>
        </div>
        <div class="header-tags">
          <span>Evidence-Driven</span>
          <span>Structured Output</span>
          <span>Memory-Powered</span>
        </div>
      </header>
      <details v-if="runId" class="run-details" open>
        <summary>本次运行 · {{ statusLabels[runStatus] || '连接中' }}</summary>
        <p>运行 ID：{{ runId }}</p>
        <p v-if="runSummary.model_calls !== undefined">
          模型调用 {{ runSummary.model_calls }} · 网络检索请求 {{ runSummary.web_calls }} · 工具调用 {{ runSummary.tool_calls }} ·
          耗时 {{ ((runSummary.duration_ms || 0) / 1000).toFixed(1) }} 秒
        </p>
        <p v-if="runSummary.token_usage">已知 Token：输入 {{ runSummary.token_usage.input_tokens }} / 输出 {{ runSummary.token_usage.output_tokens }}（{{ runSummary.token_usage.status }}）</p>
        <p v-if="runSummary.termination_reason">停止原因：{{ runSummary.termination_reason }}</p>
        <p v-for="(error, index) in runSummary.errors || []" :key="index">{{ error.provider }} · {{ error.code }}：{{ error.message }}</p>
        <button v-if="errorMessage && !loading" @click="reconnectLatest">重新连接本次运行</button>
        <details v-if="runSources.length"><summary>查看报告引用的证据片段（{{ runSources.length }}）</summary>
          <article v-for="source in runSources" :key="source.source_id" class="source-card">
            <strong>[{{ source.source_id }}] {{ source.title }}</strong>
            <p><a v-if="safeUrl(source.url)" :href="safeUrl(source.url)" target="_blank" rel="noreferrer">打开来源</a><span v-else>{{ source.doc_id }}</span>
              · {{ source.retrieval_level === 'summary_only' ? '搜索摘要，未读取全文' : '本地资料片段' }}</p>
            <p>{{ source.snippet }}</p>
          </article>
        </details>
      </details>
      <div ref="messageListRef" class="message-list">
        <section v-if="messages.length <= 1" class="onboarding-panel">
          <div class="hero-panel">
            <p class="hero-badge">商业研究 · 策略分析 · 知识问答</p>
            <h3>第一步先讲清目标，再交给 DeepResearch 自动推进</h3>
            <p class="hero-desc">
              推荐提问结构：目标 + 背景约束 + 期望输出。系统会自动选择快速回答或深度研究链路。
            </p>
            <div class="hero-actions">
              <button class="hero-btn primary" @click="applyStarterByIndex(0)">快速开始调研</button>
              <button class="hero-btn" @click="applyStarterByIndex(1)">查看方案对比</button>
            </div>
            <div class="metric-grid">
              <article v-for="item in landingMetrics" :key="item.label">
                <p>{{ item.label }}</p>
                <strong>{{ item.value }}</strong>
              </article>
            </div>
          </div>
          <div class="capability-grid">
            <article v-for="item in capabilityHighlights" :key="item.title" class="capability-card">
              <h4>{{ item.title }}</h4>
              <p>{{ item.desc }}</p>
            </article>
          </div>
          <div class="guide-panel">
            <h4>提问指南</h4>
            <div class="guide-grid">
              <article>
                <h5>1. 说明目标</h5>
                <p>你要解决什么问题、面向谁、希望达到什么结果。</p>
              </article>
              <article>
                <h5>2. 提供上下文</h5>
                <p>给出已知信息、时间范围、数据口径、业务限制。</p>
              </article>
              <article>
                <h5>3. 指定输出</h5>
                <p>例如“表格输出”“附来源链接”“分点行动清单”。</p>
              </article>
            </div>
          </div>
          <div class="prompt-list">
            <button v-for="item in starterPrompts" :key="item.prompt" class="prompt-chip" @click="usePrompt(item.prompt)">
              {{ item.prompt }}
            </button>
          </div>
        </section>
        <div
          v-for="message in messages"
          :key="message.id"
          class="message-row"
          :class="`role-${message.role}`"
        >
          <div class="avatar">{{ message.role === 'user' ? '你' : message.role === 'status' ? '...' : 'AI' }}</div>
          <div class="bubble markdown-body" v-html="renderMessageHtml(message)"></div>
        </div>
      </div>
      <div class="composer">
        <textarea
          v-model="query"
          ref="composerRef"
          class="composer-input"
          :disabled="loading"
          placeholder="输入你的问题，回车发送（Shift + Enter 换行）"
          @keydown.enter.exact.prevent="runResearch"
        />
        <button class="send-btn" :disabled="loading || !query.trim()" @click="runResearch">
          {{ loading ? '处理中...' : '发送' }}
        </button>
      </div>
      <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
    </main>
  </div>
</template>

<style scoped>
.run-details { margin: 0 24px 12px; padding: 12px 16px; border: 1px solid #dce4ee; border-radius: 12px; background: #f8fafc; max-height: 260px; overflow: auto; font-size: 13px; }
.run-details p { margin: 6px 0; overflow-wrap: anywhere; }
.run-details summary { cursor: pointer; font-weight: 600; }
.source-card { margin-top: 10px; padding: 10px; background: white; border-radius: 8px; }
.memory-toggle { display: flex; align-items: center; gap: 6px; font-size: 12px; margin: 12px 0; }
</style>
