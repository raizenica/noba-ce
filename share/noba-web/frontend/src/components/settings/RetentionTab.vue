<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get, put } = useApi()

const ret = ref({ metrics_days: 30, audit_days: 90, alerts_days: 30, job_runs_days: 30 })
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const msg = ref('')

async function load() {
  if (!authStore.isAdmin) return
  loading.value = true
  error.value = ''
  try { ret.value = await get('/api/enterprise/retention') }
  catch (e) { error.value = e.message || 'Failed to load' }
  loading.value = false
}

async function save() {
  saving.value = true; msg.value = ''; error.value = ''
  try {
    await put('/api/enterprise/retention', ret.value)
    msg.value = 'Retention policy saved.'
  } catch (e) { error.value = e.message || 'Save failed' }
  saving.value = false
}

onMounted(load)
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
      <h3 style="margin:0">Data Retention</h3>
      <button class="btn btn-sm" @click="load" :disabled="loading">
        <i class="fas fa-sync" :class="loading ? 'fa-spin' : ''"></i> Refresh
      </button>
    </div>
    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>
    <div v-if="loading" style="text-align:center;padding:2rem;color:var(--text-muted)">
      <i class="fas fa-spinner fa-spin"></i>
    </div>
    <div v-else class="card" style="padding:1rem">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Metrics (days)</label>
          <input v-model.number="ret.metrics_days" type="number" min="1" max="3650"
            class="form-control form-control-sm" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Audit Log (days)</label>
          <input v-model.number="ret.audit_days" type="number" min="1" max="3650"
            class="form-control form-control-sm" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Alerts (days)</label>
          <input v-model.number="ret.alerts_days" type="number" min="1" max="3650"
            class="form-control form-control-sm" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Job Runs (days)</label>
          <input v-model.number="ret.job_runs_days" type="number" min="1" max="3650"
            class="form-control form-control-sm" />
        </div>
      </div>
      <button class="btn btn-sm btn-primary" style="margin-top:1rem" @click="save" :disabled="saving">
        <i class="fas fa-save"></i> Save
      </button>
      <div style="font-size:.75rem;color:var(--text-muted);margin-top:.75rem">
        Data older than the configured number of days is automatically purged during nightly maintenance.
      </div>
    </div>
  </div>
</template>
