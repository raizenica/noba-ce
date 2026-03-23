import { ref } from 'vue'
import { useAuthStore } from '../stores/auth'

const _STATUS_MESSAGES = {
  400: 'Invalid request',
  403: 'Permission denied',
  404: 'Not found',
  409: 'Conflict — resource already exists',
  413: 'Upload too large',
  422: 'Validation error',
  429: 'Too many requests — please wait',
  500: 'Server error',
  502: 'Server unavailable',
  503: 'Service temporarily unavailable',
}

function _friendlyError(status, detail) {
  if (detail) return detail
  return _STATUS_MESSAGES[status] || `Unexpected error (HTTP ${status})`
}

export function useApi() {
  const loading = ref(false)
  const error = ref(null)

  async function request(url, options = {}) {
    const auth = useAuthStore()
    loading.value = true
    error.value = null
    try {
      const headers = { ...options.headers }
      if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`
      if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData) && !(options.body instanceof Uint8Array)) {
        headers['Content-Type'] = 'application/json'
        options.body = JSON.stringify(options.body)
      }
      const res = await fetch(url, { ...options, headers })
      if (res.status === 401) {
        auth.clearAuth()
        return null
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(_friendlyError(res.status, data.detail))
      }
      const ct = res.headers.get('content-type') || ''
      if (ct.includes('application/json')) return await res.json()
      return await res.text()
    } catch (e) {
      if (e instanceof TypeError && e.message === 'Failed to fetch') {
        e.message = 'Connection lost — check your network'
        error.value = e.message
        throw e
      }
      error.value = e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  const get = (url) => request(url)
  const post = (url, body) => request(url, { method: 'POST', body })
  const put = (url, body) => request(url, { method: 'PUT', body })
  const del = (url) => request(url, { method: 'DELETE' })
  const download = async (url) => {
    const auth = useAuthStore()
    const headers = {}
    if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`
    const res = await fetch(url, { headers })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res
  }

  return { request, get, post, put, del, download, loading, error }
}
