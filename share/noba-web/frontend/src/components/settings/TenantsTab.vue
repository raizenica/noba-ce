<script setup>
import { ref, onMounted, computed } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import { useModalsStore } from '../../stores/modals'
import AppModal from '../ui/AppModal.vue'

const authStore = useAuthStore()
const { get, post, put, patch, del } = useApi()
const modals = useModalsStore()

// ── Tenant list ────────────────────────────────────────────────────────────
const tenants = ref([])
const loading = ref(false)
const actionMsg = ref('')

async function fetchTenants() {
  loading.value = true
  try {
    tenants.value = await get('/api/tenants')
  } catch { /* silent */ }
  finally { loading.value = false }
}

onMounted(() => { if (authStore.isAdmin) fetchTenants() })

function flash(msg) {
  actionMsg.value = msg
  setTimeout(() => { actionMsg.value = '' }, 3000)
}

// ── Create tenant ──────────────────────────────────────────────────────────
const showCreate = ref(false)
const newName = ref('')
const newSlug = ref('')
const createError = ref('')

function openCreate() {
  newName.value = ''
  newSlug.value = ''
  createError.value = ''
  showCreate.value = true
}

async function createTenant() {
  createError.value = ''
  if (!newName.value.trim()) { createError.value = 'Name is required'; return }
  try {
    await post('/api/tenants', { name: newName.value.trim(), slug: newSlug.value.trim() || undefined })
    showCreate.value = false
    flash(`Tenant "${newName.value}" created`)
    await fetchTenants()
  } catch (e) {
    createError.value = e.message || 'Create failed'
  }
}

// ── Delete tenant ──────────────────────────────────────────────────────────
async function confirmDelete(tenant) {
  if (!await modals.confirm(`Delete tenant "${tenant.name}"? This cannot be undone.`)) return
  try {
    await del(`/api/tenants/${tenant.id}`)
    flash(`Tenant "${tenant.name}" deleted`)
    if (selectedTenant.value?.id === tenant.id) selectedTenant.value = null
    await fetchTenants()
  } catch (e) {
    flash('Delete failed: ' + (e.message || 'Unknown error'))
  }
}

// ── Member panel ───────────────────────────────────────────────────────────
const selectedTenant = ref(null)
const members = ref([])
const membersLoading = ref(false)

async function selectTenant(t) {
  if (selectedTenant.value?.id === t.id) { selectedTenant.value = null; return }
  selectedTenant.value = t
  await Promise.all([fetchMembers(t.id), fetchQuotas(t.id)])
}

async function fetchMembers(tenantId) {
  membersLoading.value = true
  try {
    members.value = await get(`/api/tenants/${tenantId}/members`)
  } catch { /* silent */ }
  finally { membersLoading.value = false }
}

// Add member
const showAddMember = ref(false)
const newMemberUsername = ref('')
const newMemberRole = ref('viewer')
const addMemberError = ref('')

function openAddMember() {
  newMemberUsername.value = ''
  newMemberRole.value = 'viewer'
  addMemberError.value = ''
  showAddMember.value = true
}

async function addMember() {
  addMemberError.value = ''
  if (!newMemberUsername.value.trim()) { addMemberError.value = 'Username required'; return }
  try {
    await post(`/api/tenants/${selectedTenant.value.id}/members`, {
      username: newMemberUsername.value.trim(),
      role: newMemberRole.value,
    })
    showAddMember.value = false
    flash(`Added ${newMemberUsername.value} to ${selectedTenant.value.name}`)
    await fetchMembers(selectedTenant.value.id)
    await fetchTenants()
  } catch (e) {
    addMemberError.value = e.message || 'Add failed'
  }
}

// Update role
async function updateRole(member, newRole) {
  try {
    await patch(`/api/tenants/${selectedTenant.value.id}/members/${member.username}`, { role: newRole })
    flash(`${member.username} role updated to ${newRole}`)
    await fetchMembers(selectedTenant.value.id)
  } catch (e) {
    flash('Role update failed: ' + (e.message || 'Unknown'))
  }
}

// Remove member
async function confirmRemoveMember(member) {
  if (!await modals.confirm(`Remove ${member.username} from "${selectedTenant.value.name}"?`)) return
  try {
    await del(`/api/tenants/${selectedTenant.value.id}/members/${member.username}`)
    flash(`${member.username} removed`)
    await fetchMembers(selectedTenant.value.id)
    await fetchTenants()
  } catch (e) {
    flash('Remove failed: ' + (e.message || 'Unknown'))
  }
}

function roleBadgeClass(role) {
  if (role === 'admin') return 'ba'
  if (role === 'operator') return 'bw'
  return 'bn'
}

const totalMembers = computed(() => tenants.value.reduce((s, t) => s + (t.member_count || 0), 0))

// ── Quota management ───────────────────────────────────────────────────────
const quotaData = ref(null)          // { limits: {...}, counts: {...} }
const quotaEditing = ref(false)
const editedLimits = ref({})
const quotaMsg = ref('')

async function fetchQuotas(tenantId) {
  quotaData.value = null
  quotaEditing.value = false
  try {
    quotaData.value = await get(`/api/enterprise/tenants/${tenantId}/limits`)
  } catch { /* silent */ }
}

function startEditQuota() {
  editedLimits.value = { ...quotaData.value.limits }
  quotaEditing.value = true
}

async function saveQuotas() {
  try {
    await put(`/api/enterprise/tenants/${selectedTenant.value.id}/limits`, editedLimits.value)
    quotaMsg.value = 'Quotas saved'
    setTimeout(() => { quotaMsg.value = '' }, 2500)
    quotaEditing.value = false
    await fetchQuotas(selectedTenant.value.id)
  } catch (e) {
    quotaMsg.value = 'Save failed: ' + (e.message || 'Unknown')
  }
}

function quotaLabel(key) {
  return { max_api_keys: 'API Keys', max_automations: 'Automations', max_webhooks: 'Webhooks' }[key] || key
}

function countFor(limitKey) {
  const countKey = limitKey.slice(4) // strip "max_"
  return quotaData.value?.counts?.[countKey] ?? '—'
}
</script>

<template>
  <div>
    <!-- Admin gate -->
    <div v-if="!authStore.isAdmin" style="text-align:center;padding:3rem;color:var(--text-muted)">
      <i class="fas fa-lock" style="font-size:2rem;margin-bottom:.75rem;display:block;opacity:.4"></i>
      Admin role required to manage tenants.
    </div>

    <template v-else>
      <!-- Header stats -->
      <div class="s-section">
        <span class="s-label">Multi-Tenancy</span>
        <p class="help-text" style="margin-bottom:.75rem">
          Tenants provide isolated workspaces. Each user can belong to one tenant with a per-tenant role.
        </p>
        <div style="display:flex;gap:1.5rem;font-size:.82rem;color:var(--text-muted);margin-bottom:.75rem">
          <span><strong style="color:var(--text)">{{ tenants.length }}</strong> tenants</span>
          <span><strong style="color:var(--text)">{{ totalMembers }}</strong> total members</span>
        </div>

        <!-- Action message -->
        <div v-if="actionMsg" style="font-size:.82rem;color:var(--text-muted);margin-bottom:.75rem">{{ actionMsg }}</div>

        <!-- Tenant list -->
        <div style="display:flex;flex-direction:column;gap:.4rem;margin-bottom:.75rem">
          <div
            v-for="t in tenants"
            :key="t.id"
            style="border:1px solid var(--border);border-radius:4px;overflow:hidden"
            :style="selectedTenant?.id === t.id ? 'border-color:var(--primary)' : ''"
          >
            <!-- Tenant row -->
            <div
              style="display:flex;justify-content:space-between;align-items:center;padding:.5rem .75rem;background:var(--surface-2);cursor:pointer"
              @click="selectTenant(t)"
            >
              <div style="display:flex;align-items:center;gap:.6rem">
                <i class="fas fa-building" style="color:var(--text-muted);font-size:.85rem"></i>
                <span style="font-weight:500">{{ t.name }}</span>
                <code style="font-size:.75rem;color:var(--text-muted);background:var(--surface);padding:.1rem .3rem;border-radius:3px">{{ t.slug }}</code>
                <span v-if="t.disabled" class="badge bn" style="font-size:.7rem">disabled</span>
              </div>
              <div style="display:flex;align-items:center;gap:.75rem">
                <span style="font-size:.78rem;color:var(--text-muted)">
                  <i class="fas fa-users" style="margin-right:.3rem"></i>{{ t.member_count || 0 }}
                </span>
                <button
                  v-if="t.id !== 'default'"
                  class="btn btn-xs btn-danger"
                  @click.stop="confirmDelete(t)"
                  :aria-label="'Delete tenant ' + t.name"
                >
                  <i class="fas fa-trash"></i>
                </button>
                <i class="fas" :class="selectedTenant?.id === t.id ? 'fa-chevron-up' : 'fa-chevron-down'"
                   style="font-size:.75rem;color:var(--text-muted)"></i>
              </div>
            </div>

            <!-- Member panel (expanded) -->
            <div v-if="selectedTenant?.id === t.id" style="padding:.75rem;background:var(--surface);border-top:1px solid var(--border)">
              <div v-if="membersLoading" style="text-align:center;padding:1rem;color:var(--text-muted)">
                <i class="fas fa-spinner fa-spin"></i> Loading…
              </div>
              <template v-else>
                <!-- Member list -->
                <div style="display:flex;flex-direction:column;gap:.3rem;margin-bottom:.6rem">
                  <div
                    v-for="m in members" :key="m.username"
                    style="display:flex;justify-content:space-between;align-items:center;padding:.4rem .6rem;background:var(--surface-2);border:1px solid var(--border);border-radius:3px"
                  >
                    <div style="display:flex;align-items:center;gap:.5rem">
                      <i class="fas fa-user" style="color:var(--text-muted);font-size:.8rem"></i>
                      <span style="font-size:.88rem">{{ m.username }}</span>
                      <span class="badge" :class="roleBadgeClass(m.role)" style="font-size:.7rem">{{ m.role }}</span>
                    </div>
                    <div style="display:flex;gap:.4rem;align-items:center">
                      <select
                        class="field-input field-select"
                        style="font-size:.78rem;padding:.2rem .4rem;height:auto;max-width:100px"
                        :value="m.role"
                        @change="updateRole(m, $event.target.value)"
                      >
                        <option value="viewer">viewer</option>
                        <option value="operator">operator</option>
                        <option value="admin">admin</option>
                      </select>
                      <button class="btn btn-xs btn-danger" @click="confirmRemoveMember(m)" :aria-label="'Remove ' + m.username">
                        <i class="fas fa-times"></i>
                      </button>
                    </div>
                  </div>
                  <div v-if="members.length === 0" style="text-align:center;padding:1rem;color:var(--text-muted);font-size:.82rem">
                    No members yet.
                  </div>
                </div>

                <!-- Add member button -->
                <button class="btn btn-xs btn-primary" @click="openAddMember">
                  <i class="fas fa-plus"></i> Add Member
                </button>

                <!-- Quota section -->
                <div v-if="quotaData" style="margin-top:.75rem;border-top:1px solid var(--border);padding-top:.6rem">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.4rem">
                    <span style="font-size:.8rem;font-weight:600;color:var(--text-muted)">
                      <i class="fas fa-tachometer-alt" style="margin-right:.3rem"></i>Resource Quotas
                    </span>
                    <button v-if="!quotaEditing" class="btn btn-xs" @click="startEditQuota">
                      <i class="fas fa-edit"></i> Edit
                    </button>
                  </div>
                  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.4rem">
                    <template v-for="(val, key) in quotaData.limits" :key="key">
                      <div style="background:var(--surface-2);border:1px solid var(--border);border-radius:4px;padding:.4rem .6rem;font-size:.8rem">
                        <div style="color:var(--text-muted);margin-bottom:.2rem">{{ quotaLabel(key) }}</div>
                        <template v-if="!quotaEditing">
                          <span style="font-weight:600">{{ countFor(key) }}</span>
                          <span style="color:var(--text-muted)"> / {{ val === 0 ? '∞' : val }}</span>
                        </template>
                        <input v-else v-model.number="editedLimits[key]" type="number" min="0"
                          style="width:100%;font-size:.8rem;padding:.15rem .3rem" placeholder="0=∞" />
                      </div>
                    </template>
                  </div>
                  <div v-if="quotaEditing" style="display:flex;gap:.4rem;margin-top:.4rem">
                    <button class="btn btn-xs btn-primary" @click="saveQuotas">
                      <i class="fas fa-check"></i> Save
                    </button>
                    <button class="btn btn-xs" @click="quotaEditing=false">Cancel</button>
                  </div>
                  <div v-if="quotaMsg" style="font-size:.78rem;color:var(--text-muted);margin-top:.3rem">{{ quotaMsg }}</div>
                </div>
              </template>
            </div>
          </div>

          <div v-if="tenants.length === 0 && !loading" style="text-align:center;padding:2rem;background:var(--surface);border:1px dashed var(--border);border-radius:6px;color:var(--text-muted)">
            <i class="fas fa-building" style="font-size:2rem;display:block;margin-bottom:.75rem;opacity:.3"></i>
            No tenants yet.
          </div>
        </div>

        <!-- Toolbar -->
        <div style="display:flex;gap:.5rem">
          <button class="btn btn-sm" @click="fetchTenants">
            <i class="fas fa-sync" :class="loading ? 'fa-spin' : ''"></i> Refresh
          </button>
          <button class="btn btn-sm btn-primary" @click="openCreate">
            <i class="fas fa-plus"></i> New Tenant
          </button>
        </div>
      </div>

      <!-- Create Tenant Modal -->
      <AppModal :show="showCreate" title="Create Tenant" @close="showCreate = false">
        <div style="padding:1rem;display:flex;flex-direction:column;gap:.75rem">
          <div>
            <label class="field-label">Name <span style="color:var(--danger)">*</span></label>
            <input class="field-input" type="text" v-model="newName" placeholder="Acme Corp" @keyup.enter="createTenant">
          </div>
          <div>
            <label class="field-label">Slug <span style="color:var(--text-muted);font-size:.8rem">(optional — auto-generated)</span></label>
            <input class="field-input" type="text" v-model="newSlug" placeholder="acme-corp" @keyup.enter="createTenant">
          </div>
          <div v-if="createError" style="color:var(--danger);font-size:.82rem">{{ createError }}</div>
        </div>
        <template #footer>
          <button class="btn btn-sm" @click="showCreate = false">Cancel</button>
          <button class="btn btn-sm btn-primary" @click="createTenant">
            <i class="fas fa-check"></i> Create
          </button>
        </template>
      </AppModal>

      <!-- Add Member Modal -->
      <AppModal :show="showAddMember" :title="`Add member — ${selectedTenant?.name}`" @close="showAddMember = false">
        <div style="padding:1rem;display:flex;flex-direction:column;gap:.75rem">
          <div>
            <label class="field-label">Username <span style="color:var(--danger)">*</span></label>
            <input class="field-input" type="text" v-model="newMemberUsername" placeholder="alice" @keyup.enter="addMember">
          </div>
          <div>
            <label class="field-label">Role</label>
            <select class="field-input field-select" v-model="newMemberRole" style="max-width:160px">
              <option value="viewer">viewer</option>
              <option value="operator">operator</option>
              <option value="admin">admin</option>
            </select>
          </div>
          <div v-if="addMemberError" style="color:var(--danger);font-size:.82rem">{{ addMemberError }}</div>
        </div>
        <template #footer>
          <button class="btn btn-sm" @click="showAddMember = false">Cancel</button>
          <button class="btn btn-sm btn-primary" @click="addMember">
            <i class="fas fa-plus"></i> Add
          </button>
        </template>
      </AppModal>
    </template>
  </div>
</template>
