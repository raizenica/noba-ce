<script setup>
import { ref, nextTick } from 'vue'

import SlaTable        from '../components/monitoring/SlaTable.vue'
import IncidentList    from '../components/monitoring/IncidentList.vue'
import EndpointTable   from '../components/monitoring/EndpointTable.vue'
import CorrelationTab  from '../components/monitoring/CorrelationTab.vue'
import GraylogTab      from '../components/monitoring/GraylogTab.vue'
import InfluxDbTab     from '../components/monitoring/InfluxDbTab.vue'
import CustomChartsTab from '../components/monitoring/CustomChartsTab.vue'

const activeTab = ref('sla')

const correlationRef  = ref(null)
const influxRef       = ref(null)
const customChartsRef = ref(null)

function setTab(tab) {
  activeTab.value = tab
  if (tab === 'correlation') {
    nextTick(() => correlationRef.value?.renderCorrelationChart())
  }
  if (tab === 'charts') {
    customChartsRef.value?.fetchAvailableMetrics()
    customChartsRef.value?.fetchDashboards()
    customChartsRef.value?.fetchMultiMetricChart()
  }
  if (tab === 'influxdb') {
    nextTick(() => influxRef.value?.renderInfluxChart())
  }
}
</script>

<template>
  <div>
    <!-- Page header -->
    <h2 style="margin-bottom:1rem">
      <i class="fas fa-chart-line" style="margin-right:.5rem;color:var(--accent)"></i>
      Monitoring
    </h2>

    <!-- Tab bar -->
    <div class="tab-bar" style="margin-bottom:1rem;display:flex;flex-wrap:wrap;gap:.3rem">
      <button
        class="btn btn-xs"
        :class="activeTab === 'sla' ? 'btn-primary' : ''"
        @click="setTab('sla')"
      >SLA</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'incidents' ? 'btn-primary' : ''"
        @click="setTab('incidents')"
      >Incidents</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'correlation' ? 'btn-primary' : ''"
        @click="setTab('correlation')"
      >Correlation</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'graylog' ? 'btn-primary' : ''"
        @click="setTab('graylog')"
      >Graylog</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'influxdb' ? 'btn-primary' : ''"
        @click="setTab('influxdb')"
      >InfluxDB</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'charts' ? 'btn-primary' : ''"
        @click="setTab('charts')"
      >Custom Charts</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'endpoints' ? 'btn-primary' : ''"
        @click="setTab('endpoints')"
      >Endpoints</button>
    </div>

    <!-- Tab contents -->
    <div v-show="activeTab === 'sla'">
      <SlaTable />
    </div>

    <div v-show="activeTab === 'incidents'">
      <IncidentList />
    </div>

    <div v-show="activeTab === 'correlation'">
      <CorrelationTab ref="correlationRef" />
    </div>

    <div v-show="activeTab === 'graylog'">
      <GraylogTab />
    </div>

    <div v-show="activeTab === 'influxdb'">
      <InfluxDbTab ref="influxRef" />
    </div>

    <div v-show="activeTab === 'charts'">
      <CustomChartsTab ref="customChartsRef" />
    </div>

    <div v-show="activeTab === 'endpoints'">
      <EndpointTable />
    </div>
  </div>
</template>
