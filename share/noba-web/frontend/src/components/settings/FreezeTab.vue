<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get, post, del } = useApi()

const windows = ref([])
const frozen = ref(false)
const loading = ref(false)
const error = ref('')
const msg = ref('')

// Form state
const form = ref({ name: '', reason: '', start_iso: '', end_iso: '' })
const saving = ref(false)

function isoToTs(iso) {
  return iso ? Math.floor(new Date(iso).getTime() / 1000) : 0
}
function formatTs(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : '—'
}
function isActive(w) {
  const now = Math.floor(Date.now() / 1000)
  return w.start_ts <= now && w.end_ts >= now
}

async function load() {
  if (!authStore.isAdmin) return
  loading.value = true
  error.value = ''
  try {
    windows.value = await get('/api/enterprise/freeze-windows')
    const status = await get('/api/enterprise/freeze-windows/status')
    frozen.value = status.frozen
  } catch (e) {
    error.value = e.message || 'Failed to load'
  }
  loading.value = false
}

async function createWindow() {
  saving.value = true
  msg.value = ''
  error.value = ''
  try {
    const start_ts = isoToTs(form.value.start_iso)
    const end_ts = isoToTs(form.value.end_iso)
    if (end_ts <= start_ts) {
      error.value = 'End time must be after start time'
      saving.value = false
      return
    }
    await post('/api/enterprise/freeze-windows', {
      name: form.value.name,
      start_ts,
      end_ts,
      reason: form.value.reason,
    })
    msg.value = 'Freeze window created.'
    form.value = { name: '', reason: '', start_iso: '', end_iso: '' }
    await load()
  } catch (e) {
    error.value = e.message || 'Create failed'
  }
  saving.value = false
}

async function removeWindow(id) {
  error.value = ''
  try {
    await del(`/api/enterprise/freeze-windows/${id}`)
    await load()
  } catch (e) {
    error.value = e.message || 'Delete failed'
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
      <h3 style="margin:0">Change Freeze Windows</h3>
      <button class="btn btn-sm" @click="load" :disabled="loading">
        <i class="fas fa-sync" :class="loading ? 'fa-spin' : ''"></i> Refresh
      </button>
    </div>

    <!-- Freeze status banner -->
    <div v-if="frozen" class="alert"
         style="background:var(--warning,#ff9800);color:#fff;font-weight:600;margin-bottom:1rem">
      <i class="fas fa-lock" style="margin-right:.5rem"></i>
      FREEZE ACTIVE — operator writes are currently locked.
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>

    <!-- Create form -->
    <div class="card" style="padding:1rem;margin-bottom:1rem">
      <h5 style="margin:0 0 .75rem 0">Schedule Freeze Window</h5>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem">
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Name</label>
          <input v-model="form.name" class="form-control form-control-sm" placeholder="Release freeze" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Reason (optional)</label>
          <input v-model="form.reason" class="form-control form-control-sm" placeholder="v2.5 release window" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Start</label>
          <input v-model="form.start_iso" type="datetime-local" class="form-control form-control-sm" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">End</label>
          <input v-model="form.end_iso" type="datetime-local" class="form-control form-control-sm" />
        </div>
      </div>
      <button class="btn btn-sm btn-primary"
        style="margin-top:.75rem"
        @click="createWindow"
        :disabled="saving || !form.name || !form.start_iso || !form.end_iso">
        <i class="fas fa-lock"></i> Schedule Freeze
      </button>
    </div>

    <!-- Windows table -->
    <div v-if="loading" style="text-align:center;padding:2rem;color:var(--text-muted)">
      <i class="fas fa-spinner fa-spin"></i>
    </div>
    <div v-else-if="windows.length" class="card" style="padding:0;overflow:hidden">
      <table class="table" style="margin:0;font-size:.85rem">
        <thead>
          <tr>
            <th>Name</th>
            <th>Start</th>
            <th>End</th>
            <th>Status</th>
            <th>Created By</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in windows" :key="w.id">
            <td>
              <strong>{{ w.name }}</strong>
              <div v-if="w.reason" style="font-size:.75rem;color:var(--text-muted)">{{ w.reason }}</div>
            </td>
            <td style="font-size:.8rem;color:var(--text-muted)">{{ formatTs(w.start_ts) }}</td>
            <td style="font-size:.8rem;color:var(--text-muted)">{{ formatTs(w.end_ts) }}</td>
            <td>
              <span v-if="isActive(w)" class="badge" style="background:var(--warning,#ff9800)">Active</span>
              <span v-else-if="w.end_ts < Date.now() / 1000" class="badge" style="background:var(--text-muted)">Expired</span>
              <span v-else class="badge" style="background:var(--info,#2196f3)">Scheduled</span>
            </td>
            <td style="font-size:.8rem">{{ w.created_by }}</td>
            <td>
              <button class="btn btn-xs btn-danger" @click="removeWindow(w.id)">
                <i class="fas fa-trash"></i>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else style="text-align:center;padding:2rem;color:var(--text-muted)">
      No freeze windows configured.
    </div>
  </div>
</template>
