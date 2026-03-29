import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useApi } from '../composables/useApi'

export const useLicenseStore = defineStore('license', () => {
  const { get } = useApi()

  const status = ref(null)
  const loading = ref(false)

  const state       = computed(() => status.value?.state        || 'unknown')
  const active      = computed(() => status.value?.active       ?? true)   // default true so trial works
  const plan        = computed(() => status.value?.plan         || 'enterprise')
  const licensee    = computed(() => status.value?.licensee     || '')
  const seats       = computed(() => status.value?.seats        || 0)
  const userCount   = computed(() => status.value?.user_count   || 0)
  const features    = computed(() => status.value?.features     || [])
  const daysLeft    = computed(() => status.value?.days_remaining ?? null)
  const trial       = computed(() => status.value?.trial        ?? false)
  const expiresAt   = computed(() => status.value?.expires_at   || 0)

  const isTrial     = computed(() => state.value === 'trial')
  const isGrace     = computed(() => state.value === 'grace')
  const isLicensed  = computed(() => state.value === 'licensed')
  const isExpired   = computed(() => state.value === 'expired')
  const isUnlicensed = computed(() => state.value === 'unlicensed')

  // Show a header pill during trial/grace/expired states
  const showBanner  = computed(() =>
    ['trial', 'grace', 'unlicensed', 'expired'].includes(state.value)
  )

  const bannerText = computed(() => {
    if (state.value === 'trial')      return `Trial · ${daysLeft.value}d left`
    if (state.value === 'grace')      return `Grace period · ${daysLeft.value}d left`
    if (state.value === 'unlicensed') return 'License required'
    if (state.value === 'expired')    return 'Support expired'
    return ''
  })

  const bannerColor = computed(() => {
    if (state.value === 'trial')   return 'var(--accent)'
    if (state.value === 'grace')   return 'var(--warning, #f0a500)'
    return 'var(--danger, #e53935)'
  })

  function hasFeature(feature) {
    return features.value.includes(feature)
  }

  async function fetchStatus(retries = 2) {
    loading.value = true
    try {
      status.value = await get('/api/license/status')
    } catch {
      // Retry — the auth token may not be ready yet on first load
      if (retries > 0) {
        setTimeout(() => fetchStatus(retries - 1), 3000)
      }
    }
    finally { loading.value = false }
  }

  return {
    status, loading,
    state, active, plan, licensee, seats, userCount, features,
    daysLeft, trial, expiresAt,
    isTrial, isGrace, isLicensed, isExpired, isUnlicensed,
    showBanner, bannerText, bannerColor,
    hasFeature, fetchStatus,
  }
})
