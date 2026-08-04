import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { useAuth } from '../../app/useAuth'
import { IdentityService } from '../../api/generated'
import { executeApi } from '../../api/runtime'

function lockedUntil(details: unknown): string | null {
  if (typeof details !== 'object' || details === null) return null
  const value = (details as Record<string, unknown>).locked_until
  if (typeof value !== 'string') return null
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? null : date.toLocaleString('zh-CN')
}

export function LoginForm() {
  const { error, isPending, login } = useAuth()
  const [tenantSlug, setTenantSlug] = useState('default')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [captchaToken, setCaptchaToken] = useState('')
  const [oidcPending, setOidcPending] = useState<string | null>(null)
  const providers = useQuery({
    queryKey: ['public-oidc-providers', tenantSlug],
    queryFn: () => executeApi(
      () => IdentityService.listPublicOidcProvidersApiV1AuthOidcProvidersGet({
        tenantSlug,
      }),
      { notifySessionExpired: false },
    ),
    enabled: Boolean(tenantSlug.trim()),
  })

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    try {
      await login({
        password,
        tenant_slug: tenantSlug,
        username,
        captcha_token: captchaToken || undefined,
      })
    } catch {
      // AuthProvider exposes the normalized error for the form to render.
    }
  }

  const startOidc = async (providerSlug: string) => {
    setOidcPending(providerSlug)
    try {
      const started = await executeApi(
        () => IdentityService.startOidcLoginApiV1AuthOidcProviderSlugStartGet({
          providerSlug,
          tenantSlug,
          redirectPath: '/auth/oidc/callback',
        }),
        { notifySessionExpired: false },
      )
      window.location.assign(started.authorization_url)
    } finally {
      setOidcPending(null)
    }
  }

  const lockTime = error?.code === 'ACCOUNT_LOCKED'
    ? lockedUntil(error.details)
    : null

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

      {error?.code === 'CAPTCHA_REQUIRED' ? (
        <label>
          验证码
          <input
            autoComplete="one-time-code"
            disabled={isPending}
            name="captcha"
            onChange={(event) => setCaptchaToken(event.target.value)}
            placeholder="输入验证码提供商返回的挑战令牌"
            required
            value={captchaToken}
          />
        </label>
      ) : null}

      {error ? (
        <div className="error-message" role="alert">
          <strong>{error.message}</strong>
          {lockTime ? <span>预计解锁时间：{lockTime}</span> : null}
          {error.requestId !== 'unknown' ? (
            <span>请求编号：{error.requestId}</span>
          ) : null}
        </div>
      ) : null}

      <button disabled={isPending} type="submit">
        {isPending ? '正在登录…' : '登录'}
      </button>

      {(providers.data?.items.length ?? 0) > 0 ? (
        <>
          <div className="login-divider"><span>或使用企业单点登录</span></div>
          <div className="oidc-provider-list">
            {providers.data?.items.map((provider) => (
              <button
                className="button secondary"
                disabled={oidcPending !== null}
                key={provider.slug}
                onClick={() => void startOidc(provider.slug)}
                type="button"
              >
                {oidcPending === provider.slug
                  ? '正在跳转…'
                  : `使用 ${provider.name} 登录`}
              </button>
            ))}
          </div>
        </>
      ) : null}
    </form>
  )
}
