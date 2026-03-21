<script setup>
import { ref, watch, onUnmounted } from 'vue'
import AppModal from '../ui/AppModal.vue'
import { useApi } from '../../composables/useApi'
import { useAuthStore } from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'

const props = defineProps({
  show: Boolean,
})
const emit = defineEmits(['close'])

const authStore = useAuthStore()
const notify    = useNotificationsStore()
const { request } = useApi()

// ── State ─────────────────────────────────────────────────────────────────
const title       = ref('Running...')
const output      = ref('')
const running     = ref(false)
const activeRunId = ref(null)
let _pollTimer    = null

// ── Public API (called from parent) ───────────────────────────────────────
async function startRun(automation) {
  title.value   = `Running: ${automation.name}`
  output.value  = `>> [${new Date().toLocaleTimeString()}] Starting automation...\n`
  running.value = true
  activeRunId.value = null

  const token = authStore.token
  let runId = null

  try {
    const res = await fetch(`/api/automations/${automation.id}/run`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      title.value    = '\u2717 Failed'
      output.value  += (err.detail || 'Request failed') + '\n'
      notify.addToast(err.detail || `${automation.name} failed to start`, 'error')
      running.value = false
      return
    }
    const result = await res.json()
    if (result.workflow) {
      title.value    = '\u2713 Workflow Started'
      output.value  += `Workflow "${automation.name}" started with ${result.steps} steps.\nCheck Run History for progress.\n`
      notify.addToast(`Workflow started (${result.steps} steps)`, 'success')
      running.value = false
      return
    }
    runId = result.run_id
    activeRunId.value = runId
  } catch {
    title.value    = '\u2717 Connection Error'
    output.value  += 'Connection error\n'
    notify.addToast('Connection error', 'error')
    running.value = false
    return
  }

  // Poll every 1 s
  _pollTimer = setInterval(async () => {
    if (!authStore.authenticated) { stopPoll(); running.value = false; return }
    try {
      const r = await fetch(`/api/runs/${runId}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!r.ok) return
      const run = await r.json()
      if (run.output) output.value = run.output
      scrollConsole()
      if (run.status !== 'running') {
        stopPoll()
        const ok = run.status === 'done'
        title.value = ok ? '\u2713 Completed'
          : run.status === 'cancelled' ? '\u2718 Cancelled'
          : '\u2717 ' + (run.status === 'timeout' ? 'Timed Out' : 'Failed')
        if (run.error) output.value += '\n' + run.error + '\n'
        notify.addToast(`${automation.name} ${run.status}`, ok ? 'success' : 'error')
        running.value = false
        activeRunId.value = null
      }
    } catch { /* non-fatal */ }
  }, 1000)
}

async function cancelRun() {
  if (!activeRunId.value) return
  try {
    await fetch(`/api/runs/${activeRunId.value}/cancel`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${authStore.token}` },
    })
    notify.addToast('Cancellation requested', 'info')
  } catch { /* silent */ }
}

function stopPoll() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null }
}

function scrollConsole() {
  const el = document.getElementById('run-console-out')
  if (el) el.scrollTop = el.scrollHeight
}

// Clean up poll if modal closes
watch(() => props.show, (v) => { if (!v) stopPoll() })
onUnmounted(() => stopPoll())

defineExpose({ startRun })
</script>

<template>
  <AppModal :show="show" :title="title" width="680px" @close="emit('close')">
    <div style="padding:1rem">
      <pre
        id="run-console-out"
        style="
          background: #0e0e10;
          color: #e0e0e0;
          font-family: monospace;
          font-size: .75rem;
          line-height: 1.5;
          padding: .75rem;
          border-radius: 5px;
          min-height: 200px;
          max-height: 420px;
          overflow-y: auto;
          white-space: pre-wrap;
          word-break: break-all;
        "
      >{{ output || '(no output)' }}</pre>
    </div>

    <template #footer>
      <button
        v-if="running && activeRunId"
        class="btn btn-danger btn-sm"
        @click="cancelRun"
      >
        <i class="fas fa-stop" style="margin-right:.3rem"></i>Cancel
      </button>
      <span
        v-if="running"
        style="font-size:.8rem;color:var(--text-muted);display:flex;align-items:center;gap:.4rem"
      >
        <i class="fas fa-spinner fa-spin"></i> Running...
      </span>
      <button class="btn" @click="emit('close')">Close</button>
    </template>
  </AppModal>
</template>
