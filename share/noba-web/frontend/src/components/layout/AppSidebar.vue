<script setup>
import { ref, inject } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import { useDashboardStore } from '../../stores/dashboard'
import { useLicenseStore } from '../../stores/license'
import { useSettingsStore } from '../../stores/settings'

const route = useRoute()
const authStore = useAuthStore()
const dashboardStore = useDashboardStore()
const settingsStore = useSettingsStore()
const licenseStore = useLicenseStore()

const sidebarCollapsed = inject('sidebarCollapsed')
const toggleSidebar = inject('toggleSidebar')

const settingsExpanded = ref(false)

const settingsTabs = [
  { tab: 'general', label: 'General', adminOnly: false },
  { tab: 'visibility', label: 'Visibility', adminOnly: false },
  { tab: 'integrations', label: 'Integrations', adminOnly: false },
  { tab: 'backup', label: 'Backup', adminOnly: false },
  { tab: 'users', label: 'Users', adminOnly: true },
  { tab: 'alerts', label: 'Alerts', adminOnly: false },
  { tab: 'statuspage', label: 'Status Page', adminOnly: true },
  { tab: 'shortcuts', label: 'Shortcuts', adminOnly: false },
  { tab: 'plugins', label: 'Plugins', adminOnly: true },
  // ── Enterprise ──────────────────────────────
  { tab: '_enterprise', label: 'Enterprise', adminOnly: true, divider: true },
  { tab: 'saml', label: 'SAML SSO', adminOnly: true, enterprise: true },
  { tab: 'scim', label: 'SCIM', adminOnly: true, enterprise: true },
  { tab: 'webauthn', label: 'WebAuthn', adminOnly: true, enterprise: true },
  { tab: 'database', label: 'Database', adminOnly: true, enterprise: true },
  { tab: 'branding', label: 'Branding', adminOnly: true, enterprise: true },
  { tab: 'license',  label: 'License',  adminOnly: true },
]

function isSettingsActive() {
  return route.path.startsWith('/settings')
}

function onSettingsClick() {
  settingsExpanded.value = !settingsExpanded.value
}

function agentCounts() {
  const all = dashboardStore.live.agents || []
  const online = all.filter(a => a.online).length
  return { total: all.length, online }
}
</script>

<template>
  <aside class="app-sidebar" :class="{ 'mobile-open': !sidebarCollapsed }">
    <div class="app-sidebar-logo">
      <div class="logo-mark" aria-hidden="true">
        <img v-if="settingsStore.branding.logoUrl"
             :src="settingsStore.branding.logoUrl"
             style="width:24px;height:24px;object-fit:contain"
             alt="Logo">
        <i v-else class="fas fa-terminal"></i>
      </div>
      <div class="logo-text">
        <div class="logo-name">
          {{ settingsStore.branding.orgName || 'NOBA' }}
          <span class="logo-edition">Enterprise</span>
        </div>
        <div class="logo-tagline">Command Center</div>
      </div>
    </div>

    <nav class="app-sidebar-nav">
      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'dashboard' }" to="/dashboard">
        <i class="fas fa-th-large nav-icon"></i>
        <span class="nav-label">Dashboard</span>
      </router-link>

      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'agents' }" to="/agents">
        <i class="fas fa-robot nav-icon"></i>
        <span class="nav-label">Agents</span>
        <span v-if="agentCounts().total > 0"
              class="nav-badge" :class="{ 'nav-badge--warn': agentCounts().online < agentCounts().total }">
          {{ agentCounts().online }}/{{ agentCounts().total }}
        </span>
      </router-link>

      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'monitoring' }" to="/monitoring">
        <i class="fas fa-chart-line nav-icon"></i>
        <span class="nav-label">Monitoring</span>
      </router-link>

      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'infrastructure' }" to="/infrastructure">
        <i class="fas fa-server nav-icon"></i>
        <span class="nav-label">Infrastructure</span>
      </router-link>

      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'automations' }" to="/automations">
        <i class="fas fa-bolt nav-icon"></i>
        <span class="nav-label">Automations</span>
      </router-link>

      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'logs' }" to="/logs">
        <i class="fas fa-scroll nav-icon"></i>
        <span class="nav-label">Logs</span>
      </router-link>

      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'healing' }" to="/healing">
        <i class="fas fa-heartbeat nav-icon"></i>
        <span class="nav-label">Healing</span>
      </router-link>

      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'security' }" to="/security">
        <i class="fas fa-shield-alt nav-icon"></i>
        <span class="nav-label">Security</span>
      </router-link>

      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'remote' || route.name === 'remote-desktop' }" to="/remote">
        <i class="fas fa-desktop nav-icon"></i>
        <span class="nav-label">Remote</span>
      </router-link>

      <a
        v-if="authStore.isAdmin"
        class="sidebar-nav-item"
        href="/api/docs"
        target="_blank"
        title="API Documentation"
      >
        <i class="fas fa-book nav-icon"></i>
        <span class="nav-label">API Docs</span>
        <i class="fas fa-external-link-alt nav-label" style="font-size:9px;opacity:.3;margin-left:auto"></i>
      </a>

      <div class="sidebar-divider"></div>

      <div
        class="sidebar-nav-item"
        :class="{ active: isSettingsActive() }"
        @click="onSettingsClick"
      >
        <i class="fas fa-cog nav-icon"></i>
        <span class="nav-label">Settings</span>
        <i
          class="fas nav-label"
          :class="settingsExpanded ? 'fa-chevron-down' : 'fa-chevron-right'"
          style="font-size:9px;opacity:.4;margin-left:auto"
        ></i>
      </div>

      <div v-show="settingsExpanded" class="sidebar-sub-items">
        <template v-for="item in settingsTabs" :key="item.tab">
          <div
            v-if="item.divider && authStore.isAdmin"
            class="sidebar-sub-divider"
          >{{ item.label }}</div>
          <router-link
            v-else-if="!item.adminOnly || authStore.isAdmin"
            class="sidebar-sub-item"
            :class="{ active: route.path === `/settings/${item.tab}`, 'enterprise-locked': item.enterprise && !licenseStore.active }"
            :to="item.enterprise && !licenseStore.active ? '/settings/license' : `/settings/${item.tab}`"
            :title="item.enterprise && !licenseStore.active ? 'Enterprise license required' : ''"
          ><i v-if="item.enterprise && !licenseStore.active" class="fas fa-lock" style="font-size:.5rem;opacity:.4;margin-right:.4rem"></i>{{ item.label }}</router-link>
        </template>
      </div>
    </nav>

    <div class="sidebar-user">
      <div class="sidebar-user-avatar">
        {{ (authStore.username || '?')[0].toUpperCase() }}
      </div>
      <div class="sidebar-user-info">
        <div class="sidebar-user-name">{{ authStore.username }}</div>
        <div class="sidebar-user-role">{{ authStore.userRole }}</div>
      </div>
      <button class="icon-btn" style="opacity:.4" title="Logout" @click="authStore.logout()">
        <i class="fas fa-sign-out-alt"></i>
      </button>
    </div>

    <div
      class="sidebar-backdrop"
      v-show="!sidebarCollapsed"
      @click="toggleSidebar()"
    ></div>
  </aside>
</template>
