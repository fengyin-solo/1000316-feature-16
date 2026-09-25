<template>
  <section class="page" data-module="generation">
    <header class="page-head">
      <div>
        <h2>发电量核算管理</h2>
        <p class="page-desc">维护发电记录，围绕记录编号、电站名称、统计日期、理论发电量做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button v-if="session.role === '核算岗'" class="btn primary" type="button" @click="openCreate">登记发电记录</button>
        <button class="btn" type="button" @click="exportRows">导出发电量核算清单</button>
      </div>
    </header>

    <p class="role-hint">{{ roleHint }}</p>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>记录编号</span>
        <input v-model="filters.keyword" placeholder="按记录编号检索" />
      </label>
      <label class="filter-item">
        <span>记录状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>争议说明</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td><span class="status-tag" :class="statusClass(row)">{{ row.status ?? '—' }}</span></td>
          <td>{{ row['争议说明'] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">查看详情</button>
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!availableActions(row).length && session.role !== '值班人'">—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无发电量核算数据，可先登记发电记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条发电量核算记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="createVisible" class="modal-mask" @click.self="createVisible = false">
      <div class="modal-card">
        <h3>登记发电记录</h3>
        <form class="form-grid" @submit.prevent="submitCreate">
          <label v-for="field in createFields" :key="field.name">
            <span>{{ field.name }}{{ field.required ? '（必填）' : '' }}</span>
            <input v-model="createForm[field.name]" :placeholder="field.required ? '必填' : '选填'" />
          </label>
          <div class="modal-actions">
            <button class="btn ghost" type="button" @click="createVisible = false">取消</button>
            <button class="btn primary" type="submit">提交登记</button>
          </div>
        </form>
      </div>
    </div>

    <div v-if="disputeTarget" class="modal-mask" @click.self="disputeTarget = null">
      <div class="modal-card">
        <h3>标记争议：{{ disputeTarget['记录编号'] }}</h3>
        <textarea v-model="disputeNote" placeholder="请填写争议说明，说明会同步到记录详情，记录保留在待处理中"></textarea>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="disputeTarget = null">取消</button>
          <button class="btn primary" type="button" @click="submitDispute">确认标记</button>
        </div>
      </div>
    </div>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal-card">
        <h3>记录详情：{{ detail['记录编号'] }}</h3>
        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd>{{ detail[field] ?? '—' }}</dd>
          </template>
        </dl>
        <h3>流转记录</h3>
        <ul class="history-list">
          <li v-for="(item, index) in detailHistory" :key="index">
            {{ item['时间'] ?? '—' }} · {{ item['操作人'] ?? '—' }}（{{ item['角色'] ?? '—' }}）{{ item['动作'] ?? '' }}
            <template v-if="item['说明']">：{{ item['说明'] }}</template>
          </li>
          <li v-if="!detailHistory.length">暂无流转记录</li>
        </ul>
        <div class="modal-actions">
          <button class="btn" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore, type OperatorRole } from '@/stores/session'

type Row = Record<string, string | number | boolean | null | undefined>
type Detail = Record<string, unknown>
type HistoryItem = Record<string, string | undefined>

const ENDPOINT = '/api/generation'
const columns = ["记录编号", "电站名称", "统计日期", "理论发电量", "实际发电量", "等效利用小时", "弃光电量", "记录状态"]
const actions = ["提交核算", "复核确认", "标记争议"]
const statuses = ["待核算", "已核算", "已复核", "有争议"]
const stats = [{"label": "本月发电量", "value": 0}, {"label": "等效小时均值", "value": 0}, {"label": "弃光电量合计", "value": 0}]
const detailFields = [...columns, "当前状态", "登记人", "登记时间", "核算人", "核算时间", "复核人", "复核时间", "争议说明", "争议标记人", "争议时间"]
const createFields = [
  { name: "记录编号", required: true },
  { name: "电站名称", required: true },
  { name: "统计日期", required: true },
  { name: "理论发电量", required: false },
  { name: "实际发电量", required: false },
  { name: "等效利用小时", required: false },
  { name: "弃光电量", required: false },
]

// 与后端一致的职责分流口径：核算岗提交核算，复核岗复核确认/标记争议，值班人只读。
const ACTION_RULES: Record<string, { roles: OperatorRole[]; from: string[] }> = {
  提交核算: { roles: ['核算岗'], from: ['待核算', '有争议'] },
  复核确认: { roles: ['复核岗'], from: ['已核算'] },
  标记争议: { roles: ['复核岗'], from: ['已核算'] },
}

const session = useSessionStore()

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref({ keyword: '', status: '' })
const createVisible = ref(false)
const createForm = ref<Record<string, string>>({})
const disputeTarget = ref<Row | null>(null)
const disputeNote = ref('')
const detail = ref<Detail | null>(null)

const roleHint = computed(() => {
  if (session.role === '核算岗') return '当前岗位：核算岗 —— 可登记发电记录、提交核算；复核确认需复核岗处理。'
  if (session.role === '复核岗') return '当前岗位：复核岗 —— 可复核确认或标记争议（需填争议说明）；不能提交核算。'
  return '当前岗位：值班人 —— 只读查看全部记录，不能提交或复核。'
})

const detailHistory = computed<HistoryItem[]>(() => {
  const value = detail.value?.['流转记录']
  return Array.isArray(value) ? (value as HistoryItem[]) : []
})

function statusClass(row: Row) {
  if (row.status === '已复核') return 'done'
  if (row.status === '有争议') return 'disputed'
  return 'pending'
}

function availableActions(row: Row): string[] {
  if (session.role === '值班人') return []
  return actions.filter((action) => {
    const rule = ACTION_RULES[action]
    return rule.roles.includes(session.role) && rule.from.includes(String(row.status ?? ''))
  })
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  createForm.value = {}
  createVisible.value = true
}

async function submitCreate() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = (await response.json()) as { ok: boolean; message: string }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '发电记录登记未生效，请稍后重试')
    }
    noticeMessage.value = payload.message
    createVisible.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发电记录登记失败'
  }
}

function runAction(action: string, row: Row) {
  if (action === '标记争议') {
    disputeTarget.value = row
    disputeNote.value = ''
    return
  }
  void submitAction(action, row)
}

async function submitDispute() {
  const target = disputeTarget.value
  if (!target) return
  if (!disputeNote.value.trim()) {
    errorMessage.value = '标记争议必须填写争议说明'
    return
  }
  await submitAction('标记争议', target, disputeNote.value.trim())
  disputeTarget.value = null
}

async function submitAction(action: string, row: Row, remark = '') {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action }, remark }),
    })
    const payload = (await response.json()) as { ok: boolean; message: string }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '发电量核算动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发电量核算操作失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('发电记录详情读取失败')
    }
    const payload = (await response.json()) as Detail
    payload['当前状态'] = payload['status']
    detail.value = payload
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发电记录详情读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword) query.set('keyword', filters.value.keyword)
  if (filters.value.status) query.set('status', filters.value.status)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('发电记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发电量核算列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.notice-text { color: #047857; }
.filter-item select { border: 1px solid var(--border); border-radius: 6px; padding: 4px 8px; }
</style>
