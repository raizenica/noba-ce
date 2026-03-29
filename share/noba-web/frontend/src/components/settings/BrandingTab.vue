<script setup>
import { ref, watch, onMounted } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import { useAuthStore } from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'

const settingsStore = useSettingsStore()
const authStore = useAuthStore()
const notify = useNotificationsStore()

const saving = ref(false)

// Live-preview the accent color as user picks/types
watch(
  () => settingsStore.data.brandingAccentColor,
  () => settingsStore.applyBranding(),
  { immediate: false }
)

onMounted(async () => {
  if (!settingsStore.loaded) await settingsStore.fetchSettings()
})

async function save() {
  saving.value = true
  try {
    await settingsStore.saveSettings()
    settingsStore.applyBranding()
    notify.addToast('Branding saved', 'success')
  } catch (e) {
    notify.addToast('Save failed: ' + (e.message || 'Unknown error'), 'danger')
  } finally {
    saving.value = false
  }
}

function resetColor() {
  settingsStore.data.brandingAccentColor = ''
  settingsStore.applyBranding()
}
</script>

<template>
  <div v-if="authStore.isAdmin">

    <!-- Organization Identity -->
    <div class="s-section">
      <span class="s-label">Organization Identity</span>
      <p class="help-text" style="margin-bottom:.75rem">
        Replaces "NOBA" in the sidebar and login page with your organization name.
      </p>
      <div>
        <label class="field-label" for="b-org-name">Organization Name</label>
        <input
          id="b-org-name"
          class="field-input"
          type="text"
          v-model="settingsStore.data.brandingOrgName"
          placeholder="NOBA"
          style="max-width:320px"
        >
      </div>
    </div>

    <!-- Accent Color -->
    <div class="s-section">
      <span class="s-label">Accent Color</span>
      <p class="help-text" style="margin-bottom:.75rem">
        Overrides the global accent color (buttons, borders, highlights) across the entire UI.
        Leave blank to use the active theme's default.
      </p>
      <div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap">
        <div>
          <label class="field-label" for="b-accent-picker">Color Picker</label>
          <input
            id="b-accent-picker"
            type="color"
            :value="settingsStore.data.brandingAccentColor || '#00c8ff'"
            @input="settingsStore.data.brandingAccentColor = $event.target.value"
            style="width:48px;height:36px;padding:2px;border:1px solid var(--border);background:var(--surface);border-radius:4px;cursor:pointer"
          >
        </div>
        <div>
          <label class="field-label" for="b-accent-hex">Hex Value</label>
          <input
            id="b-accent-hex"
            class="field-input"
            type="text"
            v-model="settingsStore.data.brandingAccentColor"
            placeholder="#00c8ff"
            style="max-width:120px;font-family:monospace"
          >
        </div>
        <div style="display:flex;align-items:center;gap:.5rem;padding:.5rem .75rem;border-radius:4px;border:1px solid var(--border)">
          <span style="font-size:.75rem;opacity:.6">Preview</span>
          <span :style="`width:16px;height:16px;border-radius:50%;background:${settingsStore.data.brandingAccentColor || 'var(--accent)'};border:1px solid var(--border-hi)`"></span>
          <span :style="`color:${settingsStore.data.brandingAccentColor || 'var(--accent)'};font-size:.8rem;font-weight:600`">Accent text</span>
        </div>
        <button
          v-if="settingsStore.data.brandingAccentColor"
          class="btn btn-xs"
          style="color:var(--text-muted)"
          @click="resetColor"
        >
          <i class="fas fa-undo"></i> Reset to theme default
        </button>
      </div>
    </div>

    <!-- Custom Logo -->
    <div class="s-section">
      <span class="s-label">Custom Logo URL</span>
      <p class="help-text" style="margin-bottom:.75rem">
        Shown in the sidebar and login card instead of the terminal icon.
        Must be an accessible HTTPS URL. Recommended: 32×32 px.
      </p>
      <div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap">
        <div style="flex:1;min-width:240px">
          <label class="field-label" for="b-logo-url">Logo URL</label>
          <input
            id="b-logo-url"
            class="field-input"
            type="url"
            v-model="settingsStore.data.brandingLogoUrl"
            placeholder="https://example.com/logo.png"
          >
        </div>
        <div v-if="settingsStore.data.brandingLogoUrl" style="display:flex;align-items:center;gap:.5rem">
          <span style="font-size:.75rem;opacity:.6">Preview</span>
          <img
            :src="settingsStore.data.brandingLogoUrl"
            style="width:32px;height:32px;object-fit:contain;border-radius:4px;border:1px solid var(--border);background:var(--surface-2);padding:2px"
            alt="Logo preview"
          >
        </div>
      </div>
    </div>

    <!-- Login Background -->
    <div class="s-section">
      <span class="s-label">Login Background Image URL</span>
      <p class="help-text" style="margin-bottom:.75rem">
        Full-page background shown on the login screen.
        Must be an accessible HTTPS URL.
      </p>
      <div>
        <label class="field-label" for="b-bg-url">Background URL</label>
        <input
          id="b-bg-url"
          class="field-input"
          type="url"
          v-model="settingsStore.data.brandingLoginBgUrl"
          placeholder="https://example.com/background.jpg"
        >
      </div>
      <div
        v-if="settingsStore.data.brandingLoginBgUrl"
        :style="`margin-top:.75rem;height:80px;border-radius:6px;border:1px solid var(--border);background-image:url('${settingsStore.data.brandingLoginBgUrl}');background-size:cover;background-position:center`"
      ></div>
    </div>

    <!-- Save -->
    <div style="margin-top:1.25rem">
      <button class="btn btn-primary" :disabled="saving" @click="save">
        <i class="fas" :class="saving ? 'fa-spinner fa-spin' : 'fa-check'"></i>
        {{ saving ? 'Saving…' : 'Save & Apply' }}
      </button>
    </div>

  </div>

  <div v-else style="padding:2rem;text-align:center;color:var(--text-muted)">
    Admin access required to configure branding.
  </div>
</template>
