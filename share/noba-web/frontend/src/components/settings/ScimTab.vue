<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import { USER_ACTION_MSG_TIMEOUT_MS } from '../../constants'

const authStore = useAuthStore()
const { get, post } = useApi()

const status = ref(null)
const scimBaseUrl = ref('')
const newToken = ref('')
const actionMsg = ref('')
const rotating = ref(false)
const copied = ref('')

onMounted(async () => {
  if (!authStore.isAdmin) return
  scimBaseUrl.value = window.location.origin + '/api/scim/v2'
  await fetchStatus()
})

async function fetchStatus() {
  try {
    status.value = await get('/api/enterprise/scim/status')
  } catch (e) {
    actionMsg.value = 'Load failed: ' + e.message
  }
}

async function generateToken() {
  rotating.value = true
  newToken.value = ''
  try {
    const d = await post('/api/admin/scim-token', {})
    newToken.value = d.token
    await fetchStatus()
    actionMsg.value = 'Token generated. Copy it now — it will not be shown again.'
  } catch (e) {
    actionMsg.value = 'Failed: ' + e.message
  }
  rotating.value = false
  setTimeout(() => { actionMsg.value = '' }, USER_ACTION_MSG_TIMEOUT_MS)
}

function dismissToken() {
  newToken.value = ''
}

async function copyToClipboard(text, key) {
  await navigator.clipboard.writeText(text)
  copied.value = key
  setTimeout(() => { copied.value = '' }, 1500)
}

function formatDate(ts) {
  if (!ts) return 'N/A'
  return new Date(ts * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}
</script>

<template>
  <div>
    <div v-if="!authStore.isAdmin" style="text-align:center;padding:3rem;color:var(--text-muted)">
      <i class="fas fa-lock" style="font-size:2rem;margin-bottom:.75rem;display:block;opacity:.4"></i>
      Admin role required.
    </div>

    <template v-else>
      <div class="s-section">
        <span class="s-label">SCIM Provisioning</span>

        <div v-if="actionMsg" style="font-size:.82rem;color:var(--text-muted);margin-bottom:.75rem">{{ actionMsg }}</div>

        <div v-if="newToken" style="margin-bottom:1rem;padding:.75rem 1rem;background:var(--surface-2);border:1px solid #ca8a04;border-radius:4px">
          <div style="font-size:.8rem;font-weight:600;color:#ca8a04;margin-bottom:.4rem">
            <i class="fas fa-exclamation-triangle"></i> Copy this token — it will not be shown again
          </div>
          <div style="display:flex;align-items:center;gap:.5rem">
            <code style="font-size:.8rem;word-break:break-all;flex:1">{{ newToken }}</code>
            <button class="btn btn-xs" @click="copyToClipboard(newToken, 'token')">
              <i class="fas" :class="copied === 'token' ? 'fa-check' : 'fa-copy'"></i>
            </button>
            <button class="btn btn-xs btn-danger" @click="dismissToken" aria-label="Dismiss">
              <i class="fas fa-times"></i>
            </button>
          </div>
        </div>

        <div v-if="status" style="margin-bottom:1rem">
          <div style="display:flex;align-items:center;gap:.75rem;margin-bottom:.5rem">
            <span style="font-size:.8rem;color:var(--text-muted)">Status:</span>
            <span class="badge" :class="status.active ? 'ba' : 'bn'" style="font-size:.75rem">
              {{ status.active ? 'Active' : 'No token' }}
            </span>
          </div>
          <div v-if="status.active" style="font-size:.8rem;color:var(--text-muted);display:flex;flex-direction:column;gap:.2rem">
            <span>Expires: {{ formatDate(status.expires_at) }}</span>
            <span>Last used: {{ status.last_used_at ? formatDate(status.last_used_at) : 'Never' }}</span>
            <span>Last provisioning activity: {{ status.last_activity ? formatDate(status.last_activity) : 'N/A' }}</span>
          </div>
        </div>

        <div style="margin-bottom:1rem">
          <label class="field-label">SCIM Base URL (paste into Okta / Azure AD)</label>
          <div style="display:flex;align-items:center;gap:.5rem">
            <input class="field-input" type="text" :value="scimBaseUrl" readonly style="flex:1">
            <button class="btn btn-sm" @click="copyToClipboard(scimBaseUrl, 'base')">
              <i class="fas" :class="copied === 'base' ? 'fa-check' : 'fa-copy'"></i>
              {{ copied === 'base' ? 'Copied' : 'Copy' }}
            </button>
          </div>
        </div>

        <div style="margin-bottom:1rem;font-size:.8rem;color:var(--text-muted)">
          Supported resources: <strong>Users</strong>
        </div>

        <button class="btn btn-sm btn-primary" @click="generateToken" :disabled="rotating">
          <i class="fas fa-key"></i>
          {{ rotating ? 'Generating…' : (status?.active ? 'Rotate Token' : 'Generate Token') }}
        </button>
      </div>
    </template>
  </div>
</template>
