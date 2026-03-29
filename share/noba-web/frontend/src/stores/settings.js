import { defineStore } from 'pinia'
import { ref, reactive, computed } from 'vue'
import { useApi } from '../composables/useApi'

export const useSettingsStore = defineStore('settings', () => {
  const loaded = ref(false)
  const data = reactive({})
  const vis = reactive({})
  const preferences = reactive({})

  async function fetchSettings() {
    const { get } = useApi()
    try {
      const settings = await get('/api/settings')
      Object.assign(data, settings)
      loaded.value = true
    } catch { /* ignore */ }
  }

  async function saveSettings(updates) {
    const { post } = useApi()
    Object.assign(data, updates)
    await post('/api/settings', data)
  }

  async function fetchPreferences() {
    const { get } = useApi()
    try {
      const prefs = await get('/api/user/preferences')
      Object.assign(preferences, prefs)
      if (prefs.vis) Object.assign(vis, prefs.vis)
    } catch { /* ignore */ }
  }

  async function savePreferences() {
    const { put } = useApi()
    await put('/api/user/preferences', { ...preferences, vis: { ...vis } })
  }

  const branding = computed(() => ({
    orgName:     data.brandingOrgName     || '',
    accentColor: data.brandingAccentColor || '',
    logoUrl:     data.brandingLogoUrl     || '',
    loginBgUrl:  data.brandingLoginBgUrl  || '',
  }))

  function applyBranding() {
    const color = data.brandingAccentColor
    if (color && /^#[0-9a-fA-F]{3,8}$/.test(color)) {
      document.documentElement.style.setProperty('--accent', color)
    } else {
      document.documentElement.style.removeProperty('--accent')
    }
  }

  return { loaded, data, vis, preferences, fetchSettings, saveSettings, fetchPreferences, savePreferences, branding, applyBranding }
})
