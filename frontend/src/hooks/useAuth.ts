import { createContext, useContext } from 'react'
import type { User } from '../types'

export interface AuthContextValue {
  user:     User | null
  token:    string
  isAdmin:  boolean
  isLoading: boolean
}

export const AuthContext = createContext<AuthContextValue>({
  user: null, token: '', isAdmin: false, isLoading: true,
})

export function useAuth() { return useContext(AuthContext) }
