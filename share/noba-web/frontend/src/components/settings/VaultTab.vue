<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get, post, del } = useApi()

const secrets = ref([])
const loading = ref(false)
const error = ref('')
const msg = ref('')

const form = ref({ name: '', value: '' })
const saving = ref(false)

async function load() {
  if (!authStore.isAdmin) return
  loading.value = true
  error.value = ''
  try {
    secrets.value = await get('/api/enterprise/vault/secrets')
  } catch (e) {
    error.value = e.message || 'Failed to load secrets'
  }
  loading.value = false
}

async function saveSecret() {
  saving.value = true
  msg.value = ''
  error.value = ''
  try {
    await post('/api/enterprise/vault/secrets', form.value)
    msg.value = `Secret "${form.value.name}" stored.`
    form.value = { name: '', value: '' }
    await load()
  } catch (e) {
    error.value = e.message || 'Save failed'
  }
  saving.value = false
}

async function removeSecret(name) {
  error.value = ''
  try {
    await del(`/api/enterprise/vault/secrets/${encodeURIComponent(name)}`)
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
      <h3 style="margin:0">Secrets Vault</h3>
      <button class="btn btn-sm" @click="load" :disabled="loading">
        <i class="fas fa-sync" :class="loading ? 'fa-spin' : ''"></i> Refresh
      </button>
    </div>

    <div class="alert" style="background:var(--surface-2);border:1px solid var(--border);font-size:.83rem;margin-bottom:1rem">
      <i class="fas fa-info-circle" style="margin-right:.4rem"></i>
      Secrets are encrypted at rest with AES-256-GCM. Values are <strong>never</strong> returned by the API — only names are listed.
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>

    <!-- Add secret form -->
    <div class="card" style="padding:1rem;margin-bottom:1rem">
      <h5 style="margin:0 0 .75rem 0">Add / Overwrite Secret</h5>
      <div style="display:grid;grid-template-columns:1fr 1fr auto;gap:.5rem;align-items:end">
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Name</label>
          <input v-model="form.name" class="form-control form-control-sm"
            placeholder="db-password" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Value</label>
          <input v-model="form.value" type="password" class="form-control form-control-sm"
            placeholder="••••••••" autocomplete="new-password" />
        </div>
        <button class="btn btn-sm btn-primary" @click="saveSecret"
          :disabled="saving || !form.name || !form.value">
          <i class="fas fa-lock"></i> Store
        </button>
      </div>
      <div style="font-size:.75rem;color:var(--text-muted);margin-top:.5rem">
        Name: alphanumeric, dashes, underscores only. Storing a secret with an existing name overwrites it.
      </div>
    </div>

    <!-- Secrets list -->
    <div v-if="loading" style="text-align:center;padding:2rem;color:var(--text-muted)">
      <i class="fas fa-spinner fa-spin"></i>
    </div>
    <div v-else-if="secrets.length" class="card" style="padding:0;overflow:hidden">
      <table class="table" style="margin:0;font-size:.85rem">
        <thead>
          <tr>
            <th>Name</th>
            <th>Value</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in secrets" :key="s.name">
            <td><strong><code>{{ s.name }}</code></strong></td>
            <td style="color:var(--text-muted);font-size:.8rem">
              <i class="fas fa-lock" style="margin-right:.3rem"></i>encrypted
            </td>
            <td>
              <button class="btn btn-xs btn-danger" @click="removeSecret(s.name)">
                <i class="fas fa-trash"></i>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else style="text-align:center;padding:2rem;color:var(--text-muted)">
      No secrets stored.
    </div>
  </div>
</template>
