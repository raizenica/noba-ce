<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const status = ref('Completing sign-in…')

onMounted(async () => {
  const code = route.query.code
  if (!code) {
    status.value = 'Missing authorization code.'
    setTimeout(() => window.close(), 2000)
    return
  }
  try {
    const res = await fetch('/api/auth/exchange', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    })
    if (!res.ok) {
      status.value = 'Sign-in failed. Please try again.'
      setTimeout(() => window.close(), 2000)
      return
    }
    const data = await res.json()
    // Write token to localStorage — the main window detects this
    // via the 'storage' event and completes the login.
    localStorage.setItem('noba-token', data.token)
    status.value = 'Signed in — closing…'
    window.close()
  } catch {
    status.value = 'Sign-in failed. Please try again.'
    setTimeout(() => window.close(), 2000)
  }
})
</script>

<template>
  <div style="display:flex;align-items:center;justify-content:center;height:100vh;background:var(--bg);color:var(--text-muted);font-size:.9rem">
    <i class="fas fa-circle-notch fa-spin" style="margin-right:.5rem"></i> {{ status }}
  </div>
</template>
