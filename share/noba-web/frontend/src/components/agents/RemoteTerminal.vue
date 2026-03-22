<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAuthStore } from '../../stores/auth'

const props = defineProps({
  hostname: { type: String, required: true },
  visible: { type: Boolean, default: true },
})

const { post, get } = useApi()
const authStore = useAuthStore()

// ── State ────────────────────────────────────────────────────────────────────
const input        = ref('')
const lines        = ref([])
const sending      = ref(false)
const cmdHistory   = ref([])
const historyIdx   = ref(-1)
const scrollEl     = ref(null)
const inputEl      = ref(null)
const pollTimer    = ref(null)
const pendingCmdId = ref('')

// ── Scroll to bottom ─────────────────────────────────────────────────────────
function scrollBottom() {
  nextTick(() => {
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  })
}

// ── Push a line ──────────────────────────────────────────────────────────────
function pushLine(text, type = 'output') {
  lines.value.push({ text, type, ts: Date.now() })
  // Keep last 500 lines
  if (lines.value.length > 500) lines.value = lines.value.slice(-500)
  scrollBottom()
}

// ── Execute command ──────────────────────────────────────────────────────────
async function execute() {
  const cmd = input.value.trim()
  if (!cmd) return

  // Add to history
  if (cmdHistory.value[cmdHistory.value.length - 1] !== cmd) {
    cmdHistory.value.push(cmd)
    if (cmdHistory.value.length > 100) cmdHistory.value.shift()
  }
  historyIdx.value = -1

  pushLine(`${props.hostname}$ ${cmd}`, 'input')
  input.value = ''
  sending.value = true

  // Handle built-in commands
  if (cmd === 'clear') {
    lines.value = []
    sending.value = false
    return
  }
  if (cmd === 'help') {
    pushLine('Built-in commands: clear, help, history', 'system')
    pushLine('All other input is executed as shell commands on the remote agent.', 'system')
    sending.value = false
    return
  }
  if (cmd === 'history') {
    cmdHistory.value.forEach((c, i) => pushLine(`  ${i + 1}  ${c}`, 'system'))
    sending.value = false
    return
  }

  try {
    const resp = await post(`/api/agents/${encodeURIComponent(props.hostname)}/command`, {
      type: 'exec',
      params: { command: cmd, timeout: 30 },
    })
    pendingCmdId.value = resp.id || ''
    if (resp.websocket) {
      pushLine('(sent via WebSocket)', 'system')
    }
    // Start polling for result
    startPoll()
  } catch (e) {
    pushLine(`Error: ${e.message || e}`, 'error')
    sending.value = false
  }
}

// ── Poll for results ─────────────────────────────────────────────────────────
let pollCount = 0

function startPoll() {
  stopPoll()
  pollCount = 0
  pollTimer.value = setInterval(async () => {
    pollCount++
    try {
      const results = await get(`/api/agents/${encodeURIComponent(props.hostname)}/results`)
      if (Array.isArray(results) && results.length > 0) {
        const last = results[results.length - 1]
        if (last.id === pendingCmdId.value || pollCount >= 3) {
          let output = ''
          if (last.stdout) output = last.stdout
          else if (last.message) output = last.message
          else if (last.error) output = last.error
          else output = JSON.stringify(last, null, 2)

          const isError = last.status === 'error' || last.exit_code > 0
          output.split('\n').forEach(line => pushLine(line, isError ? 'error' : 'output'))

          if (last.exit_code !== undefined && last.exit_code !== 0) {
            pushLine(`(exit code: ${last.exit_code})`, 'system')
          }

          stopPoll()
          sending.value = false
          pendingCmdId.value = ''
        }
      }
    } catch { /* silent */ }
    // Timeout after 60s of polling
    if (pollCount >= 30) {
      pushLine('(timed out waiting for response)', 'error')
      stopPoll()
      sending.value = false
    }
  }, 2000)
}

function stopPoll() {
  if (pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

// ── Keyboard ─────────────────────────────────────────────────────────────────
function onKeydown(e) {
  if (e.key === 'Enter') {
    e.preventDefault()
    execute()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (cmdHistory.value.length === 0) return
    if (historyIdx.value < 0) historyIdx.value = cmdHistory.value.length
    historyIdx.value = Math.max(0, historyIdx.value - 1)
    input.value = cmdHistory.value[historyIdx.value] || ''
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (historyIdx.value < 0) return
    historyIdx.value = Math.min(cmdHistory.value.length, historyIdx.value + 1)
    input.value = historyIdx.value >= cmdHistory.value.length ? '' : cmdHistory.value[historyIdx.value]
  } else if (e.key === 'l' && e.ctrlKey) {
    e.preventDefault()
    lines.value = []
  }
}

// ── Focus input when terminal area clicked ───────────────────────────────────
function focusInput() {
  inputEl.value?.focus()
}

// ── Lifecycle ────────────────────────────────────────────────────────────────
watch(() => props.visible, (val) => {
  if (val) nextTick(() => inputEl.value?.focus())
})

watch(() => props.hostname, () => {
  lines.value = []
  pushLine(`Connected to ${props.hostname}`, 'system')
  pushLine('Type commands to execute on the remote agent. Use "help" for built-in commands.', 'system')
})

onMounted(() => {
  if (props.hostname) {
    pushLine(`Connected to ${props.hostname}`, 'system')
    pushLine('Type commands to execute on the remote agent. Use "help" for built-in commands.', 'system')
  }
  nextTick(() => inputEl.value?.focus())
})

onUnmounted(() => stopPoll())
</script>

<template>
  <div class="remote-terminal" @click="focusInput">
    <div class="term-header">
      <i class="fas fa-terminal" style="margin-right:.4rem;opacity:.6"></i>
      <span style="font-weight:600;font-size:.75rem">{{ hostname }}</span>
      <span v-if="sending" style="margin-left:.5rem;font-size:.65rem;color:var(--warning)">
        <i class="fas fa-circle-notch fa-spin"></i> running...
      </span>
      <button
        class="btn btn-xs"
        style="margin-left:auto;opacity:.5"
        title="Clear terminal"
        @click.stop="lines = []"
      ><i class="fas fa-eraser"></i></button>
    </div>

    <div ref="scrollEl" class="term-output">
      <div
        v-for="(line, i) in lines"
        :key="i"
        class="term-line"
        :class="`term-${line.type}`"
      >{{ line.text }}</div>
    </div>

    <div class="term-input-row">
      <span class="term-prompt">{{ hostname }}$</span>
      <input
        ref="inputEl"
        v-model="input"
        class="term-input"
        :disabled="!authStore.isOperator"
        :placeholder="authStore.isOperator ? 'Type a command...' : 'Operator access required'"
        spellcheck="false"
        autocomplete="off"
        @keydown="onKeydown"
      >
    </div>
  </div>
</template>

<style scoped>
.remote-terminal {
  display: flex;
  flex-direction: column;
  background: #0d1117;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: .75rem;
  min-height: 300px;
}

.term-header {
  display: flex;
  align-items: center;
  padding: .4rem .6rem;
  background: #161b22;
  border-bottom: 1px solid #21262d;
  color: #8b949e;
  font-size: .7rem;
}

.term-output {
  flex: 1;
  overflow-y: auto;
  padding: .5rem .6rem;
  min-height: 200px;
  max-height: 400px;
}

.term-line {
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
  padding: 0 .2rem;
}

.term-input { color: #58a6ff; }
.term-output-line, .term-output { color: #c9d1d9; }
.term-error { color: #f85149; }
.term-system { color: #8b949e; font-style: italic; }

.term-input-row {
  display: flex;
  align-items: center;
  padding: .3rem .6rem;
  background: #0d1117;
  border-top: 1px solid #21262d;
}

.term-prompt {
  color: #3fb950;
  margin-right: .4rem;
  white-space: nowrap;
  font-weight: 600;
}

.term-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: #c9d1d9;
  font-family: inherit;
  font-size: inherit;
  caret-color: #58a6ff;
}

.term-input::placeholder {
  color: #484f58;
}

.term-input:disabled {
  cursor: not-allowed;
  opacity: .5;
}
</style>
