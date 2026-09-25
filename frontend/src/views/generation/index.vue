<template>
  <section class="page" data-module="generation">
    <header class="page-head">
      <div>
        <h2>发电量核算管理</h2>
        <p class="page-desc">核算岗提交核算、复核岗复核确认与标记争议、值班人只读查看；同一条记录同一时间只能由一个账号推进。</p>
      </div>
      <div class="page-actions">
        <button v-if="!session.isReadOnly" class="btn primary" type="button" @click="openCreate">登记发电记录</button>
        <button class="btn" type="button" @click="exportRows">导出发电量核算清单</button>
      </div>
    </header>

    <div class="role-bar">
      <span class="role-label">当前账号（演示可切换）：</span>
      <label v-for="account in accounts" :key="account.operator" class="role-option">
        <input
          type="radio"
          name="account"
          :value="account.operator"
          :checked="account.operator === session.operator"
          @change="switchAccount(account)"
        />
        <span>{{ account.operator }} · {{ account.role }}</span>
      </label>
      <span class="role-badge" :data-role="session.role">{{ session.role }} / {{ session.team }}</span>
      <span v-if="session.isReadOnly" class="readonly-tip">只读模式：可查看全部记录，不能提交或复核</span>
    </div>

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
          <th>处理锁定</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '记录状态'">
              <span class="status-tag" :data-status="String(row.status)">{{ row.status ?? '—' }}</span>
            </template>
            <template v-else-if="column === '争议说明'">
              <span :title="String(row[column] ?? '')">{{ row[column] ? truncate(String(row[column])) : '—' }}</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td>
            <span v-if="isLockActive(row)" class="lock-tag">{{ String(row.locked_by) }}处理中</span>
            <span v-else class="muted-text">未占用</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">查看详情</button>
            <template v-if="session.role === '核算岗'">
              <button
                v-if="['待核算', '有争议'].includes(String(row.status))"
                class="link"
                type="button"
                :disabled="isLockedByOther(row)"
                :title="isLockedByOther(row) ? '记录正被其他账号处理' : ''"
                @click="openSubmit(row)"
              >
                提交核算
              </button>
              <button
                v-if="isLockOwner(row)"
                class="link danger"
                type="button"
                @click="releaseRowLock(row)"
              >
                放弃处理
              </button>
            </template>
            <template v-else-if="session.role === '复核岗'">
              <button
                v-if="String(row.status) === '已核算'"
                class="link"
                type="button"
                :disabled="isLockedByOther(row)"
                :title="isLockedByOther(row) ? '记录正被其他账号处理' : ''"
                @click="confirmRow(row)"
              >
                复核确认
              </button>
              <button
                v-if="['待核算', '已核算'].includes(String(row.status))"
                class="link danger"
                type="button"
                :disabled="isLockedByOther(row)"
                :title="isLockedByOther(row) ? '记录正被其他账号处理' : ''"
                @click="openDispute(row)"
              >
                标记争议
              </button>
              <button
                v-if="isLockOwner(row)"
                class="link danger"
                type="button"
                @click="releaseRowLock(row)"
              >
                放弃处理
              </button>
            </template>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无发电量核算数据，可先登记发电记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条发电量核算记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 登记 / 提交核算 弹窗 -->
    <div v-if="formDialog.open" class="modal-mask" @click.self="cancelForm">
      <div class="modal">
        <h3>{{ formDialog.mode === 'create' ? '登记发电记录' : `提交核算 · ${String(formDialog.row?.['记录编号'] ?? '')}` }}</h3>
        <p v-if="formDialog.mode === 'submit' && String(formDialog.row?.status) === '有争议'" class="modal-tip warn">
          该记录存在争议：{{ String(formDialog.row?.['争议说明'] ?? '') }}，请核对后重新提交
        </p>
        <div class="form-grid">
          <label v-for="field in readonlyFields" :key="field" class="form-item">
            <span>{{ field }}</span>
            <input :value="String(formDialog.row?.[field] ?? '')" readonly />
          </label>
          <label v-for="field in formFields" :key="field.key" class="form-item">
            <span>{{ field.label }}<em v-if="field.required">*</em></span>
            <input v-model="formDialog.model[field.key]" :placeholder="`请输入${field.label}`" />
          </label>
        </div>
        <div class="modal-foot">
          <button class="btn" type="button" @click="cancelForm">取消</button>
          <button class="btn primary" type="button" @click="submitForm">
            {{ formDialog.mode === 'create' ? '登记' : '提交核算' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 标记争议 弹窗 -->
    <div v-if="disputeDialog.open" class="modal-mask" @click.self="cancelDispute">
      <div class="modal">
        <h3>标记争议 · {{ String(disputeDialog.row?.['记录编号'] ?? '') }}</h3>
        <p class="modal-tip">争议说明会同步到记录详情，记录保留在待处理列表，由核算岗重新核对。</p>
        <label class="form-item full">
          <span>争议说明<em>*</em></span>
          <textarea v-model="disputeDialog.note" rows="4" placeholder="请说明数据争议点，例如实际发电量与抄表值不一致"></textarea>
        </label>
        <div class="modal-foot">
          <button class="btn" type="button" @click="cancelDispute">取消</button>
          <button class="btn primary" type="button" @click="submitDispute">确认标记争议</button>
        </div>
      </div>
    </div>

    <!-- 记录详情 弹窗 -->
    <div v-if="detail.open" class="modal-mask" @click.self="detail.open = false">
      <div class="modal wide">
        <h3>发电记录详情 · {{ String(detail.entry?.['记录编号'] ?? '') }}</h3>
        <table class="detail-table">
          <tbody>
            <tr v-for="item in detailRows" :key="item.label">
              <th>{{ item.label }}</th>
              <td>{{ item.value }}</td>
            </tr>
          </tbody>
        </table>
        <section v-if="detailHistory.length" class="history-block">
          <h4>争议记录（{{ detailHistory.length }}）</h4>
          <ul>
            <li v-for="(item, index) in detailHistory" :key="index">
              <span class="history-note">{{ item['争议说明'] }}</span>
              <span class="history-meta">{{ item['标记人'] }} · {{ item['标记时间'] }}</span>
            </li>
          </ul>
        </section>
        <div class="modal-foot">
          <button class="btn primary" type="button" @click="detail.open = false">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { ACCOUNTS, useSessionStore, type AccountOption } from '@/stores/session'

type Row = Record<string, string | number | boolean | null | DisputeHistoryItem[]>

interface DisputeHistoryItem {
  争议说明: string
  标记人: string
  标记时间: string
}

interface FormField {
  key: string
  label: string
  required: boolean
}

const ENDPOINT = '/api/generation'
const session = useSessionStore()
const accounts = ACCOUNTS

const columns = ["记录编号", "电站名称", "统计日期", "理论发电量", "实际发电量", "等效利用小时", "弃光电量", "争议说明", "记录状态"]
const statuses = ["待核算", "已核算", "已复核", "有争议"]
// 统计卡片沿用旧口径，不改变弃光电量的既有统计方式
const stats = [{ "label": "本月发电量", "value": 0 }, { "label": "等效小时均值", "value": 0 }, { "label": "弃光电量合计", "value": 0 }]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = reactive<{ keyword: string; status: string }>({ keyword: '', status: '' })

const formDialog = reactive<{
  open: boolean
  mode: 'create' | 'submit'
  row: Row | null
  locked: boolean
  model: Record<string, string>
}>({
  open: false,
  mode: 'create',
  row: null,
  locked: false,
  model: {},
})

const disputeDialog = reactive<{ open: boolean; row: Row | null; locked: boolean; note: string }>({
  open: false,
  row: null,
  locked: false,
  note: '',
})

const detail = reactive<{ open: boolean; entry: Row | null }>({ open: false, entry: null })

const formFields = computed<FormField[]>(() =>
  formDialog.mode === 'create'
    ? [
        { key: '记录编号', label: '记录编号', required: true },
        { key: '电站名称', label: '电站名称', required: true },
        { key: '统计日期', label: '统计日期', required: true },
        { key: '理论发电量', label: '理论发电量', required: false },
      ]
    : [
        { key: '实际发电量', label: '实际发电量', required: true },
        { key: '等效利用小时', label: '等效利用小时', required: false },
        { key: '弃光电量', label: '弃光电量（沿用原口径）', required: false },
      ],
)

// 提交核算时只能填核算结果，记录基础信息保持只读，防止顺手改台账
const readonlyFields = computed<string[]>(() =>
  formDialog.mode === 'create'
    ? []
    : ['记录编号', '电站名称', '统计日期', '理论发电量'],
)

const detailRows = computed(() => {
  const entry = detail.entry ?? {}
  const fields = ["记录编号", "电站名称", "统计日期", "理论发电量", "实际发电量", "等效利用小时", "弃光电量", "争议说明", "status", "核算人", "核算时间", "复核人", "复核时间", "locked_by"]
  const labels: Record<string, string> = {
    status: '记录状态',
    locked_by: '当前处理锁定',
  }
  return fields
    .map((field) => ({ label: labels[field] ?? field, value: formatValue(entry[field]) }))
    .filter((item) => item.value !== '—')
})

const detailHistory = computed<DisputeHistoryItem[]>(() => {
  const history = detail.entry?.['争议记录']
  return Array.isArray(history) ? (history as DisputeHistoryItem[]) : []
})

function switchAccount(account: AccountOption) {
  session.switchAccount(account)
  errorMessage.value = ''
  void reload()
}

function truncate(text: string) {
  return text.length > 12 ? `${text.slice(0, 12)}…` : text
}

function formatValue(value: Row[keyof Row] | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

// 前端只做展示判断，真正的锁判定以后端为准；锁带 5 分钟超时，避免历史占锁永久挡住列表
function isLockActive(row: Row) {
  const lockedAt = Number(row.locked_at ?? 0)
  return Boolean(row.locked_by) && (!lockedAt || Date.now() / 1000 - lockedAt < 5 * 60)
}

function isLockOwner(row: Row) {
  return isLockActive(row) && String(row.locked_by) === session.operator
}

function isLockedByOther(row: Row) {
  return isLockActive(row) && String(row.locked_by) !== session.operator
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function identity() {
  return { operator: session.operator, role: session.role }
}

async function postAction(path: string, body: Record<string, unknown>) {
  const response = await request(path, {
    method: 'POST',
    body: JSON.stringify({ values: { ...identity(), ...body } }),
  })
  if (!response.ok) {
    throw new Error('发电量核算动作未生效，请稍后重试')
  }
  return (await response.json()) as { ok: boolean; message: string }
}

async function releaseLock(row: Row) {
  await request(`${ENDPOINT}/${String(row.id)}/lock`, {
    method: 'DELETE',
    body: JSON.stringify({ values: identity() }),
  })
}

function openCreate() {
  formDialog.open = true
  formDialog.mode = 'create'
  formDialog.row = null
  formDialog.locked = false
  formDialog.model = {}
}

async function openSubmit(row: Row) {
  errorMessage.value = ''
  // 打开填报表单前先占锁；占不到就不允许进入填报，避免两个人填完互相覆盖
  const result = await postAction(`${ENDPOINT}/${String(row.id)}/lock`, {})
  if (!result.ok) {
    errorMessage.value = result.message
    return
  }
  formDialog.open = true
  formDialog.mode = 'submit'
  formDialog.row = row
  formDialog.locked = true
  formDialog.model = {
    实际发电量: String(row['实际发电量'] ?? ''),
    等效利用小时: String(row['等效利用小时'] ?? ''),
    弃光电量: String(row['弃光电量'] ?? ''),
  }
}

async function submitForm() {
  errorMessage.value = ''
  const payload: Record<string, string> = {}
  for (const field of formFields.value) {
    const value = formDialog.model[field.key]?.trim() ?? ''
    if (field.required && !value) {
      errorMessage.value = `请填写${field.label}`
      return
    }
    if (value) payload[field.key] = value
  }
  try {
    if (formDialog.mode === 'create') {
      const result = await postAction(ENDPOINT, payload)
      if (!result.ok) {
        errorMessage.value = result.message
        return
      }
    } else {
      const result = await postAction(`${ENDPOINT}/${String(formDialog.row?.id)}/actions`, {
        action: '提交核算',
        ...payload,
      })
      if (!result.ok) {
        errorMessage.value = result.message
        // 占锁在但提交被拒（如字段问题）时保留锁，允许修正后重试；锁失效则关闭弹窗
        if (result.message.includes('处理中') || result.message.includes('只读') || result.message.includes('无权')) {
          formDialog.open = false
        } else {
          return
        }
      }
    }
    formDialog.open = false
    formDialog.locked = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发电量核算操作失败'
  }
}

async function cancelForm() {
  formDialog.open = false
  if (formDialog.mode === 'submit' && formDialog.locked && formDialog.row) {
    try {
      await releaseLock(formDialog.row)
    } catch {
      // 释放失败不阻塞界面，后端锁有超时保护
    }
  }
  formDialog.locked = false
  await reload()
}

async function openDispute(row: Row) {
  errorMessage.value = ''
  const result = await postAction(`${ENDPOINT}/${String(row.id)}/lock`, {})
  if (!result.ok) {
    errorMessage.value = result.message
    return
  }
  disputeDialog.open = true
  disputeDialog.row = row
  disputeDialog.locked = true
  disputeDialog.note = ''
}

async function submitDispute() {
  errorMessage.value = ''
  const note = disputeDialog.note.trim()
  if (!note) {
    errorMessage.value = '请填写争议说明'
    return
  }
  try {
    const result = await postAction(`${ENDPOINT}/${String(disputeDialog.row?.id)}/actions`, {
      action: '标记争议',
      争议说明: note,
    })
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    disputeDialog.open = false
    disputeDialog.locked = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '标记争议失败'
  }
}

async function cancelDispute() {
  disputeDialog.open = false
  if (disputeDialog.locked && disputeDialog.row) {
    try {
      await releaseLock(disputeDialog.row)
    } catch {
      // 释放失败不阻塞界面，后端锁有超时保护
    }
  }
  disputeDialog.locked = false
  await reload()
}

async function confirmRow(row: Row) {
  errorMessage.value = ''
  try {
    const result = await postAction(`${ENDPOINT}/${String(row.id)}/actions`, { action: '复核确认' })
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复核确认失败'
  }
}

async function releaseRowLock(row: Row) {
  errorMessage.value = ''
  try {
    await releaseLock(row)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '释放处理锁失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${String(row.id)}`)
    if (!response.ok) {
      throw new Error('发电记录详情读取失败')
    }
    detail.entry = (await response.json()) as Row
    detail.open = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发电记录详情读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(
    Object.entries({ keyword: filters.keyword, status: filters.status }).filter(([, value]) => value),
  ).toString()
  try {
    const response = await request(`${ENDPOINT}${query ? `?${query}` : ''}`)
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
.role-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 13px;
}
.role-label { color: var(--muted); }
.role-option { display: inline-flex; align-items: center; gap: 4px; cursor: pointer; }
.role-badge {
  margin-left: auto;
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  background: #eef2ff;
  color: #3730a3;
}
.role-badge[data-role='值班人'] { background: #f1f5f9; color: #475569; }
.readonly-tip { color: #b45309; font-size: 12px; }
.status-tag { border-radius: 4px; padding: 1px 8px; font-size: 12px; background: #f1f5f9; color: #475569; }
.status-tag[data-status='已核算'] { background: #e0f2fe; color: #075985; }
.status-tag[data-status='已复核'] { background: #dcfce7; color: #166534; }
.status-tag[data-status='有争议'] { background: #fef3c7; color: #92400e; }
.lock-tag { color: #b45309; font-size: 12px; }
.muted-text { color: var(--muted); font-size: 12px; }
.link:disabled { color: #94a3b8; cursor: not-allowed; }
.link.danger { color: #b42318; }

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}
.modal {
  width: 520px;
  max-height: 85vh;
  overflow-y: auto;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
}
.modal.wide { width: 640px; }
.modal h3 { margin: 0 0 12px; font-size: 16px; }
.modal-tip { color: var(--muted); font-size: 12px; margin: 0 0 12px; }
.modal-tip.warn { color: #b45309; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 14px; }
.form-item { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
.form-item.full { grid-column: 1 / -1; }
.form-item em { color: #b42318; font-style: normal; margin-left: 2px; }
.form-item input,
.form-item textarea,
.filter-item select {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
  color: #1f2937;
}
.form-item input[readonly] { background: #f8fafc; color: var(--muted); }
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.detail-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.detail-table th,
.detail-table td { border: 1px solid var(--border); padding: 6px 10px; text-align: left; }
.detail-table th { width: 130px; background: #f8fafc; color: var(--muted); font-weight: normal; }
.history-block { margin-top: 14px; }
.history-block h4 { margin: 0 0 8px; font-size: 13px; }
.history-block ul { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.history-note { display: block; }
.history-meta { color: var(--muted); font-size: 12px; }
</style>
