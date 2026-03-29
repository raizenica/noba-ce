<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get } = useApi()

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')

// Filters
const filterUsername = ref('')
const filterAction = ref('')
const filterFromDate = ref('')
const filterToDate = ref('')
const availableActions = ref([])

// Pagination
const limit = 100
const offset = ref(0)

const totalPages = computed(() => Math.ceil(total.value / limit) || 1)
const currentPage = computed(() => Math.floor(offset.value / limit) + 1)

function dateToTs(dateStr) {
  return dateStr ? Math.floor(new Date(dateStr).getTime() / 1000) : 0
}

async function load() {
  if (!authStore.isAdmin) return
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams({ limit, offset: offset.value })
    if (filterUsername.value) params.set('username', filterUsername.value)
    if (filterAction.value) params.set('action', filterAction.value)
    const fromTs = dateToTs(filterFromDate.value)
    const toTs = filterToDate.value ? dateToTs(filterToDate.value) + 86399 : 0
    if (fromTs) params.set('from_ts', fromTs)
    if (toTs) params.set('to_ts', toTs)

    const data = await get(`/api/enterprise/audit?${params}`)
    rows.value = data.rows || []
    total.value = data.total || 0
  } catch (e) {
    error.value = e.message || 'Failed to load audit log'
  }
  loading.value = false
}

async function applyFilters() {
  offset.value = 0
  await load()
}

function prevPage() {
  if (offset.value >= limit) { offset.value -= limit; load() }
}
function nextPage() {
  if (offset.value + limit < total.value) { offset.value += limit; load() }
}

function exportLog(fmt) {
  const params = new URLSearchParams({ format: fmt })
  if (filterUsername.value) params.set('username', filterUsername.value)
  if (filterAction.value) params.set('action', filterAction.value)
  const fromTs = dateToTs(filterFromDate.value)
  const toTs = filterToDate.value ? dateToTs(filterToDate.value) + 86399 : 0
  if (fromTs) params.set('from_ts', fromTs)
  if (toTs) params.set('to_ts', toTs)
  window.location.href = `/api/enterprise/audit/export?${params}`
}

function formatTime(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : '—'
}

// Expand/collapse row details
const expanded = ref(new Set())
function toggleRow(idx) {
  if (expanded.value.has(idx)) expanded.value.delete(idx)
  else expanded.value.add(idx)
}

onMounted(async () => {
  if (!authStore.isAdmin) return
  try {
    availableActions.value = await get('/api/enterprise/audit/actions')
  } catch (_) {}
  await load()
})
</script>

<template>
  <div>
    <h3 style="margin-bottom:1rem">Audit Log</h3>

    <!-- Filters -->
    <div class="card" style="margin-bottom:1rem;padding:.75rem 1rem">
      <div style="display:flex;flex-wrap:wrap;gap:.75rem;align-items:flex-end">
        <div>
          <label style="display:block;font-size:.8rem;color:var(--text-muted);margin-bottom:.2rem">User</label>
          <input v-model="filterUsername" type="text" placeholder="any user"
            style="width:140px" @keydown.enter="applyFilters" />
        </div>
        <div>
          <label style="display:block;font-size:.8rem;color:var(--text-muted);margin-bottom:.2rem">Action</label>
          <select v-model="filterAction" style="width:160px">
            <option value="">All actions</option>
            <option v-for="a in availableActions" :key="a" :value="a">{{ a }}</option>
          </select>
        </div>
        <div>
          <label style="display:block;font-size:.8rem;color:var(--text-muted);margin-bottom:.2rem">From</label>
          <input v-model="filterFromDate" type="date" style="width:140px" />
        </div>
        <div>
          <label style="display:block;font-size:.8rem;color:var(--text-muted);margin-bottom:.2rem">To</label>
          <input v-model="filterToDate" type="date" style="width:140px" />
        </div>
        <button class="btn btn-primary btn-sm" @click="applyFilters" :disabled="loading">
          <i class="fas fa-search"></i> Filter
        </button>
        <button class="btn btn-sm" @click="filterUsername='';filterAction='';filterFromDate='';filterToDate='';applyFilters()">
          Clear
        </button>
        <div style="margin-left:auto;display:flex;gap:.5rem">
          <button class="btn btn-sm" @click="exportLog('csv')" title="Export CSV">
            <i class="fas fa-file-csv"></i> CSV
          </button>
          <button class="btn btn-sm" @click="exportLog('json')" title="Export JSON">
            <i class="fas fa-file-code"></i> JSON
          </button>
        </div>
      </div>
    </div>

    <!-- Error -->
    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <!-- Loading -->
    <div v-if="loading" style="text-align:center;padding:2rem;color:var(--text-muted)">
      <i class="fas fa-spinner fa-spin"></i> Loading…
    </div>

    <!-- Table -->
    <div v-else-if="rows.length" class="card" style="padding:0;overflow:hidden">
      <table class="table" style="margin:0;font-size:.85rem">
        <thead>
          <tr>
            <th style="width:160px">Time</th>
            <th style="width:130px">User</th>
            <th style="width:160px">Action</th>
            <th>Details</th>
            <th style="width:120px">IP</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="(row, idx) in rows" :key="idx">
            <tr style="cursor:pointer" @click="toggleRow(idx)">
              <td style="color:var(--text-muted);white-space:nowrap">{{ formatTime(row.time) }}</td>
              <td><strong>{{ row.username }}</strong></td>
              <td>
                <span class="badge"
                  :style="row.action.includes('fail') || row.action.includes('error') ? 'background:var(--danger)' : ''">
                  {{ row.action }}
                </span>
              </td>
              <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                {{ row.details || '—' }}
              </td>
              <td style="color:var(--text-muted);font-size:.78rem">{{ row.ip || '—' }}</td>
            </tr>
            <tr v-if="expanded.has(idx)">
              <td colspan="5" style="background:var(--bg-secondary);padding:.5rem 1rem;font-size:.8rem">
                <strong>Full details:</strong> {{ row.details || '(none)' }}
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <!-- Empty -->
    <div v-else style="text-align:center;padding:2rem;color:var(--text-muted)">
      No audit events match the current filters.
    </div>

    <!-- Pagination -->
    <div v-if="total > limit" style="display:flex;justify-content:space-between;align-items:center;margin-top:.75rem">
      <span style="font-size:.85rem;color:var(--text-muted)">
        {{ offset + 1 }}–{{ Math.min(offset + limit, total) }} of {{ total.toLocaleString() }} events
      </span>
      <div style="display:flex;gap:.5rem">
        <button class="btn btn-sm" :disabled="currentPage === 1" @click="prevPage">
          <i class="fas fa-chevron-left"></i> Prev
        </button>
        <span style="line-height:2rem;font-size:.85rem">Page {{ currentPage }} / {{ totalPages }}</span>
        <button class="btn btn-sm" :disabled="currentPage === totalPages" @click="nextPage">
          Next <i class="fas fa-chevron-right"></i>
        </button>
      </div>
    </div>

    <!-- Summary line -->
    <div v-if="!loading && total > 0" style="margin-top:.5rem;font-size:.8rem;color:var(--text-muted)">
      {{ total.toLocaleString() }} total events in tenant scope.
      Click any row to expand details.
    </div>
  </div>
</template>
