<template>
  <div class="modal-overlay login-fullscreen"
       :style="settings.branding.loginBgUrl
         ? `background-image:url('${settings.branding.loginBgUrl}');background-size:cover;background-position:center`
         : ''">
    <form
      style="background:var(--surface);padding:2rem;border-radius:8px;border:1px solid var(--border);border-top:3px solid var(--accent);width:95%;max-width:400px;margin:auto"
      @submit.prevent="handleLogin"
    >
      <!-- Logo -->
      <div style="display:flex;align-items:center;gap:.75rem;margin-bottom:1.5rem">
        <div style="width:42px;height:42px;background:var(--accent-dim);border:1px solid var(--accent);display:flex;align-items:center;justify-content:center;color:var(--accent);border-radius:6px;flex-shrink:0">
          <img v-if="settings.branding.logoUrl"
               :src="settings.branding.logoUrl"
               style="width:26px;height:26px;object-fit:contain"
               alt="Logo">
          <i v-else class="fas fa-terminal"></i>
        </div>
        <div>
          <div style="font-weight:700;font-size:1.2rem;letter-spacing:.1em;display:flex;align-items:center;gap:.5rem">
            {{ settings.branding.orgName || 'NOBA' }} <span style="color:var(--accent)">//</span> CMD
            <span class="login-edition-badge">Enterprise</span>
          </div>
          <div style="font-size:.65rem;color:var(--text-muted);letter-spacing:.2em;text-transform:uppercase">Command Center</div>
        </div>
      </div>

      <!-- Username -->
      <div style="margin-bottom:1rem">
        <label class="field-label">Username</label>
        <input
          v-model="username"
          class="field-input"
          type="text"
          autofocus
          autocomplete="username"
        >
      </div>

      <!-- Password -->
      <div style="margin-bottom:1rem">
        <label class="field-label">Password</label>
        <div style="position:relative">
          <input
            v-model="password"
            class="field-input"
            :type="showPassword ? 'text' : 'password'"
            autocomplete="current-password"
            style="padding-right:2.5rem"
          >
          <button type="button" class="pw-toggle" @click="showPassword = !showPassword"
            :title="showPassword ? 'Hide password' : 'Show password'">
            <i class="fas" :class="showPassword ? 'fa-eye-slash' : 'fa-eye'"></i>
          </button>
        </div>
      </div>

      <!-- Error -->
      <div v-if="error" style="color:var(--danger);font-size:.8rem;margin-bottom:1rem">{{ error }}</div>

      <!-- Submit -->
      <button class="btn btn-primary" type="submit" :disabled="loading" style="width:100%">
        <i class="fas" :class="loading ? 'fa-spinner fa-spin' : 'fa-sign-in-alt'"></i>
        {{ loading ? 'Authenticating...' : 'Login' }}
      </button>

      <!-- SSO section -->
      <div v-if="samlEnabled || providers.length" class="sso-section">
        <div class="sso-divider"><span>Single Sign-On</span></div>

        <!-- SAML — first-class enterprise SSO -->
        <button v-if="samlEnabled" type="button" class="sso-saml-btn" @click="openSsoPopup">
          <i class="fas fa-shield-alt"></i>
          Sign in with SSO
          <span class="sso-protocol-badge">SAML 2.0</span>
        </button>

        <!-- OIDC / OAuth providers -->
        <div v-if="providers.length" style="display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:8px">
          <button v-for="p in providers" :key="p.id" type="button" class="btn btn-sm social-btn" @click="openSsoPopup(p.url)">
            <i :class="['fab', providerIcon(p.id)]" v-if="isFab(p.id)"></i>
            <i :class="['fas', providerIcon(p.id)]" v-else></i>
            {{ p.name }}
          </button>
        </div>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useDashboardStore } from '../stores/dashboard'
import { useSettingsStore } from '../stores/settings'
import { useApi } from '../composables/useApi'

const router = useRouter()
const auth = useAuthStore()
const dashboard = useDashboardStore()
const settings = useSettingsStore()
const { get } = useApi()

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)
const showPassword = ref(false)
const providers = ref([])
const samlEnabled = ref(false)

onMounted(async () => {
  // Apply org branding before credentials are entered (public endpoint)
  try {
    const b = await get('/api/branding')
    Object.assign(settings.data, {
      brandingOrgName:     b.orgName     || '',
      brandingAccentColor: b.accentColor || '',
      brandingLogoUrl:     b.logoUrl     || '',
      brandingLoginBgUrl:  b.loginBgUrl  || '',
    })
    settings.applyBranding()
  } catch { /* branding not yet configured — show defaults */ }
  try {
    const data = await get('/api/auth/providers')
    if (data && Array.isArray(data)) providers.value = data
  } catch { /* no providers configured — that's fine */ }
  try {
    const r = await fetch('/api/saml/metadata')
    samlEnabled.value = r.ok
  } catch { /* SAML not configured */ }
})

function providerIcon(id) {
  const icons = { google: 'fa-google', facebook: 'fa-facebook', github: 'fa-github', microsoft: 'fa-microsoft' }
  return icons[id] || 'fa-sign-in-alt'
}
function isFab(id) {
  return ['google', 'facebook', 'github', 'microsoft'].includes(id)
}

// ── SSO popup ────────────────────────────────────────────────────────────────
let _ssoPoller = null

function openSsoPopup(url = '/api/saml/login') {
  const w = 500, h = 600
  const left = window.screenX + (window.outerWidth - w) / 2
  const top = window.screenY + (window.outerHeight - h) / 2
  const popup = window.open(
    url,
    'noba-sso',
    `width=${w},height=${h},left=${left},top=${top},popup=yes`,
  )
  // Poll localStorage for the token (storage event isn't always reliable)
  if (_ssoPoller) clearInterval(_ssoPoller)
  _ssoPoller = setInterval(() => {
    const token = localStorage.getItem('noba-token')
    if (token) {
      clearInterval(_ssoPoller)
      _ssoPoller = null
      auth.setToken(token)
      window.location.replace('/#/dashboard')
    }
    // Stop polling if popup was closed without completing
    if (popup && popup.closed && !localStorage.getItem('noba-token')) {
      clearInterval(_ssoPoller)
      _ssoPoller = null
    }
  }, 500)
}

onUnmounted(() => {
  if (_ssoPoller) { clearInterval(_ssoPoller); _ssoPoller = null }
})

const availableProviders = [
  { id: 'google', name: 'Google' },
  { id: 'facebook', name: 'Facebook' },
  { id: 'github', name: 'GitHub' },
  { id: 'microsoft', name: 'Microsoft' },
]

async function handleLogin() {
  if (loading.value) return
  error.value = ''
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    // Bootstrap app data after successful login
    await Promise.all([
      settings.fetchSettings(),
      settings.fetchPreferences(),
    ])
    dashboard.connectSse()
    router.push('/dashboard')
  } catch (err) {
    error.value = err.message || 'Login failed'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.social-btn {
  display: inline-flex;
  align-items: center;
  gap: .4rem;
  min-width: 100px;
  justify-content: center;
}
.pw-toggle {
  position: absolute;
  right: .5rem;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: .25rem;
  font-size: .85rem;
}
.pw-toggle:hover { color: var(--accent); }

/* Enterprise edition badge (login logo) */
.login-edition-badge {
  font-size: .48rem;
  font-weight: 700;
  letter-spacing: .18em;
  text-transform: uppercase;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
  padding: 2px 6px;
  border-radius: 3px;
  line-height: 1.6;
}

/* SSO section */
.sso-section { margin-top: 1.25rem; }
.sso-divider {
  display: flex;
  align-items: center;
  gap: .5rem;
  margin-bottom: .75rem;
  font-size: .62rem;
  letter-spacing: .15em;
  text-transform: uppercase;
  color: var(--text-muted);
}
.sso-divider::before,
.sso-divider::after {
  content: '';
  flex: 1;
  border-top: 1px solid var(--border);
}
.sso-saml-btn {
  width: 100%;
  display: flex;
  align-items: center;
  gap: .6rem;
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
  color: var(--accent);
  padding: .6rem 1rem;
  border-radius: 6px;
  font-size: .8rem;
  font-weight: 600;
  letter-spacing: .04em;
  transition: background .15s, border-color .15s;
  text-decoration: none;
  cursor: pointer;
}
.sso-saml-btn:hover {
  background: color-mix(in srgb, var(--accent) 15%, transparent);
  border-color: var(--accent);
}
.sso-protocol-badge {
  font-size: .52rem;
  letter-spacing: .14em;
  opacity: .55;
  border: 1px solid currentColor;
  padding: 1px 5px;
  border-radius: 3px;
  margin-left: auto;
}
</style>
