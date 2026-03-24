<script setup>
import { ref, computed } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useDashboardStore } from '../stores/dashboard'

import SystemLogTab      from '../components/logs/SystemLogTab.vue'
import CommandHistoryTab from '../components/logs/CommandHistoryTab.vue'
import AuditLogTab       from '../components/logs/AuditLogTab.vue'
import JournalTab        from '../components/logs/JournalTab.vue'
import LiveStreamTab     from '../components/logs/LiveStreamTab.vue'

const authStore = useAuthStore()
const dashStore = useDashboardStore()

const agents = computed(() => dashStore.live.agents || [])

const activeTab = ref('syslog')

const syslogRef  = ref(null)
const historyRef = ref(null)
const auditRef   = ref(null)
const journalRef = ref(null)

function setTab(tab) {
  activeTab.value = tab
  if (tab === 'syslog')   syslogRef.value?.fetchLog()
  if (tab === 'history')  historyRef.value?.fetchCommandHistory()
  if (tab === 'audit')    auditRef.value?.fetchAuditLog()
  if (tab === 'journal')  { journalRef.value?.fetchJournalUnits(); journalRef.value?.fetchJournal() }
}
</script>

<template>
  <div>
    <!-- Page header -->
    <h2 style="margin-bottom:1rem">
      <i class="fas fa-scroll" style="margin-right:.5rem"></i>Logs
    </h2>

    <!-- Tab bar -->
    <div class="tab-bar" style="margin-bottom:1rem;display:flex;flex-wrap:wrap;gap:.3rem">
      <button
        class="btn btn-xs"
        :class="{ 'btn-primary': activeTab === 'syslog' }"
        @click="setTab('syslog')"
      >System Log</button>
      <button
        class="btn btn-xs"
        :class="{ 'btn-primary': activeTab === 'history' }"
        @click="setTab('history')"
      >Command History</button>
      <button
        class="btn btn-xs"
        :class="{ 'btn-primary': activeTab === 'audit' }"
        @click="setTab('audit')"
      >Audit Log</button>
      <button
        class="btn btn-xs"
        :class="{ 'btn-primary': activeTab === 'journal' }"
        @click="setTab('journal')"
      >Journal</button>
      <button
        v-if="agents.length > 0 && authStore.isAdmin"
        class="btn btn-xs"
        :class="{ 'btn-primary': activeTab === 'stream' }"
        @click="setTab('stream')"
      >
        <i class="fas fa-satellite-dish" style="margin-right:.3rem"></i>Live Stream
      </button>
    </div>

    <!-- Tab contents -->
    <div v-show="activeTab === 'syslog'">
      <SystemLogTab ref="syslogRef" />
    </div>

    <div v-show="activeTab === 'history'">
      <CommandHistoryTab ref="historyRef" />
    </div>

    <div v-show="activeTab === 'audit'">
      <AuditLogTab ref="auditRef" />
    </div>

    <div v-show="activeTab === 'journal'">
      <JournalTab ref="journalRef" />
    </div>

    <div v-show="activeTab === 'stream'">
      <LiveStreamTab />
    </div>
  </div>
</template>
