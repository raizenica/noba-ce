<script setup>
import { ref } from 'vue'
import { useAuthStore } from '../stores/auth'

import ServiceMapTab    from '../components/infrastructure/ServiceMapTab.vue'
import ServiceList      from '../components/infrastructure/ServiceList.vue'
import TopologyTab      from '../components/infrastructure/TopologyTab.vue'
import K8sBrowser       from '../components/infrastructure/K8sBrowser.vue'
import TailscaleTab     from '../components/infrastructure/TailscaleTab.vue'
import CrossSiteSyncTab from '../components/infrastructure/CrossSiteSyncTab.vue'
import ConfigDrift      from '../components/infrastructure/ConfigDrift.vue'
import ExportTab        from '../components/infrastructure/ExportTab.vue'
import TrafficTab       from '../components/infrastructure/TrafficTab.vue'
import NetworkDevices   from '../components/infrastructure/NetworkDevices.vue'
import PredictionsTab   from '../components/infrastructure/PredictionsTab.vue'

const authStore = useAuthStore()

const activeTab = ref('servicemap')

const serviceMapRef = ref(null)
const topologyRef   = ref(null)
const syncRef       = ref(null)
const trafficRef    = ref(null)
const predictRef    = ref(null)

function setTab(tab) {
  activeTab.value = tab
  if (tab === 'servicemap')  serviceMapRef.value?.fetchServiceMap()
  if (tab === 'topology')    topologyRef.value?.fetchTopology()
  if (tab === 'sync')        syncRef.value?.fetchSyncStatus()
  if (tab === 'traffic')     trafficRef.value?.fetchNetworkStats()
  if (tab === 'predictions') { predictRef.value?.fetchPredictions(); predictRef.value?.fetchPredictHealth() }
}
</script>

<template>
  <div style="padding:1rem">
    <h2 style="margin-bottom:1rem">
      <i class="fas fa-server" style="margin-right:.5rem"></i> Infrastructure
    </h2>

    <!-- Tab bar -->
    <div class="tab-bar" style="margin-bottom:1rem;display:flex;flex-wrap:wrap;gap:.3rem">
      <button
        class="btn btn-xs"
        :class="activeTab === 'servicemap' ? 'btn-primary' : ''"
        @click="setTab('servicemap')"
      >Service Map</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'services' ? 'btn-primary' : ''"
        @click="setTab('services')"
      >Services</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'topology' ? 'btn-primary' : ''"
        @click="setTab('topology')"
      >Topology</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'k8s' ? 'btn-primary' : ''"
        @click="setTab('k8s')"
      >Kubernetes</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'tailscale' ? 'btn-primary' : ''"
        @click="setTab('tailscale')"
      >Tailscale</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'sync' ? 'btn-primary' : ''"
        @click="setTab('sync')"
      >Cross-Site Sync</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'drift' ? 'btn-primary' : ''"
        @click="setTab('drift')"
      >Config Drift</button>
      <button
        v-if="authStore.isOperator"
        class="btn btn-xs"
        :class="activeTab === 'export' ? 'btn-primary' : ''"
        @click="setTab('export')"
      >Export</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'traffic' ? 'btn-primary' : ''"
        @click="setTab('traffic')"
      >
        <i class="fas fa-chart-area mr-sm"></i>Traffic
      </button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'networkmap' ? 'btn-primary' : ''"
        @click="setTab('networkmap')"
      >Network Map</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'predictions' ? 'btn-primary' : ''"
        @click="setTab('predictions')"
      >
        <i class="fas fa-chart-line mr-sm"></i>Predictions
      </button>
    </div>

    <!-- Tab contents -->
    <div v-show="activeTab === 'servicemap'">
      <ServiceMapTab ref="serviceMapRef" />
    </div>

    <div v-show="activeTab === 'services'">
      <ServiceList />
    </div>

    <div v-show="activeTab === 'topology'">
      <TopologyTab ref="topologyRef" />
    </div>

    <div v-show="activeTab === 'k8s'">
      <K8sBrowser />
    </div>

    <div v-show="activeTab === 'tailscale'">
      <TailscaleTab />
    </div>

    <div v-show="activeTab === 'sync'">
      <CrossSiteSyncTab ref="syncRef" />
    </div>

    <div v-show="activeTab === 'drift'">
      <ConfigDrift />
    </div>

    <div v-show="activeTab === 'export'">
      <ExportTab />
    </div>

    <div v-show="activeTab === 'traffic'">
      <TrafficTab ref="trafficRef" />
    </div>

    <div v-show="activeTab === 'networkmap'">
      <NetworkDevices />
    </div>

    <div v-show="activeTab === 'predictions'">
      <PredictionsTab ref="predictRef" />
    </div>
  </div>
</template>
