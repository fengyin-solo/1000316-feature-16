import { defineStore } from 'pinia'

export interface AccountOption {
  operator: string
  role: string
  team: string
}

/** 演示用账号：按职责分流，核算岗与复核岗分属不同班组，值班人全局只读。 */
export const ACCOUNTS: AccountOption[] = [
  { operator: '张核算', role: '核算岗', team: '一值核算班' },
  { operator: '李复核', role: '复核岗', team: '运行复核组' },
  { operator: '王值班', role: '值班人', team: '调度值班台' },
]

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: ACCOUNTS[0].operator,
    role: ACCOUNTS[0].role,
    team: ACCOUNTS[0].team,
    shiftLabel: '白班 08:00-20:00',
    scope: '光伏电站智能运维平台',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
    isReadOnly: (state) => state.role === '值班人',
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    switchAccount(account: AccountOption) {
      this.operator = account.operator
      this.role = account.role
      this.team = account.team
    },
  },
})
