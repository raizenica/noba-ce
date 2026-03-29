<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import { USER_ACTION_MSG_TIMEOUT_MS } from '../../constants'

const authStore = useAuthStore()
const { get, put, post } = useApi()

const form = ref({
  samlEnabled: false,
  samlIdpSsoUrl: '',
  samlIdpCert: '',
  samlEntityId: '',
  samlAcsUrl: '',
  samlDefaultRole: 'viewer',
  samlGroupMapping: '{}',
})
const actionMsg = ref('')
const testResult = ref(null)
const testing = ref(false)
const saving = ref(false)
const spMetadataUrl = ref('')
const copied = ref('')

onMounted(async () => {
  if (!authStore.isAdmin) return
  spMetadataUrl.value = window.location.origin + '/api/saml/metadata'
  try {
    const d = await get('/api/enterprise/saml')
    Object.assign(form.value, d)
  } catch (e) {
    actionMsg.value = 'Load failed: ' + e.message
  }
})

async function save() {
  const pw = prompt('Confirm your password to save SSO configuration:')
  if (!pw) return
  saving.value = true
  try {
    const token = authStore.token
    const res = await fetch('/api/enterprise/saml', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
        'X-Confirm-Password': pw,
      },
      body: JSON.stringify(form.value),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    actionMsg.value = 'SAML configuration saved.'
  } catch (e) {
    actionMsg.value = 'Save failed: ' + e.message
  }
  saving.value = false
  setTimeout(() => { actionMsg.value = '' }, USER_ACTION_MSG_TIMEOUT_MS)
}

async function testConnection() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await post('/api/enterprise/saml/test', {})
  } catch (e) {
    testResult.value = { ok: false, error: e.message }
  }
  testing.value = false
}

async function copyToClipboard(text, key) {
  await navigator.clipboard.writeText(text)
  copied.value = key
  setTimeout(() => { copied.value = '' }, 1500)
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
        <span class="s-label">SAML SSO Configuration</span>

        <div v-if="actionMsg" style="font-size:.82rem;color:var(--text-muted);margin-bottom:.75rem">{{ actionMsg }}</div>

        <div style="margin-bottom:1rem;display:flex;align-items:center;gap:.75rem">
          <input id="saml-enabled" type="checkbox" v-model="form.samlEnabled">
          <label for="saml-enabled" class="field-label" style="margin:0">Enable SAML SSO</label>
        </div>

        <div style="margin-bottom:.75rem">
          <label class="field-label" for="saml-idp-url">IdP SSO URL</label>
          <input id="saml-idp-url" class="field-input" type="text" v-model="form.samlIdpSsoUrl"
            placeholder="https://idp.example.com/sso/saml">
        </div>

        <div style="margin-bottom:.75rem">
          <label class="field-label" for="saml-idp-cert">IdP Certificate (PEM)</label>
          <textarea id="saml-idp-cert" class="field-input" rows="5"
            style="font-family:monospace;font-size:.8rem;resize:vertical"
            v-model="form.samlIdpCert"
            placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"></textarea>
        </div>

        <div class="field-2" style="margin-bottom:.75rem">
          <div>
            <label class="field-label" for="saml-entity-id">SP Entity ID</label>
            <input id="saml-entity-id" class="field-input" type="text" v-model="form.samlEntityId"
              placeholder="https://noba.example.com">
          </div>
          <div>
            <label class="field-label" for="saml-acs-url">Assertion Consumer Service URL</label>
            <input id="saml-acs-url" class="field-input" type="text" v-model="form.samlAcsUrl"
              placeholder="https://noba.example.com/api/saml/acs">
          </div>
        </div>

        <div class="field-2" style="margin-bottom:.75rem">
          <div>
            <label class="field-label" for="saml-default-role">Default role for new SAML users</label>
            <select id="saml-default-role" class="field-input field-select" v-model="form.samlDefaultRole">
              <option value="viewer">viewer</option>
              <option value="operator">operator</option>
              <option value="admin">admin</option>
            </select>
          </div>
          <div>
            <label class="field-label" for="saml-group-map">Role mapping (JSON)</label>
            <input id="saml-group-map" class="field-input" type="text" v-model="form.samlGroupMapping"
              placeholder='{"Admins": "admin"}'>
          </div>
        </div>

        <div style="margin-bottom:1rem;border:1px solid var(--border);padding:.75rem;border-radius:4px;background:var(--surface-2)">
          <div style="font-size:.75rem;color:var(--text-muted);margin-bottom:.5rem;font-weight:600">SP Metadata (paste into IdP)</div>
          <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.4rem">
            <span style="font-size:.78rem;font-family:monospace">{{ spMetadataUrl }}</span>
            <button class="btn btn-xs" @click="copyToClipboard(spMetadataUrl, 'metadata')">
              <i class="fas" :class="copied === 'metadata' ? 'fa-check' : 'fa-copy'"></i>
            </button>
          </div>
          <div style="display:flex;align-items:center;gap:.5rem">
            <span style="font-size:.78rem;color:var(--text-muted)">ACS: </span>
            <span style="font-size:.78rem;font-family:monospace">{{ form.samlAcsUrl || '(configure above)' }}</span>
            <button v-if="form.samlAcsUrl" class="btn btn-xs" @click="copyToClipboard(form.samlAcsUrl, 'acs')">
              <i class="fas" :class="copied === 'acs' ? 'fa-check' : 'fa-copy'"></i>
            </button>
          </div>
        </div>

        <div v-if="testResult" style="margin-bottom:.75rem;font-size:.82rem;padding:.5rem .75rem;border-radius:4px"
          :style="testResult.ok ? 'background:var(--surface-2);border:1px solid var(--success,#4ade80)' : 'background:var(--surface-2);border:1px solid var(--danger,#f87171)'">
          <span v-if="testResult.ok">
            <i class="fas fa-check-circle" style="color:var(--success,#4ade80)"></i>
            IdP reachable — HTTP {{ testResult.status }}, {{ testResult.latency_ms }}ms
          </span>
          <span v-else>
            <i class="fas fa-times-circle" style="color:var(--danger,#f87171)"></i>
            Connection failed
            <span v-if="testResult.status"> — HTTP {{ testResult.status }}</span>
            <span v-if="testResult.error"> — {{ testResult.error }}</span>
          </span>
        </div>

        <div style="display:flex;gap:.5rem;flex-wrap:wrap">
          <button class="btn btn-sm btn-primary" @click="save" :disabled="saving">
            <i class="fas fa-save"></i> {{ saving ? 'Saving…' : 'Save' }}
          </button>
          <button class="btn btn-sm" @click="testConnection" :disabled="testing || !form.samlIdpSsoUrl">
            <i class="fas fa-plug"></i> {{ testing ? 'Testing…' : 'Test Connection' }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
