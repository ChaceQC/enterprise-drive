import { useState, type FormEvent } from 'react'

import { useAuth } from '../../app/useAuth'

export function LoginForm() {
  const { error, isPending, login } = useAuth()
  const [tenantSlug, setTenantSlug] = useState('default')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    try {
      await login({
        password,
        tenant_slug: tenantSlug,
        username,
      })
    } catch {
      // AuthProvider exposes the normalized error for the form to render.
    }
  }

  return (
    <form className="login-form" onSubmit={handleSubmit}>
      <div>
        <p className="eyebrow">企业网盘</p>
        <h1>登录</h1>
        <p className="muted">使用企业账号进入文件与管理工作区。</p>
      </div>

      <label>
        企业标识
        <input
          autoComplete="organization"
          disabled={isPending}
          name="tenant"
          onChange={(event) => setTenantSlug(event.target.value)}
          required
          value={tenantSlug}
        />
      </label>

      <label>
        用户名
        <input
          autoComplete="username"
          disabled={isPending}
          name="username"
          onChange={(event) => setUsername(event.target.value)}
          required
          value={username}
        />
      </label>

      <label>
        密码
        <input
          autoComplete="current-password"
          disabled={isPending}
          name="password"
          onChange={(event) => setPassword(event.target.value)}
          required
          type="password"
          value={password}
        />
      </label>

      {error ? (
        <div className="error-message" role="alert">
          <strong>{error.message}</strong>
          {error.requestId !== 'unknown' ? (
            <span>请求编号：{error.requestId}</span>
          ) : null}
        </div>
      ) : null}

      <button disabled={isPending} type="submit">
        {isPending ? '正在登录…' : '登录'}
      </button>
    </form>
  )
}
