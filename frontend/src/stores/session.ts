import { defineStore } from 'pinia'

export const OPERATOR_ROLES = ['核算岗', '复核岗', '值班人'] as const
export type OperatorRole = (typeof OPERATOR_ROLES)[number]

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员',
    role: '值班人' as OperatorRole,
    shiftLabel: '白班 08:00-20:00',
    scope: '光伏电站智能运维平台',
  }),
  getters: {
    canOperate: (state) => state.role !== '值班人',
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setRole(role: OperatorRole) {
      this.role = role
    },
  },
})
