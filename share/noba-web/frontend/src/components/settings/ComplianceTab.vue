<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get } = useApi()

const report = ref(null)
const loading = ref(false)
const error = ref('')

async function load() {
  if (!authStore.isAdmin) return
  loading.value = true
  error.value = ''
  try {
    report.value = await get('/api/enterprise/compliance/report')
  } catch (e) {
    error.value = e.message || 'Failed to load compliance report'
  }
  loading.value = false
}

onMounted(load)

// ── Helpers ────────────────────────────────────────────────────────────────
function scoreColor(score) {
  if (score === null || score === undefined) return 'var(--text-muted)'
  if (score >= 80) return 'var(--success, #4caf50)'
  if (score >= 50) return 'var(--warning, #ff9800)'
  return 'var(--danger, #f44336)'
}

function scoreLabel(score) {
  if (score === null || score === undefined) return 'No data'
  if (score >= 80) return 'Good'
  if (score >= 50) return 'Fair'
  return 'Poor'
}

function formatTs(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : '—'
}

function quotaLabel(key) {
  return {
    max_api_keys: 'API Keys', max_automations: 'Automations', max_webhooks: 'Webhooks'
  }[key] || key
}

const overallScore = computed(() => report.value?.security?.avg_score ?? null)

function printReport() {
  window.print()
}
</script>

<style scoped>
@media print {
  .no-print { display: none !important; }
  .print-section { page-break-inside: avoid; }
}
</style>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
      <h3 style="margin:0">Compliance Report</h3>
      <div class="no-print" style="display:flex;gap:.5rem">
        <button class="btn btn-sm" @click="load" :disabled="loading">
          <i class="fas fa-sync" :class="loading ? 'fa-spin' : ''"></i> Refresh
        </button>
        <button class="btn btn-sm btn-primary" @click="printReport">
          <i class="fas fa-print"></i> Export / Print
        </button>
      </div>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-if="loading" style="text-align:center;padding:3rem;color:var(--text-muted)">
      <i class="fas fa-spinner fa-spin"></i> Generating report…
    </div>

    <template v-else-if="report">
      <!-- Generated timestamp -->
      <div style="font-size:.78rem;color:var(--text-muted);margin-bottom:1rem">
        Generated {{ formatTs(report.generated_at) }} — Tenant: <code>{{ report.tenant_id }}</code>
      </div>

      <!-- ── Summary Scorecard ── -->
      <div class="print-section card" style="padding:1rem;margin-bottom:1rem">
        <h4 style="margin:0 0 .75rem 0"><i class="fas fa-shield-alt" style="margin-right:.4rem"></i>Security Posture</h4>
        <div style="display:flex;gap:1.5rem;flex-wrap:wrap;align-items:center">
          <!-- Overall Score -->
          <div style="text-align:center;min-width:100px">
            <div style="font-size:2.5rem;font-weight:700;line-height:1"
              :style="{ color: scoreColor(overallScore) }">
              {{ overallScore !== null ? overallScore : '—' }}
            </div>
            <div style="font-size:.8rem;color:var(--text-muted)">Avg Score</div>
            <div style="font-size:.78rem;font-weight:600" :style="{ color: scoreColor(overallScore) }">
              {{ scoreLabel(overallScore) }}
            </div>
          </div>

          <!-- Stats -->
          <div style="display:flex;gap:1.5rem;flex-wrap:wrap">
            <div class="stat-box">
              <div class="stat-val" :style="{ color: report.incidents.open > 0 ? 'var(--danger)' : 'var(--success,#4caf50)' }">
                {{ report.incidents.open }}
              </div>
              <div class="stat-lbl">Open Incidents</div>
            </div>
            <div class="stat-box">
              <div class="stat-val" :style="{ color: report.drift.drifted_count > 0 ? 'var(--warning,#ff9800)' : 'var(--success,#4caf50)' }">
                {{ report.drift.drifted_count }}
              </div>
              <div class="stat-lbl">Config Drift</div>
            </div>
            <div class="stat-box">
              <div class="stat-val">{{ report.security.host_count }}</div>
              <div class="stat-lbl">Scanned Hosts</div>
            </div>
            <div class="stat-box">
              <div class="stat-val">{{ report.incidents.total_7d }}</div>
              <div class="stat-lbl">Incidents (7d)</div>
            </div>
          </div>
        </div>
      </div>

      <!-- ── Per-host Security Table ── -->
      <div v-if="report.security.hosts.length" class="print-section card" style="padding:0;overflow:hidden;margin-bottom:1rem">
        <div style="padding:.6rem 1rem;border-bottom:1px solid var(--border)">
          <strong>Host Security Scores</strong>
        </div>
        <table class="table" style="margin:0;font-size:.85rem">
          <thead>
            <tr>
              <th>Hostname</th>
              <th>Score</th>
              <th>Rating</th>
              <th>Last Scanned</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="h in report.security.hosts" :key="h.hostname">
              <td><strong>{{ h.hostname }}</strong></td>
              <td>
                <span style="font-weight:700" :style="{ color: scoreColor(h.score) }">{{ h.score }}</span>
              </td>
              <td>
                <span class="badge" :style="{ background: scoreColor(h.score) }">{{ scoreLabel(h.score) }}</span>
              </td>
              <td style="color:var(--text-muted);font-size:.8rem">{{ formatTs(h.scanned_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ── Incident Breakdown ── -->
      <div class="print-section" style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem">
        <div class="card" style="padding:.75rem 1rem">
          <h5 style="margin:0 0 .6rem 0"><i class="fas fa-exclamation-triangle" style="margin-right:.4rem;color:var(--warning,#ff9800)"></i>Open Incidents by Severity</h5>
          <div v-if="Object.keys(report.incidents.by_severity).length">
            <div v-for="(cnt, sev) in report.incidents.by_severity" :key="sev"
              style="display:flex;justify-content:space-between;align-items:center;padding:.25rem 0;border-bottom:1px solid var(--border);font-size:.85rem">
              <span>{{ sev }}</span>
              <span class="badge" :style="sev === 'critical' ? 'background:var(--danger)' : sev === 'high' ? 'background:var(--warning,#ff9800)' : ''">{{ cnt }}</span>
            </div>
          </div>
          <div v-else style="color:var(--text-muted);font-size:.85rem;padding:.5rem 0">No open incidents.</div>
        </div>

        <!-- ── Audit Activity ── -->
        <div class="card" style="padding:.75rem 1rem">
          <h5 style="margin:0 0 .6rem 0"><i class="fas fa-history" style="margin-right:.4rem"></i>Audit Activity (7d)</h5>
          <div style="font-size:.78rem;color:var(--text-muted);margin-bottom:.4rem">{{ report.audit.event_count_7d }} total events</div>
          <div v-for="item in report.audit.top_actions" :key="item.action"
            style="display:flex;justify-content:space-between;align-items:center;padding:.2rem 0;border-bottom:1px solid var(--border);font-size:.83rem">
            <code>{{ item.action }}</code>
            <span>{{ item.count }}</span>
          </div>
          <div v-if="!report.audit.top_actions.length" style="color:var(--text-muted);font-size:.85rem;padding:.5rem 0">No activity this week.</div>
        </div>
      </div>

      <!-- ── Resource Inventory ── -->
      <div class="print-section card" style="padding:.75rem 1rem;margin-bottom:1rem">
        <h5 style="margin:0 0 .6rem 0"><i class="fas fa-cubes" style="margin-right:.4rem"></i>Resource Inventory</h5>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:.75rem">
          <div class="stat-box">
            <div class="stat-val"><i class="fas fa-users" style="font-size:1rem"></i></div>
            <div class="stat-val">{{ report.resources.members }}</div>
            <div class="stat-lbl">Members</div>
          </div>
          <div class="stat-box">
            <div class="stat-val">{{ report.resources.api_keys }}</div>
            <div class="stat-lbl">
              API Keys
              <span v-if="report.resources.quotas.max_api_keys > 0" style="color:var(--text-muted)">
                / {{ report.resources.quotas.max_api_keys }}
              </span>
            </div>
          </div>
          <div class="stat-box">
            <div class="stat-val">{{ report.resources.automations }}</div>
            <div class="stat-lbl">
              Automations
              <span v-if="report.resources.quotas.max_automations > 0" style="color:var(--text-muted)">
                / {{ report.resources.quotas.max_automations }}
              </span>
            </div>
          </div>
          <div class="stat-box">
            <div class="stat-val">{{ report.resources.webhooks }}</div>
            <div class="stat-lbl">
              Webhooks
              <span v-if="report.resources.quotas.max_webhooks > 0" style="color:var(--text-muted)">
                / {{ report.resources.quotas.max_webhooks }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </template>

    <div v-else-if="!loading" style="text-align:center;padding:2rem;color:var(--text-muted)">
      No compliance data available.
    </div>
  </div>
</template>

<style scoped>
.stat-box {
  text-align: center;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: .5rem;
}
.stat-val {
  font-size: 1.5rem;
  font-weight: 700;
  line-height: 1.2;
}
.stat-lbl {
  font-size: .75rem;
  color: var(--text-muted);
  margin-top: .15rem;
}
</style>
