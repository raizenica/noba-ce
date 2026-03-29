<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import { useModalsStore } from '../../stores/modals'
import { USER_ACTION_MSG_TIMEOUT_MS } from '../../constants'

const authStore = useAuthStore()
const { get, del } = useApi()
const modals = useModalsStore()

const credentials = ref([])
const loading = ref(false)
const actionMsg = ref('')

onMounted(() => {
  if (authStore.isAdmin) fetchCredentials()
})

async function fetchCredentials() {
  loading.value = true
  try {
    credentials.value = await get('/api/enterprise/webauthn/credentials')
  } catch (e) {
    actionMsg.value = 'Load failed: ' + e.message
  }
  loading.value = false
}

async function revokeCredential(cred) {
  if (!await modals.confirm(`Revoke passkey "${cred.name || cred.id}" for ${cred.username}?`)) return
  try {
    await del(`/api/enterprise/webauthn/credentials/${cred.id}`)
    actionMsg.value = `Passkey revoked for ${cred.username}.`
    await fetchCredentials()
  } catch (e) {
    actionMsg.value = 'Revoke failed: ' + e.message
  }
  setTimeout(() => { actionMsg.value = '' }, USER_ACTION_MSG_TIMEOUT_MS)
}

function formatDate(ts) {
  if (!ts) return '—'
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
        <span class="s-label">WebAuthn Passkey Management</span>

        <div v-if="actionMsg" style="font-size:.82rem;color:var(--text-muted);margin-bottom:.75rem">{{ actionMsg }}</div>

        <div v-if="loading" style="padding:2rem;text-align:center;color:var(--text-muted)">
          <i class="fas fa-spinner fa-spin"></i> Loading passkeys…
        </div>

        <div v-else-if="credentials.length === 0"
          style="text-align:center;padding:2.5rem;background:var(--surface);border:1px dashed var(--border);border-radius:6px;color:var(--text-muted)">
          <i class="fas fa-fingerprint" style="font-size:2rem;display:block;margin-bottom:.75rem;opacity:.3"></i>
          No passkeys registered. Users can register passkeys from the login screen.
        </div>

        <div v-else style="overflow-x:auto">
          <table style="width:100%;border-collapse:collapse;font-size:.82rem">
            <thead>
              <tr style="border-bottom:1px solid var(--border);text-align:left">
                <th style="padding:.5rem .75rem;color:var(--text-muted);font-weight:600">Username</th>
                <th style="padding:.5rem .75rem;color:var(--text-muted);font-weight:600">Passkey Name</th>
                <th style="padding:.5rem .75rem;color:var(--text-muted);font-weight:600">Registered</th>
                <th style="padding:.5rem .75rem;color:var(--text-muted);font-weight:600">Uses</th>
                <th style="padding:.5rem .75rem"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="cred in credentials" :key="cred.id" style="border-bottom:1px solid var(--border)">
                <td style="padding:.5rem .75rem">
                  <i class="fas fa-user" style="color:var(--text-muted);margin-right:.4rem;opacity:.5"></i>
                  {{ cred.username }}
                </td>
                <td style="padding:.5rem .75rem">{{ cred.name || '(unnamed)' }}</td>
                <td style="padding:.5rem .75rem">{{ formatDate(cred.created_at) }}</td>
                <td style="padding:.5rem .75rem">{{ cred.sign_count }}</td>
                <td style="padding:.5rem .75rem;text-align:right">
                  <button class="btn btn-xs btn-danger" @click="revokeCredential(cred)"
                    :aria-label="'Revoke passkey for ' + cred.username">
                    <i class="fas fa-ban"></i> Revoke
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
