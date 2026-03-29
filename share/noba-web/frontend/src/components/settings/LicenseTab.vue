<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useLicenseStore } from '../../stores/license'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'

const auth    = useAuthStore()
const license = useLicenseStore()
const notify  = useNotificationsStore()
const { post } = useApi()

const uploading   = ref(false)
const dragOver    = ref(false)
const fileInput   = ref(null)

onMounted(() => license.fetchStatus())

// ── State display helpers ────────────────────────────────────────────────────
const stateLabel = computed(() => {
  const map = {
    trial:      'Trial',
    grace:      'Grace Period',
    licensed:   'Licensed',
    expired:    'Support Expired',
    unlicensed: 'Unlicensed',
    unknown:    'Loading…',
  }
  return map[license.state] || license.state
})

const stateColor = computed(() => {
  if (license.isLicensed)   return 'var(--success, #22c55e)'
  if (license.isTrial)      return 'var(--accent)'
  if (license.isGrace)      return 'var(--warning, #f0a500)'
  return 'var(--danger, #e53935)'
})

const expiresLabel = computed(() => {
  if (!license.expiresAt) return '—'
  return new Date(license.expiresAt * 1000).toLocaleDateString(undefined, {
    year: 'numeric', month: 'long', day: 'numeric',
  })
})

// ── Upload ───────────────────────────────────────────────────────────────────
async function handleFile(file) {
  if (!file) return
  uploading.value = true
  try {
    const text = await file.text()
    await uploadLicense(text)
  } catch (e) {
    notify.addToast('Upload failed: ' + (e.message || 'Unknown error'), 'danger')
  } finally {
    uploading.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function uploadLicense(text) {
  const res = await fetch('/api/license/upload', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('noba-token')}` },
    body: text,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  await license.fetchStatus()
  notify.addToast('License activated successfully', 'success')
}

function onFileInput(e) {
  handleFile(e.target.files?.[0])
}

function onDrop(e) {
  dragOver.value = false
  handleFile(e.dataTransfer?.files?.[0])
}

async function removeLicense() {
  if (!confirm('Remove the installed license? The instance will revert to trial or unlicensed state.')) return
  const res = await fetch('/api/license', {
    method: 'DELETE',
    headers: { 'Authorization': `Bearer ${localStorage.getItem('noba-token')}` },
  })
  if (res.ok) {
    await license.fetchStatus()
    notify.addToast('License removed', 'success')
  }
}
</script>

<template>
  <div v-if="auth.isAdmin">

    <!-- Status Card -->
    <div class="s-section">
      <span class="s-label">License Status</span>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:.75rem;margin-top:.5rem">

        <div style="padding:.75rem;border-radius:6px;border:1px solid var(--border);background:var(--surface-2)">
          <div style="font-size:.6rem;letter-spacing:.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:.3rem">Status</div>
          <div style="font-weight:700;font-size:.95rem" :style="`color:${stateColor}`">{{ stateLabel }}</div>
        </div>

        <div style="padding:.75rem;border-radius:6px;border:1px solid var(--border);background:var(--surface-2)">
          <div style="font-size:.6rem;letter-spacing:.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:.3rem">Plan</div>
          <div style="font-weight:600;text-transform:capitalize">{{ license.plan }}</div>
        </div>

        <div v-if="license.licensee" style="padding:.75rem;border-radius:6px;border:1px solid var(--border);background:var(--surface-2)">
          <div style="font-size:.6rem;letter-spacing:.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:.3rem">Licensee</div>
          <div style="font-weight:600">{{ license.licensee }}</div>
        </div>

        <div style="padding:.75rem;border-radius:6px;border:1px solid var(--border);background:var(--surface-2)">
          <div style="font-size:.6rem;letter-spacing:.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:.3rem">
            {{ license.isTrial || license.isGrace ? 'Trial Ends' : 'Support Until' }}
          </div>
          <div style="font-weight:600">{{ expiresLabel }}</div>
          <div v-if="license.daysLeft !== null" style="font-size:.7rem;color:var(--text-muted);margin-top:.1rem">
            {{ license.daysLeft }} day{{ license.daysLeft === 1 ? '' : 's' }} remaining
          </div>
        </div>

        <div style="padding:.75rem;border-radius:6px;border:1px solid var(--border);background:var(--surface-2)">
          <div style="font-size:.6rem;letter-spacing:.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:.3rem">Seats</div>
          <div style="font-weight:600">
            {{ license.userCount }}<span style="opacity:.5">/{{ license.seats || '∞' }}</span>
          </div>
        </div>

      </div>

      <!-- Grace / unlicensed warning -->
      <div
        v-if="license.isGrace || license.isUnlicensed"
        style="margin-top:.75rem;padding:.75rem 1rem;border-radius:6px;border:1px solid var(--warning, #f0a500);background:color-mix(in srgb, var(--warning, #f0a500) 10%, transparent);font-size:.8rem"
      >
        <i class="fas fa-exclamation-triangle" style="margin-right:.4rem"></i>
        <template v-if="license.isGrace">
          Your trial has ended. Enterprise features will be disabled in {{ license.daysLeft }} day{{ license.daysLeft === 1 ? '' : 's' }}.
          Upload a license below to continue.
        </template>
        <template v-else>
          No valid license found. Enterprise features (SAML, SCIM, WebAuthn, branding) are disabled.
          Upload a license file to activate.
        </template>
      </div>

      <!-- Support expired notice -->
      <div
        v-if="license.isExpired"
        style="margin-top:.75rem;padding:.75rem 1rem;border-radius:6px;border:1px solid var(--border);background:var(--surface-2);font-size:.8rem;color:var(--text-muted)"
      >
        <i class="fas fa-info-circle" style="margin-right:.4rem"></i>
        Your support &amp; update entitlement has ended. All licensed features continue to work — renew to get security updates and new features.
      </div>
    </div>

    <!-- Upload -->
    <div class="s-section">
      <span class="s-label">{{ license.isLicensed || license.isExpired ? 'Replace License' : 'Activate License' }}</span>
      <p class="help-text" style="margin-bottom:.75rem">
        Upload the <code>.noba-license</code> file provided after purchase.
        The file is verified offline — no internet connection required.
      </p>

      <!-- Drop zone -->
      <div
        style="border:2px dashed var(--border);border-radius:8px;padding:2rem;text-align:center;cursor:pointer;transition:border-color .15s,background .15s"
        :style="dragOver ? 'border-color:var(--accent);background:color-mix(in srgb, var(--accent) 6%, transparent)' : ''"
        @dragover.prevent="dragOver = true"
        @dragleave="dragOver = false"
        @drop.prevent="onDrop"
        @click="fileInput?.click()"
      >
        <i class="fas fa-file-upload" style="font-size:1.5rem;opacity:.4;margin-bottom:.5rem;display:block"></i>
        <div style="font-size:.82rem;color:var(--text-muted)">
          Drop <code>.noba-license</code> here or <span style="color:var(--accent)">click to browse</span>
        </div>
        <input
          ref="fileInput"
          type="file"
          accept=".noba-license,.json"
          style="display:none"
          @change="onFileInput"
        >
      </div>

      <div v-if="uploading" style="margin-top:.75rem;font-size:.82rem;color:var(--text-muted)">
        <i class="fas fa-spinner fa-spin"></i> Verifying and installing…
      </div>
    </div>

    <!-- Installed features -->
    <div v-if="license.features.length" class="s-section">
      <span class="s-label">Included Features</span>
      <div style="display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.5rem">
        <span
          v-for="f in license.features"
          :key="f"
          style="font-size:.68rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;padding:3px 8px;border-radius:4px;border:1px solid color-mix(in srgb, var(--accent) 40%, transparent);background:color-mix(in srgb, var(--accent) 10%, transparent);color:var(--accent)"
        >{{ f.replace('_', ' ') }}</span>
      </div>
    </div>

    <!-- Remove license -->
    <div v-if="license.isLicensed || license.isExpired" style="margin-top:.5rem">
      <button class="btn btn-xs" style="color:var(--danger, #e53935)" @click="removeLicense">
        <i class="fas fa-trash"></i> Remove license
      </button>
    </div>

  </div>

  <div v-else style="padding:2rem;text-align:center;color:var(--text-muted)">
    Admin access required to manage licensing.
  </div>
</template>
