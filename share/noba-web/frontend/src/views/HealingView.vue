<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useApi } from '../composables/useApi'
import { useNotificationsStore } from '../stores/notifications'
import { useIntervals } from '../composables/useIntervals'

const authStore = useAuthStore()
const { get, post } = useApi()
const notify = useNotificationsStore()
const { addInterval, clearAll } = useIntervals()

// ── Tab state ─────────────────────────────────────────────────────────────────
const activeTab = ref('ledger')

// ── Ledger ────────────────────────────────────────────────────────────────────
const ledger = ref([])
const ledgerLoading = ref(false)
const ledgerFilterRule = ref('')
const ledgerFilterTarget = ref('')

const ledgerRuleOptions = computed(() => {
  const ids = [...new Set(ledger.value.map(r => r.rule_id).filter(Boolean))]
  return ids.sort()
})

const ledgerTargetOptions = computed(() => {
  const targets = [...new Set(ledger.value.map(r => r.target).filter(Boolean))]
  return targets.sort()
})

const filteredLedger = computed(() => {
  return ledger.value.filter(r => {
    if (ledgerFilterRule.value && r.rule_id !== ledgerFilterRule.value) return false
    if (ledgerFilterTarget.value && r.target !== ledgerFilterTarget.value) return false
    return true
  })
})

async function fetchLedger() {
  ledgerLoading.value = true
  try {
    const params = new URLSearchParams({ limit: '50' })
    if (ledgerFilterRule.value) params.set('rule_id', ledgerFilterRule.value)
    if (ledgerFilterTarget.value) params.set('target', ledgerFilterTarget.value)
    const data = await get(`/api/healing/ledger?${params}`)
    ledger.value = data || []
  } catch (e) {
    notify.error('Failed to load healing ledger')
  } finally {
    ledgerLoading.value = false
  }
}

function ledgerRowStyle(row) {
  if (row.verified === true) return { borderLeft: '3px solid var(--success)' }
  if (row.action_success === false) return { borderLeft: '3px solid var(--danger)' }
  if (row.verified === false) return { borderLeft: '3px solid var(--warning)' }
  return {}
}

function fmtBool(val) {
  if (val === true) return '✓'
  if (val === false) return '✗'
  return '–'
}

function fmtTs(ts) {
  if (!ts) return '–'
  return new Date(ts * 1000).toLocaleString()
}

// ── Trust ─────────────────────────────────────────────────────────────────────
const trustStates = ref([])
const trustLoading = ref(false)
const promoteConfirm = ref(null)
const promoteLoading = ref(false)

async function fetchTrust() {
  trustLoading.value = true
  try {
    const data = await get('/api/healing/trust')
    trustStates.value = data || []
  } catch (e) {
    notify.error('Failed to load trust states')
  } finally {
    trustLoading.value = false
  }
}

function trustLevelClass(level) {
  if (level === 'execute') return 'bs'
  if (level === 'approve') return 'bw'
  return 'ba'
}

function openPromote(ruleId) {
  promoteConfirm.value = ruleId
}

function cancelPromote() {
  promoteConfirm.value = null
}

async function confirmPromote(ruleId) {
  promoteLoading.value = true
  try {
    const res = await post(`/api/healing/trust/${ruleId}/promote`, {})
    if (res && res.success) {
      notify.success(`Rule ${ruleId} promoted to ${res.new_level}`)
      await fetchTrust()
    }
  } catch (e) {
    notify.error('Failed to promote trust level')
  } finally {
    promoteLoading.value = false
    promoteConfirm.value = null
  }
}

// ── Suggestions ───────────────────────────────────────────────────────────────
const suggestions = ref([])
const suggestionsLoading = ref(false)
const dismissingId = ref(null)

async function fetchSuggestions() {
  suggestionsLoading.value = true
  try {
    const data = await get('/api/healing/suggestions')
    suggestions.value = data || []
  } catch (e) {
    notify.error('Failed to load suggestions')
  } finally {
    suggestionsLoading.value = false
  }
}

async function dismissSuggestion(id) {
  dismissingId.value = id
  try {
    const res = await post(`/api/healing/suggestions/${id}/dismiss`, {})
    if (res && res.success) {
      suggestions.value = suggestions.value.filter(s => s.id !== id)
      notify.success('Suggestion dismissed')
    }
  } catch (e) {
    notify.error('Failed to dismiss suggestion')
  } finally {
    dismissingId.value = null
  }
}

function severityClass(severity) {
  if (severity === 'high') return 'bd'
  if (severity === 'medium') return 'bw'
  return 'bs'
}

function categoryClass(category) {
  return 'ba'
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  fetchLedger()
  fetchTrust()
  fetchSuggestions()
  addInterval(() => fetchLedger(), 30000)
})

onUnmounted(() => {
  clearAll()
})
</script>

<template>
  <div class="view-root">
    <div class="view-header">
      <h1 class="view-title"><i class="fas fa-heartbeat" style="margin-right:8px"></i>Self-Healing</h1>
      <p class="view-subtitle">Monitor heal outcomes, trust levels, and pipeline suggestions</p>
    </div>

    <!-- Tab nav -->
    <div class="tab-nav" style="margin-bottom:20px">
      <button
        class="btn"
        :class="activeTab === 'ledger' ? 'btn-primary' : ''"
        @click="activeTab = 'ledger'"
      >
        <i class="fas fa-list-alt" style="margin-right:6px"></i>Ledger
      </button>
      <button
        class="btn"
        :class="activeTab === 'trust' ? 'btn-primary' : ''"
        @click="activeTab = 'trust'"
        style="margin-left:8px"
      >
        <i class="fas fa-shield-alt" style="margin-right:6px"></i>Trust
      </button>
      <button
        class="btn"
        :class="activeTab === 'suggestions' ? 'btn-primary' : ''"
        @click="activeTab = 'suggestions'"
        style="margin-left:8px"
      >
        <i class="fas fa-lightbulb" style="margin-right:6px"></i>Suggestions
        <span v-if="suggestions.length" class="nav-badge" style="margin-left:6px">{{ suggestions.length }}</span>
      </button>
    </div>

    <!-- ── Ledger Tab ─────────────────────────────────────────────────────── -->
    <div v-if="activeTab === 'ledger'">
      <!-- Filters -->
      <div style="display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap;align-items:center">
        <select v-model="ledgerFilterRule" class="form-select" style="width:auto" @change="fetchLedger">
          <option value="">All rules</option>
          <option v-for="r in ledgerRuleOptions" :key="r" :value="r">{{ r }}</option>
        </select>
        <select v-model="ledgerFilterTarget" class="form-select" style="width:auto" @change="fetchLedger">
          <option value="">All targets</option>
          <option v-for="t in ledgerTargetOptions" :key="t" :value="t">{{ t }}</option>
        </select>
        <button class="btn btn-xs" @click="fetchLedger" :disabled="ledgerLoading">
          <i class="fas fa-sync-alt" :class="{ 'fa-spin': ledgerLoading }"></i>
          Refresh
        </button>
        <span style="color:var(--text-muted);font-size:12px">Auto-refreshes every 30s</span>
      </div>

      <!-- Table -->
      <div class="card">
        <div class="card-body" style="padding:0;overflow-x:auto">
          <table style="width:100%;border-collapse:collapse;font-size:13px">
            <thead>
              <tr style="background:var(--surface2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px">
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Timestamp</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Rule ID</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Target</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Action</th>
                <th style="padding:10px 14px;text-align:center;border-bottom:1px solid var(--border)">Step</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Trust</th>
                <th style="padding:10px 14px;text-align:center;border-bottom:1px solid var(--border)">Success</th>
                <th style="padding:10px 14px;text-align:center;border-bottom:1px solid var(--border)">Verified</th>
                <th style="padding:10px 14px;text-align:right;border-bottom:1px solid var(--border)">Duration</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="ledgerLoading && filteredLedger.length === 0">
                <td colspan="9" style="padding:24px;text-align:center;color:var(--text-muted)">
                  <i class="fas fa-spinner fa-spin"></i> Loading…
                </td>
              </tr>
              <tr v-else-if="filteredLedger.length === 0">
                <td colspan="9" class="empty-msg">No heal outcomes recorded yet.</td>
              </tr>
              <tr
                v-for="row in filteredLedger"
                :key="row.id || (row.rule_id + row.ts)"
                :style="ledgerRowStyle(row)"
                style="border-bottom:1px solid var(--border);transition:background .15s"
                class="table-row-hover"
              >
                <td style="padding:9px 14px;color:var(--text-muted);white-space:nowrap">{{ fmtTs(row.ts) }}</td>
                <td style="padding:9px 14px;font-family:monospace;font-size:12px">{{ row.rule_id || '–' }}</td>
                <td style="padding:9px 14px;font-family:monospace;font-size:12px">{{ row.target || '–' }}</td>
                <td style="padding:9px 14px">
                  <span class="badge ba">{{ row.action_type || '–' }}</span>
                </td>
                <td style="padding:9px 14px;text-align:center">{{ row.escalation_step ||0 }}</td>
                <td style="padding:9px 14px">
                  <span v-if="row.trust_level" class="badge" :class="trustLevelClass(row.trust_level)">{{ row.trust_level }}</span>
                  <span v-else style="color:var(--text-muted)">–</span>
                </td>
                <td style="padding:9px 14px;text-align:center;font-weight:600"
                    :style="{ color: row.action_success === true ? 'var(--success)' : row.action_success === false ? 'var(--danger)' : 'var(--text-muted)' }">
                  {{ fmtBool(row.action_success) }}
                </td>
                <td style="padding:9px 14px;text-align:center;font-weight:600"
                    :style="{ color: row.verified === true ? 'var(--success)' : row.verified === false ? 'var(--warning)' : 'var(--text-muted)' }">
                  {{ fmtBool(row.verified) }}
                </td>
                <td style="padding:9px 14px;text-align:right;color:var(--text-muted)">
                  {{ row.duration_s != null ? (row.duration_s ||0).toFixed(1) + 's' : '–' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ── Trust Tab ──────────────────────────────────────────────────────── -->
    <div v-if="activeTab === 'trust'">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
        <button class="btn btn-xs" @click="fetchTrust" :disabled="trustLoading">
          <i class="fas fa-sync-alt" :class="{ 'fa-spin': trustLoading }"></i>
          Refresh
        </button>
      </div>

      <div v-if="trustLoading && trustStates.length === 0" style="padding:32px;text-align:center;color:var(--text-muted)">
        <i class="fas fa-spinner fa-spin"></i> Loading…
      </div>

      <p v-else-if="trustStates.length === 0" class="empty-msg">No trust states found.</p>

      <div v-else style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px">
        <div v-for="state in trustStates" :key="state.rule_id" class="card">
          <div class="card-body">
            <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:12px">
              <div>
                <div style="font-family:monospace;font-size:13px;font-weight:600;margin-bottom:4px">{{ state.rule_id }}</div>
                <span class="badge" :class="trustLevelClass(state.current_level)">{{ state.current_level }}</span>
              </div>
              <div v-if="authStore.isAdmin">
                <button
                  v-if="promoteConfirm !== state.rule_id"
                  class="btn btn-xs"
                  @click="openPromote(state.rule_id)"
                >
                  <i class="fas fa-arrow-up"></i> Promote
                </button>
                <div v-else style="display:flex;gap:6px;align-items:center">
                  <span style="font-size:12px;color:var(--text-muted)">Sure?</span>
                  <button class="btn btn-xs btn-primary" :disabled="promoteLoading" @click="confirmPromote(state.rule_id)">
                    <i v-if="promoteLoading" class="fas fa-spinner fa-spin"></i>
                    <span v-else>Yes</span>
                  </button>
                  <button class="btn btn-xs" @click="cancelPromote">No</button>
                </div>
              </div>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:12px">
              <div style="color:var(--text-muted)">Ceiling</div>
              <div>
                <span class="badge" :class="trustLevelClass(state.ceiling)">{{ state.ceiling || '–' }}</span>
              </div>
              <div style="color:var(--text-muted)">Promotions</div>
              <div style="color:var(--success);font-weight:600">{{ state.promotion_count ||0 }}</div>
              <div style="color:var(--text-muted)">Demotions</div>
              <div style="color:var(--danger);font-weight:600">{{ state.demotion_count ||0 }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Suggestions Tab ────────────────────────────────────────────────── -->
    <div v-if="activeTab === 'suggestions'">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
        <button class="btn btn-xs" @click="fetchSuggestions" :disabled="suggestionsLoading">
          <i class="fas fa-sync-alt" :class="{ 'fa-spin': suggestionsLoading }"></i>
          Refresh
        </button>
      </div>

      <div v-if="suggestionsLoading && suggestions.length === 0" style="padding:32px;text-align:center;color:var(--text-muted)">
        <i class="fas fa-spinner fa-spin"></i> Loading…
      </div>

      <p v-else-if="suggestions.length === 0" class="empty-msg">No suggestions at this time. The pipeline is running smoothly.</p>

      <div v-else style="display:flex;flex-direction:column;gap:12px">
        <div v-for="sug in suggestions" :key="sug.id" class="card">
          <div class="card-body" style="display:flex;align-items:flex-start;gap:14px">
            <div style="flex:1">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap">
                <span class="badge" :class="categoryClass(sug.category)">{{ sug.category || 'general' }}</span>
                <span class="badge" :class="severityClass(sug.severity)">{{ sug.severity || 'low' }}</span>
                <span v-if="sug.rule_id" style="font-family:monospace;font-size:11px;color:var(--text-muted)">{{ sug.rule_id }}</span>
              </div>
              <p style="margin:0;font-size:13px;line-height:1.5">{{ sug.message }}</p>
            </div>
            <div v-if="authStore.isOperator" style="flex-shrink:0">
              <button
                class="btn btn-xs"
                :disabled="dismissingId === sug.id"
                @click="dismissSuggestion(sug.id)"
              >
                <i v-if="dismissingId === sug.id" class="fas fa-spinner fa-spin"></i>
                <i v-else class="fas fa-times"></i>
                Dismiss
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
