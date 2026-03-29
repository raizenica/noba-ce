<script setup>
import { ref, computed, onMounted } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import { useApi } from '../../composables/useApi'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const { get } = useApi()

const healthScore = ref(null)

onMounted(async () => {
  try {
    healthScore.value = await get('/api/health-score')
  } catch { /* non-critical */ }
})

const agents = computed(() => dashboard.live.agents || [])
const onlineAgents = computed(() => agents.value.filter(a => a.online).length)
const activeAlerts = computed(() => (dashboard.live.alerts || []).filter(a => !a.resolved).length)

const scoreGrade = computed(() => healthScore.value?.grade || '—')
const scoreValue = computed(() => healthScore.value?.score ?? null)

function gradeColor(grade) {
  if (grade === 'A') return 'var(--success, #22c55e)'
  if (grade === 'B') return 'var(--accent)'
  if (grade === 'C') return 'var(--warning, #f0a500)'
  if (grade === 'D' || grade === 'F') return 'var(--danger, #e53935)'
  return 'var(--text-muted)'
}
</script>

<template>
  <DashboardCard title="Executive Summary" icon="fas fa-chart-pie" card-id="executive">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:.6rem">

      <!-- Health Score -->
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:.5rem;border-radius:6px;border:1px solid var(--border);background:var(--surface-2)">
        <div style="font-size:1.8rem;font-weight:700;line-height:1" :style="`color:${gradeColor(scoreGrade)}`">
          {{ scoreGrade }}
        </div>
        <div style="font-size:.62rem;color:var(--text-muted);letter-spacing:.08em;text-transform:uppercase;margin-top:.2rem">
          Health
          <span v-if="scoreValue !== null" style="opacity:.7"> · {{ scoreValue }}%</span>
        </div>
      </div>

      <!-- Active Alerts -->
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:.5rem;border-radius:6px;border:1px solid var(--border);background:var(--surface-2)">
        <div
          style="font-size:1.8rem;font-weight:700;line-height:1"
          :style="`color:${activeAlerts > 0 ? 'var(--danger, #e53935)' : 'var(--success, #22c55e)'}`"
        >
          {{ activeAlerts }}
        </div>
        <div style="font-size:.62rem;color:var(--text-muted);letter-spacing:.08em;text-transform:uppercase;margin-top:.2rem">Alerts</div>
      </div>

      <!-- Agents -->
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:.5rem;border-radius:6px;border:1px solid var(--border);background:var(--surface-2)">
        <div style="font-size:1.8rem;font-weight:700;line-height:1;color:var(--accent)">
          {{ onlineAgents }}<span style="font-size:.9rem;opacity:.5">/{{ agents.length }}</span>
        </div>
        <div style="font-size:.62rem;color:var(--text-muted);letter-spacing:.08em;text-transform:uppercase;margin-top:.2rem">Agents</div>
      </div>

      <!-- Uptime -->
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:.5rem;border-radius:6px;border:1px solid var(--border);background:var(--surface-2)">
        <div style="font-size:.95rem;font-weight:700;line-height:1;color:var(--text);text-align:center">
          {{ dashboard.live.uptime || '—' }}
        </div>
        <div style="font-size:.62rem;color:var(--text-muted);letter-spacing:.08em;text-transform:uppercase;margin-top:.2rem">Uptime</div>
      </div>

    </div>

    <!-- Category breakdown from health score -->
    <div v-if="healthScore?.categories?.length" style="margin-top:.75rem">
      <div
        v-for="cat in healthScore.categories"
        :key="cat.name"
        class="row"
        style="font-size:.72rem"
      >
        <span class="row-label" style="text-transform:capitalize">{{ cat.name }}</span>
        <span class="row-val" :style="`color:${gradeColor(cat.grade)}`">{{ cat.grade }}</span>
      </div>
    </div>
  </DashboardCard>
</template>
