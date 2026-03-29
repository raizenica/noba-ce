<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get, put, del } = useApi()

const acls = ref([])
const loading = ref(false)
const error = ref('')
const msg = ref('')

// New ACL form
const form = ref({ username: '', resource_type: 'automations', can_read: true, can_write: false })
const saving = ref(false)

const RESOURCE_TYPES = [
  'api_keys', 'audit', 'automations', 'integrations', 'users', 'webhooks',
]

async function load() {
  if (!authStore.isAdmin) return
  loading.value = true
  error.value = ''
  try {
    acls.value = await get('/api/enterprise/rbac/acls')
  } catch (e) {
    error.value = e.message || 'Failed to load ACLs'
  }
  loading.value = false
}

async function saveAcl() {
  saving.value = true
  msg.value = ''
  error.value = ''
  try {
    await put('/api/enterprise/rbac/acls', form.value)
    msg.value = 'ACL saved.'
    form.value = { username: '', resource_type: 'automations', can_read: true, can_write: false }
    await load()
  } catch (e) {
    error.value = e.message || 'Save failed'
  }
  saving.value = false
}

async function removeAcl(username, resource_type) {
  error.value = ''
  try {
    await del(`/api/enterprise/rbac/acls?username=${encodeURIComponent(username)}&resource_type=${encodeURIComponent(resource_type)}`)
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
      <h3 style="margin:0">Resource Access Control</h3>
      <button class="btn btn-sm" @click="load" :disabled="loading">
        <i class="fas fa-sync" :class="loading ? 'fa-spin' : ''"></i> Refresh
      </button>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>

    <!-- Add ACL form -->
    <div class="card" style="padding:1rem;margin-bottom:1rem">
      <h5 style="margin:0 0 .75rem 0">Add / Update Restriction</h5>
      <div style="display:grid;grid-template-columns:1fr 1fr auto auto auto;gap:.5rem;align-items:end">
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Username</label>
          <input v-model="form.username" class="form-control form-control-sm" placeholder="alice" />
        </div>
        <div>
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Resource Type</label>
          <select v-model="form.resource_type" class="form-control form-control-sm">
            <option v-for="rt in RESOURCE_TYPES" :key="rt" :value="rt">{{ rt }}</option>
          </select>
        </div>
        <div style="text-align:center">
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Can Read</label>
          <input type="checkbox" v-model="form.can_read" style="width:1.1rem;height:1.1rem" />
        </div>
        <div style="text-align:center">
          <label style="font-size:.8rem;display:block;margin-bottom:.2rem">Can Write</label>
          <input type="checkbox" v-model="form.can_write" style="width:1.1rem;height:1.1rem" />
        </div>
        <button class="btn btn-sm btn-primary" @click="saveAcl"
          :disabled="saving || !form.username">
          <i class="fas fa-save"></i> Save
        </button>
      </div>
      <div style="font-size:.75rem;color:var(--text-muted);margin-top:.5rem">
        No row = full access. A row with can_read=off denies all access. Admins always bypass ACLs.
      </div>
    </div>

    <!-- ACL table -->
    <div v-if="loading" style="text-align:center;padding:2rem;color:var(--text-muted)">
      <i class="fas fa-spinner fa-spin"></i>
    </div>
    <div v-else-if="acls.length" class="card" style="padding:0;overflow:hidden">
      <table class="table" style="margin:0;font-size:.85rem">
        <thead>
          <tr>
            <th>Username</th>
            <th>Resource Type</th>
            <th style="text-align:center">Read</th>
            <th style="text-align:center">Write</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in acls" :key="`${row.username}:${row.resource_type}`">
            <td><strong>{{ row.username }}</strong></td>
            <td><code>{{ row.resource_type }}</code></td>
            <td style="text-align:center">
              <i :class="row.can_read ? 'fas fa-check text-success' : 'fas fa-times text-danger'"></i>
            </td>
            <td style="text-align:center">
              <i :class="row.can_write ? 'fas fa-check text-success' : 'fas fa-times text-danger'"></i>
            </td>
            <td>
              <button class="btn btn-xs btn-danger"
                @click="removeAcl(row.username, row.resource_type)">
                <i class="fas fa-trash"></i>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else style="text-align:center;padding:2rem;color:var(--text-muted)">
      No restrictions configured. All users have full access within their role.
    </div>
  </div>
</template>
