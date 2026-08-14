<template>
  <div class="ai-learning-page">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon class="title-icon"><ChatDotSquare /></el-icon>
        AI辅助学习
      </h1>
      <p class="page-subtitle">快来问问你的学习小助手吧</p>
    </div>

    <!-- 模式选择 -->
    <div class="mode-selector" role="group" aria-label="学习模式">
      <button
        class="mode-btn"
        :class="{ active: mode === 'explore' }"
        :disabled="hasMessages"
        @click="selectMode('explore')"
      >
        <el-icon><Compass /></el-icon>
        <span>探索全新领域</span>
      </button>
      <button
        class="mode-btn"
        :class="{ active: mode === 'reinforce' }"
        :disabled="hasMessages"
        @click="selectMode('reinforce')"
      >
        <el-icon><Reading /></el-icon>
        <span>加强已有知识</span>
      </button>
    </div>

    <!-- 对话区域 -->
    <div class="chat-container" ref="chatContainer">
      <div v-if="!hasMessages" class="chat-placeholder">
        <el-icon class="placeholder-icon"><ChatLineRound /></el-icon>
        <p>选择学习模式，开始与 AI 助手对话</p>
        <p class="placeholder-hint">支持上传文件，AI 会基于文件内容或知识库回答</p>
      </div>

      <div
        v-for="(msg, idx) in messages"
        :key="msg.message_id || idx"
        class="message-row"
        :class="msg.role"
      >
        <div class="message-avatar">
          <el-icon v-if="msg.role === 'user'"><User /></el-icon>
          <el-icon v-else><MagicStick /></el-icon>
        </div>
        <div class="message-body">
          <div class="message-role">{{ msg.role === 'user' ? '你' : 'AI 助手' }}</div>
          <div class="message-content" v-html="renderMarkdown(msg.content)"></div>

          <!-- 引用卡片 -->
          <div v-if="msg.citations && msg.citations.length" class="citations">
            <div class="citations-label">引用来源</div>
            <div
              v-for="(cit, ci) in msg.citations"
              :key="ci"
              class="citation-card"
            >
              <div class="citation-source">{{ cit.source_name }}</div>
              <div class="citation-excerpt">{{ cit.excerpt }}</div>
              <div class="citation-score">相关度: {{ cit.score }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 加载中 -->
      <div v-if="isLoading" class="message-row assistant">
        <div class="message-avatar">
          <el-icon><MagicStick /></el-icon>
        </div>
        <div class="message-body">
          <div class="typing-indicator">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="input-area">
      <!-- 文件上传 -->
      <div class="file-upload-row">
        <el-upload
          :auto-upload="false"
          :show-file-list="false"
          :on-change="handleFileChange"
          accept=".pdf,.doc,.docx,.ppt,.pptx,.txt"
        >
          <el-button size="small" :disabled="!mode">
            <el-icon><Document /></el-icon>
            上传文件
          </el-button>
        </el-upload>
        <span v-if="selectedFile" class="file-name">
          {{ selectedFile.name }}
          <el-button
            type="text"
            size="small"
            @click.stop="clearFile"
          >移除</el-button>
        </span>
      </div>

      <!-- 输入框 + 发送 -->
      <div class="input-row">
        <el-input
          v-model="inputText"
          type="textarea"
          :rows="2"
          :placeholder="inputPlaceholder"
          :disabled="!mode || isLoading"
          @keydown.enter.exact.prevent="sendMessage"
        />
        <el-button
          type="primary"
          :disabled="!canSend"
          :loading="isLoading"
          @click="sendMessage"
        >
          <el-icon><Promotion /></el-icon>
          发送
        </el-button>
      </div>

      <!-- 总结对话 -->
      <div class="summary-row">
        <el-button
          :disabled="!hasMessages || isLoading"
          @click="generateSummary"
        >
          <el-icon><DocumentChecked /></el-icon>
          总结对话
        </el-button>
        <span v-if="summaryResult" class="summary-success">
          已生成：{{ summaryResult.title }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ChatDotSquare,
  Compass,
  Reading,
  ChatLineRound,
  User,
  MagicStick,
  Document,
  Promotion,
  DocumentChecked
} from '@element-plus/icons-vue'
import {
  createAILearningSession,
  sendAILearningMessage,
  getAILearningSession,
  summarizeAILearningSession
} from '../services/api'
import type { AIMessage, AICitation, AISession } from '../types'

// ──────────────────────────────────────────
// 状态
// ──────────────────────────────────────────

const mode = ref<'explore' | 'reinforce'>('explore')
const sessionId = ref<string | null>(null)
const messages = ref<AIMessage[]>([])
const inputText = ref('')
const isLoading = ref(false)
const selectedFile = ref<File | null>(null)
const fileText = ref('')
const summaryResult = ref<{ title: string; artifact_id: string } | null>(null)
const chatContainer = ref<HTMLElement | null>(null)

// ──────────────────────────────────────────
// 计算属性
// ──────────────────────────────────────────

const hasMessages = computed(() => messages.value.length > 0)

const canSend = computed(() => {
  return !!mode.value && !!inputText.value.trim() && !isLoading.value
})

const inputPlaceholder = computed(() => {
  if (!mode.value) return '请先选择学习模式'
  if (mode.value === 'explore') return '输入你想学习的主题或问题...'
  return '输入你想巩固的问题或知识点...'
})

// ──────────────────────────────────────────
// 方法
// ──────────────────────────────────────────

function selectMode(m: 'explore' | 'reinforce') {
  if (hasMessages.value) return
  mode.value = m
}

async function loadHistory() {
  // 尝试加载最近的会话
  try {
    const sessions = await getAILearningSessions(1)
    if (sessions.length > 0) {
      const latest = sessions[0]
      const detail = await getAILearningSession(latest.session_id)
      sessionId.value = detail.session_id
      mode.value = detail.mode
      messages.value = detail.messages || []
      await scrollToBottom()
    }
  } catch {
    // 没有历史会话，忽略
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

async function sendMessage() {
  if (!canSend.value || !sessionId.value) return

  const text = inputText.value.trim()
  inputText.value = ''
  isLoading.value = true
  scrollToBottom()

  try {
    const reply = await sendAILearningMessage(sessionId.value, {
      content: text,
      fileText: fileText.value || undefined,
    })

    messages.value.push({
      message_id: `user_${Date.now()}`,
      session_id: sessionId.value,
      role: 'user',
      content: text,
      citations: [],
      created_at: new Date().toISOString(),
    })
    messages.value.push({
      message_id: reply.message_id,
      session_id: sessionId.value,
      role: 'assistant',
      content: reply.content,
      citations: reply.citations as AICitation[],
      created_at: new Date().toISOString(),
    })
    clearFile()
  } catch (err: any) {
    ElMessage.error(err.message || '发送消息失败')
  } finally {
    isLoading.value = false
    scrollToBottom()
  }
}

async function generateSummary() {
  if (!sessionId.value || isLoading.value) return
  isLoading.value = true
  try {
    const result = await summarizeAILearningSession(sessionId.value)
    summaryResult.value = {
      title: result.title,
      artifact_id: result.artifact_id,
    }
    ElMessage.success(`总结已保存：${result.title}`)
  } catch (err: any) {
    ElMessage.error(err.message || '生成总结失败')
  } finally {
    isLoading.value = false
  }
}

// 文件上传处理
function handleFileChange(file: any) {
  if (!file) return
  selectedFile.value = file.raw
  const reader = new FileReader()
  reader.onload = () => {
    fileText.value = reader.result as string
  }
  reader.readAsText(file.raw)
}

function clearFile() {
  selectedFile.value = null
  fileText.value = ''
}

// 简单 Markdown 渲染（加粗、换行、代码块）
function renderMarkdown(text: string): string {
  if (!text) return ''
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  // 代码块
  html = html.replace(/```[\s\S]*?```/g, (match) => {
    const inner = match.slice(3, -3).trim()
    return `<pre><code>${inner}</code></pre>`
  })
  // 行内代码
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')
  // 加粗
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  // 换行
  html = html.replace(/\n/g, '<br>')
  return html
}

// ──────────────────────────────────────────
// 生命周期
// ──────────────────────────────────────────

onMounted(async () => {
  try {
    // 用系统默认配置创建会话
    const resp = await createAILearningSession({
      mode: 'explore',
      userApiKey: '',
    })
    sessionId.value = resp.session_id
    mode.value = resp.mode

    // 如果创建时带了 first_message（这里没有），处理回复
    if (resp.reply) {
      messages.value.push({
        message_id: resp.reply.message_id,
        session_id: resp.session_id,
        role: 'assistant',
        content: resp.reply.content,
        citations: resp.reply.citations as AICitation[],
        created_at: new Date().toISOString(),
      })
    }

    // 加载历史
    await loadHistory()
  } catch (err: any) {
    ElMessage.error(err.message || '初始化学习会话失败')
  }
})
</script>

<style scoped>
.ai-learning-page {
  --bg-card: var(--bg-surface, #f7faf8);
  --border-subtle: #d7e3d9;
  --border-default: #bfd0c3;
  --text-primary: #183229;
  --text-secondary: #4d655b;
  --text-muted: #6d8077;
  --accent: #5b8a72;

  max-width: 900px;
  margin: 0 auto;
  padding: 24px;
}

.page-header {
  margin-bottom: 24px;
}

.page-title {
  font-size: 26px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 6px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-icon {
  color: var(--accent);
}

.page-subtitle {
  font-size: 15px;
  color: var(--text-muted);
  margin: 0;
}

/* 模式选择 */
.mode-selector {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.mode-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 20px;
  background: var(--bg-card);
  border: 2px solid var(--border-subtle);
  border-radius: 14px;
  color: var(--text-secondary);
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.mode-btn:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.mode-btn.active {
  background: rgba(91, 138, 114, 0.12);
  border-color: var(--accent);
  color: var(--accent);
  font-weight: 600;
}

.mode-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 对话区域 */
.chat-container {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 16px;
  min-height: 400px;
  max-height: 520px;
  overflow-y: auto;
  padding: 20px;
  margin-bottom: 16px;
}

.chat-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 340px;
  color: var(--text-muted);
  text-align: center;
}

.placeholder-icon {
  font-size: 48px;
  margin-bottom: 16px;
  opacity: 0.5;
}

.placeholder-hint {
  font-size: 13px;
  margin-top: 8px;
  opacity: 0.7;
}

/* 消息 */
.message-row {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.message-row.user {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 18px;
}

.message-row.user .message-avatar {
  background: #d7e3d9;
  color: var(--text-primary);
}

.message-row.assistant .message-avatar {
  background: rgba(91, 138, 114, 0.15);
  color: var(--accent);
}

.message-body {
  max-width: 75%;
}

.message-role {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.message-row.user .message-role {
  text-align: right;
}

.message-content {
  background: #fff;
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  padding: 12px 16px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-primary);
  word-break: break-word;
}

.message-row.user .message-content {
  background: rgba(91, 138, 114, 0.08);
  border-color: rgba(91, 138, 114, 0.2);
}

.message-content :deep(pre) {
  background: #f0f4f2;
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
  font-size: 13px;
}

.message-content :deep(code) {
  background: #f0f4f2;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}

.message-content :deep(strong) {
  color: var(--text-primary);
}

/* 引用卡片 */
.citations {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.citations-label {
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 500;
}

.citation-card {
  background: rgba(91, 138, 114, 0.05);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 13px;
}

.citation-source {
  font-weight: 600;
  color: var(--accent);
  margin-bottom: 4px;
}

.citation-excerpt {
  color: var(--text-secondary);
  line-height: 1.5;
  margin-bottom: 4px;
}

.citation-score {
  font-size: 12px;
  color: var(--text-muted);
}

/* 输入中动画 */
.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background: var(--accent);
  border-radius: 50%;
  animation: bounce 1.2s infinite;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-6px); opacity: 1; }
}

/* 输入区域 */
.input-area {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.file-upload-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.file-name {
  font-size: 13px;
  color: var(--text-secondary);
}

.input-row {
  display: flex;
  gap: 10px;
}

.input-row .el-input {
  flex: 1;
}

.input-row .el-button {
  align-self: flex-end;
}

.summary-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.summary-success {
  font-size: 13px;
  color: var(--accent);
}

/* 响应式 */
@media (max-width: 768px) {
  .ai-learning-page {
    padding: 16px;
  }

  .mode-selector {
    flex-direction: column;
  }

  .message-body {
    max-width: 85%;
  }

  .chat-container {
    min-height: 300px;
    max-height: 400px;
  }
}
</style>
