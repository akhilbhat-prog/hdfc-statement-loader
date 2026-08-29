import { createContext, useContext } from 'react'

export interface Toast {
  id:      string
  message: string
  type:    'success' | 'error' | 'info'
}

export interface ToastContextValue {
  toasts:   Toast[]
  toast:    (message: string, type?: Toast['type']) => void
  dismiss:  (id: string) => void
}

export const ToastContext = createContext<ToastContextValue>({
  toasts: [], toast: () => {}, dismiss: () => {},
})

export function useToast() { return useContext(ToastContext) }
