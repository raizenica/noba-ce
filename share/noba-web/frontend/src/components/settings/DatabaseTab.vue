<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get } = useApi()

const status = ref(null)
const loading = ref(false)
const showMigration = ref(false)
const copied = ref(false)
const migrationCmd = ref('')

onMounted(async () => {
  if (!authStore.isAdmin) return
  loading.value = true
  try {
    status.value = await get('/api/enterprise/db/status')
    if (status.value?.backend === 'sqlite') {
      migrationCmd.value =
        `DATABASE_URL=postgresql://user:pass@host/noba \\\n` +
        `  python3 scripts/migrate-to-postgres.py ${status.value.path || '~/.local/share/noba-history.db'}`
    }
  } catch (e) {
    status.value = { backend: 'unknown', error: e.message }
  }
  loading.value = false
})

async function copyCmd() {
  await navigator.clipboard.writeText(migrationCmd.value)
  copied.value = true
  setTimeout(() => { copied.value = false }, 1500)
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
        <span class="s-label">Database Backend</span>

        <div v-if="loading" style="padding:2rem;text-align:center;color:var(--text-muted)">
          <i class="fas fa-spinner fa-spin"></i> Loading…
        </div>

        <template v-else-if="status">
          <div style="display:flex;align-items:center;gap:.75rem;margin-bottom:1rem">
            <span class="badge" :class="status.backend === 'postgresql' ? 'ba' : 'bn'">
              {{ status.backend === 'postgresql' ? 'PostgreSQL' : status.backend === 'sqlite' ? 'SQLite' : status.backend }}
            </span>
            <span v-if="status.backend === 'postgresql'">
              <i class="fas fa-circle"
                :style="status.connected ? 'color:var(--success,#4ade80)' : 'color:var(--danger,#f87171)'"></i>
              {{ status.connected ? 'Connected' : 'Disconnected' }}
            </span>
          </div>

          <template v-if="status.backend === 'sqlite'">
            <div style="font-size:.82rem;display:flex;flex-direction:column;gap:.3rem;margin-bottom:1rem;color:var(--text-muted)">
              <span><strong>Path:</strong> {{ status.path }}</span>
              <span><strong>WAL mode:</strong>
                <span :style="status.wal_mode ? 'color:var(--success,#4ade80)' : ''">
                  {{ status.wal_mode ? 'enabled' : 'disabled' }}
                </span>
              </span>
            </div>
            <div style="font-size:.8rem;color:var(--text-muted);margin-bottom:.75rem">
              <i class="fas fa-info-circle"></i>
              SQLite is ideal for single-server deployments.
              Switch to PostgreSQL or MySQL for multi-instance or high-load environments.
            </div>

            <div style="border:1px solid var(--border);border-radius:4px;overflow:hidden">
              <button class="btn btn-sm"
                style="width:100%;text-align:left;border-radius:0;padding:.6rem .75rem;display:flex;justify-content:space-between"
                @click="showMigration = !showMigration">
                <span><i class="fas fa-database" style="margin-right:.4rem"></i> Migrate to PostgreSQL</span>
                <i class="fas" :class="showMigration ? 'fa-chevron-up' : 'fa-chevron-down'"></i>
              </button>
              <div v-if="showMigration" style="padding:.75rem;background:var(--surface-2)">
                <p style="font-size:.8rem;color:var(--text-muted);margin-bottom:.5rem">
                  Set <code>DATABASE_URL</code> in your environment, then run the migration script once. Restart NOBA after migration.
                </p>
                <div style="position:relative">
                  <pre style="font-size:.78rem;background:var(--surface);border:1px solid var(--border);padding:.75rem;border-radius:4px;overflow-x:auto;margin:0">{{ migrationCmd }}</pre>
                  <button class="btn btn-xs" style="position:absolute;top:.4rem;right:.4rem" @click="copyCmd">
                    <i class="fas" :class="copied ? 'fa-check' : 'fa-copy'"></i>
                  </button>
                </div>
                <p style="font-size:.75rem;color:var(--text-muted);margin-top:.5rem">
                  <i class="fas fa-info-circle"></i>
                  <code>DATABASE_URL</code> is read from the environment on startup. Requires server restart to take effect.
                </p>
              </div>
            </div>
          </template>

          <template v-else-if="status.backend === 'postgresql'">
            <div style="font-size:.82rem;display:grid;grid-template-columns:auto 1fr;gap:.3rem .75rem;margin-bottom:1rem">
              <span style="color:var(--text-muted)">Host</span>     <span>{{ status.host }}</span>
              <span style="color:var(--text-muted)">Database</span> <span>{{ status.database }}</span>
              <span style="color:var(--text-muted)">Version</span>  <span>{{ status.server_version }}</span>
              <span style="color:var(--text-muted)">Pool min</span> <span>{{ status.pool_min }}</span>
              <span style="color:var(--text-muted)">Pool max</span> <span>{{ status.pool_max }}</span>
            </div>
            <div v-if="status.error" style="font-size:.8rem;color:var(--danger,#f87171)">
              Error: {{ status.error }}
            </div>
          </template>
        </template>
      </div>
    </template>
  </div>
</template>
