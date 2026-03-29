<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get, put, post, del } = useApi()

const policy = ref({
  min_length: 8, require_uppercase: true, require_digit: true,
  require_special: false, max_age_days: 0, history_count: 0,
})
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const msg = ref('')

async function load() {
  if (!authStore.isAdmin) return
  loading.value = true
  error.value = ''
  try {
    policy.value = await get('/api/enterprise/password-policy')
  } catch (e) {
    error.value = e.message || 'Failed to load policy'
  }
  loading.value = false
}

async function save() {
  saving.value = true
  msg.value = ''
  error.value = ''
  try {
    await put('/api/enterprise/password-policy', policy.value)
    msg.value = 'Password policy saved.'
  } catch (e) {
    error.value = e.message || 'Save failed'
  }
  saving.value = false
}

const ipRules = ref([])
const ipForm = ref({ cidr: '', label: '' })
const ipSaving = ref(false)

async function loadIpRules() {
  try { ipRules.value = await get('/api/enterprise/login-ip-rules') } catch {}
}
async function addIpRule() {
  ipSaving.value = true
  error.value = ''
  try {
    await post('/api/enterprise/login-ip-rules', ipForm.value)
    ipForm.value = { cidr: '', label: '' }
    await loadIpRules()
  } catch (e) { error.value = e.message || 'Failed to add rule' }
  ipSaving.value = false
}
async function removeIpRule(id) {
  try { await del(`/api/enterprise/login-ip-rules/${id}`); await loadIpRules() }
  catch (e) { error.value = e.message || 'Delete failed' }
}

onMounted(() => { load(); loadIpRules() })
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
      <h3 style="margin:0">Password Policy</h3>
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
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Minimum Length</label>
          <input v-model.number="policy.min_length" type="number" min="6" max="128"
            class="form-control form-control-sm" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Max Age (days, 0=never)</label>
          <input v-model.number="policy.max_age_days" type="number" min="0"
            class="form-control form-control-sm" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">History Count (0=disabled)</label>
          <input v-model.number="policy.history_count" type="number" min="0" max="50"
            class="form-control form-control-sm" />
        </div>
        <div></div>
        <div style="display:flex;gap:1.5rem;align-items:center">
          <label style="font-size:.85rem">
            <input type="checkbox" v-model="policy.require_uppercase" style="margin-right:.4rem" />
            Require uppercase
          </label>
        </div>
        <div style="display:flex;gap:1.5rem;align-items:center">
          <label style="font-size:.85rem">
            <input type="checkbox" v-model="policy.require_digit" style="margin-right:.4rem" />
            Require digit
          </label>
        </div>
        <div style="display:flex;gap:1.5rem;align-items:center">
          <label style="font-size:.85rem">
            <input type="checkbox" v-model="policy.require_special" style="margin-right:.4rem" />
            Require special character
          </label>
        </div>
      </div>
      <div style="margin-top:1rem;display:flex;gap:.5rem">
        <button class="btn btn-sm btn-primary" @click="save" :disabled="saving">
          <i class="fas fa-save"></i> Save Policy
        </button>
      </div>
      <div style="font-size:.75rem;color:var(--text-muted);margin-top:.75rem">
        Changes apply to new passwords immediately. Set max_age_days > 0 to enforce password rotation.
        History count prevents reuse of the N most recent passwords.
      </div>
    </div>

    <!-- Login IP Allowlist -->
    <div class="card" style="padding:1rem;margin-top:1rem">
      <h5 style="margin:0 0 .75rem 0">Login IP Allowlist</h5>
      <div style="font-size:.75rem;color:var(--text-muted);margin-bottom:.75rem">
        No rules = all IPs allowed. Adding rules restricts login to matching CIDRs only.
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr auto;gap:.5rem;align-items:end">
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">CIDR</label>
          <input v-model="ipForm.cidr" class="form-control form-control-sm" placeholder="10.0.0.0/24" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Label</label>
          <input v-model="ipForm.label" class="form-control form-control-sm" placeholder="Office" />
        </div>
        <button class="btn btn-sm btn-primary" @click="addIpRule"
          :disabled="ipSaving || !ipForm.cidr">
          <i class="fas fa-plus"></i> Add
        </button>
      </div>
      <div v-if="ipRules.length" style="margin-top:.75rem">
        <div v-for="r in ipRules" :key="r.id"
          style="display:flex;align-items:center;gap:.5rem;padding:.3rem 0;border-bottom:1px solid var(--border)">
          <code style="flex:1">{{ r.cidr }}</code>
          <span style="flex:1;font-size:.8rem;color:var(--text-muted)">{{ r.label }}</span>
          <button class="btn btn-xs btn-danger" @click="removeIpRule(r.id)">
            <i class="fas fa-trash"></i>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
