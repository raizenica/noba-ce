<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useApi } from '../../composables/useApi'
import { LOG_AUTO_REFRESH_MS } from '../../constants'

const { get } = useApi()

const LOG_TYPES = ['syserr', 'syslog', 'auth', 'kern', 'daemon', 'dpkg', 'apt', 'nginx', 'docker']

const selectedLog    = ref('syserr')
const logContent     = ref('')
const logLoading     = ref(false)
const logAutoRefresh = ref(false)
let   _logTimer      = null

async function fetchLog() {
  logLoading.value = true
  try {
    const text = await get(`/api/log-viewer?type=${selectedLog.value}`)
    logContent.value = typeof text === 'string' ? text : ''
    await nextTick()
    const el = document.getElementById('syslog-pre')
    if (el) el.scrollTop = el.scrollHeight
  } catch (e) {
    logContent.value = 'Failed to fetch log: ' + e.message
  } finally {
    logLoading.value = false
  }
}

function toggleLogAutoRefresh() {
  logAutoRefresh.value = !logAutoRefresh.value
  if (_logTimer) { clearInterval(_logTimer); _logTimer = null }
  if (logAutoRefresh.value) {
    _logTimer = setInterval(fetchLog, LOG_AUTO_REFRESH_MS)
  }
}

function nextTick() {
  return new Promise(r => setTimeout(r, 0))
}

onMounted(() => {
  fetchLog()
})

onUnmounted(() => {
  if (_logTimer) { clearInterval(_logTimer); _logTimer = null }
})

defineExpose({ fetchLog })
</script>

<template>
  <div>
    <div style="display:flex;gap:.4rem;flex-wrap:wrap;align-items:center;margin-bottom:.5rem">
      <select
        v-model="selectedLog"
        style="background:var(--surface-2);border:1px solid var(--border);color:var(--text);padding:3px 8px;border-radius:4px;font-size:.8rem"
        @change="fetchLog"
      >
        <option v-for="t in LOG_TYPES" :key="t" :value="t">{{ t }}</option>
      </select>
      <button class="btn btn-xs" :disabled="logLoading" @click="fetchLog">
        <i class="fas" :class="logLoading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i> Refresh
      </button>
      <button
        class="btn btn-xs"
        :class="{ 'btn-primary': logAutoRefresh }"
        @click="toggleLogAutoRefresh"
      >
        <i class="fas fa-clock"></i> Auto-refresh
      </button>
      <span v-if="logAutoRefresh" style="font-size:.7rem;color:var(--text-muted)">every 5s</span>
    </div>
    <pre
      id="syslog-pre"
      class="log-pre"
      style="max-height:55vh;overflow:auto;margin:0;padding:12px;font-size:.75rem;white-space:pre-wrap;word-break:break-all"
    >{{ logContent || 'No content.' }}</pre>
  </div>
</template>
