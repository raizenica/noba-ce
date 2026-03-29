<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get, del } = useApi()

const sessions = ref([])
const loading = ref(false)
const error = ref('')
const msg = ref('')

async function load() {
  if (!authStore.isAdmin) return
  loading.value = true
  error.value = ''
  try {
    sessions.value = await get('/api/admin/sessions')
  } catch (e) {
    error.value = e.message || 'Failed to load sessions'
  }
  loading.value = false
}

async function revoke(prefix) {
  error.value = ''
  msg.value = ''
  try {
    await del(`/api/admin/sessions/${encodeURIComponent(prefix.replace('…', ''))}`)
    msg.value = 'Session revoked.'
    await load()
  } catch (e) {
    error.value = e.message || 'Revoke failed'
  }
}

function timeLeft(expires) {
  const diff = new Date(expires) - Date.now()
  if (diff <= 0) return 'expired'
  const h = Math.floor(diff / 3600000)
  const m = Math.floor((diff % 3600000) / 60000)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

onMounted(load)
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
      <h3 style="margin:0">Active Sessions</h3>
      <button class="btn btn-sm" @click="load" :disabled="loading">
        <i class="fas fa-sync" :class="loading ? 'fa-spin' : ''"></i> Refresh
      </button>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>

    <div v-if="loading" style="text-align:center;padding:2rem;color:var(--text-muted)">
      <i class="fas fa-spinner fa-spin"></i>
    </div>
    <div v-else-if="sessions.length" class="card" style="padding:0;overflow:hidden">
      <table class="table" style="margin:0;font-size:.85rem">
        <thead>
          <tr>
            <th>User</th>
            <th>Role</th>
            <th>Token</th>
            <th>Expires In</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in sessions" :key="s.prefix">
            <td><strong>{{ s.username }}</strong></td>
            <td><code>{{ s.role }}</code></td>
            <td style="font-family:monospace;font-size:.8rem;color:var(--text-muted)">{{ s.prefix }}</td>
            <td>{{ timeLeft(s.expires) }}</td>
            <td>
              <button class="btn btn-xs btn-danger" @click="revoke(s.prefix)">
                <i class="fas fa-times"></i> Revoke
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else style="text-align:center;padding:2rem;color:var(--text-muted)">
      No active sessions.
    </div>
  </div>
</template>
