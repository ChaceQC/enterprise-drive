import { useEffect, useState } from 'react'

import { useAuth } from '../../app/useAuth'

export function OidcCallbackPage() {
  const { refresh } = useAuth()
  const [message, setMessage] = useState('正在确认企业身份…')

  useEffect(() => {
    let active = true
    void refresh().then(() => {
      if (!active) return
      setMessage('身份确认完成，正在进入工作区…')
      window.location.replace('/')
    })
    return () => {
      active = false
    }
  }, [refresh])

  return (
    <main className="auth-loading">
      <span className="loading-dot" />
      <p>{message}</p>
    </main>
  )
}
