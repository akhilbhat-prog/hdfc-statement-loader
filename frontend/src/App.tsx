import { useState, useEffect, type ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthContext, type AuthContextValue } from './hooks/useAuth'
import { ToastProvider } from './components/ToastProvider'
import { setToken, getToken, apiFetch } from './api/client'
import type { User } from './types'

import { ReviewPage }    from './pages/Review'
import { ViewPage }      from './pages/View'
import { SharedPage }    from './pages/Shared'
import { RecurringPage } from './pages/Recurring'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser]        = useState<User | null>(null)
  const [token, setTokenState] = useState(getToken())
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const t = params.get('token')
    if (t) { setToken(t); setTokenState(t) }

    apiFetch<User>('/api/me')
      .then(u => setUser(u))
      .catch(() => { /* 401 redirects in apiFetch */ })
      .finally(() => setIsLoading(false))
  }, [])

  const value: AuthContextValue = {
    user, token, isAdmin: user?.role === 'admin', isLoading,
  }

  return <AuthContext value={value}>{children}</AuthContext>
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ToastProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/review"    element={<ReviewPage />} />
              <Route path="/view"      element={<ViewPage />} />
              <Route path="/shared"    element={<SharedPage />} />
              <Route path="/recurring" element={<RecurringPage />} />
              <Route path="/"          element={<Navigate to="/shared" replace />} />
              <Route path="*"          element={<Navigate to="/shared" replace />} />
            </Routes>
          </BrowserRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}
