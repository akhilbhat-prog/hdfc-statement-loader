import { useState, useEffect } from 'react'

export function useTheme() {
  const [isLight, setIsLight] = useState<boolean>(
    () => localStorage.getItem('theme') === 'light'
  )

  useEffect(() => {
    document.body.classList.toggle('light', isLight)
    localStorage.setItem('theme', isLight ? 'light' : 'dark')
  }, [isLight])

  return { isLight, toggle: () => setIsLight(v => !v) }
}
