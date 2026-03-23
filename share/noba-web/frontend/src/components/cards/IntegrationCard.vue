<template>
  <DashboardCard :title="instance.id" :icon="template.icon || 'fas fa-plug'" :health="health">
    <div v-if="!data || !Object.keys(data).length" class="empty-msg">No data available</div>
    <template v-else>
      <div v-for="metric in template.metrics" :key="metric.key" class="row">
        <span class="row-label">{{ metric.label }}</span>

        <!-- Status badge -->
        <span v-if="metric.type === 'status'" class="row-val">
          <span :class="['badge', statusClass(data[metric.key])]">
            {{ data[metric.key] || 'unknown' }}
          </span>
        </span>

        <!-- Percent bar -->
        <span v-else-if="metric.type === 'percent_bar'" class="row-val">
          <div class="prog" style="flex:1">
            <div class="prog-track" :style="{ width: Math.min(data[metric.key]||0, 100) + '%',
              background: percentColor(data[metric.key]||0) }" />
          </div>
          <span class="prog-meta">{{ data[metric.key]||0 }}%</span>
        </span>

        <!-- Temperature -->
        <span v-else-if="metric.type === 'temperature'" class="row-val"
          :style="{ color: tempColor(data[metric.key]) }">
          {{ data[metric.key] != null ? data[metric.key] + '°C' : '—' }}
        </span>

        <!-- Age (time since) -->
        <span v-else-if="metric.type === 'age'" class="row-val">
          {{ formatAge(data[metric.key]) }}
        </span>

        <!-- Number -->
        <span v-else-if="metric.type === 'number'" class="row-val">
          {{ data[metric.key] != null ? data[metric.key] : '—' }}
        </span>

        <!-- Bytes -->
        <span v-else-if="metric.type === 'bytes'" class="row-val">
          {{ formatBytes(data[metric.key]) }}
        </span>

        <!-- Default -->
        <span v-else class="row-val">{{ data[metric.key] ?? '—' }}</span>
      </div>

      <!-- Site badge -->
      <div v-if="instance.site" class="row">
        <span class="row-label">Site</span>
        <span class="row-val"><span class="badge ba">{{ instance.site }}</span></span>
      </div>

      <!-- Health status -->
      <div v-if="instance.health_status && instance.health_status !== 'unknown'" class="row">
        <span class="row-label">Status</span>
        <span class="row-val">
          <span :class="['badge', statusClass(instance.health_status)]">{{ instance.health_status }}</span>
        </span>
      </div>
    </template>
  </DashboardCard>
</template>

<script setup>
import { computed } from 'vue'
import DashboardCard from './DashboardCard.vue'

const props = defineProps({
  instance: { type: Object, required: true },   // {id, category, platform, site, health_status, ...}
  template: { type: Object, required: true },    // {icon, metrics: [{key, label, type}]}
  data: { type: Object, default: () => ({}) },   // live metrics from collector
})

const health = computed(() => {
  const s = props.instance.health_status
  if (s === 'online') return 'ok'
  if (s === 'degraded') return 'warn'
  if (s === 'offline') return 'fail'
  return undefined
})

function statusClass(val) {
  if (!val) return 'ba'
  const v = String(val).toLowerCase()
  if (['online', 'healthy', 'ok', 'active', 'running'].includes(v)) return 'bs'
  if (['degraded', 'warning', 'slow'].includes(v)) return 'bw'
  if (['offline', 'error', 'failed', 'down', 'faulted'].includes(v)) return 'bd'
  return 'ba'
}

function percentColor(val) {
  if (val >= 90) return 'var(--danger)'
  if (val >= 75) return 'var(--warning)'
  return 'var(--accent)'
}

function tempColor(val) {
  if (val == null) return 'var(--text-muted)'
  if (val >= 80) return 'var(--danger)'
  if (val >= 60) return 'var(--warning)'
  return 'var(--success)'
}

function formatAge(val) {
  if (!val) return '—'
  const hours = typeof val === 'number' ? val : 0
  if (hours < 1) return 'just now'
  if (hours < 24) return `${Math.round(hours)}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function formatBytes(val) {
  if (val == null) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = val
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(1)} ${units[i]}`
}
</script>
