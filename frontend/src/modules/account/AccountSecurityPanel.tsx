import {
  KeyRound,
  Link2,
  MonitorSmartphone,
  ShieldCheck,
  Unlink,
} from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'

import {
  listBrowserSessions,
  revokeBrowserSession,
} from '../../api/auth'
import { IdentityService } from '../../api/generated'
import { executeApi } from '../../api/runtime'
import {
  EmptyState,
  ErrorNotice,
  IconButton,
  LoadingBlock,
  StatusBadge,
} from '../../components/ui'
import { queryClient } from '../../app/query-client'
import { useAuth } from '../../app/useAuth'
import { PasswordChangeForm } from './PasswordChangeForm'

export function AccountSecurityPanel() {
  const { refresh } = useAuth()
  const sessions = useQuery({
    queryKey: ['browser-sessions'],
    queryFn: listBrowserSessions,
  })
  const links = useQuery({
    queryKey: ['identity-links'],
    queryFn: () => executeApi(() => IdentityService.listIdentityLinksApiV1AuthIdentityLinksGet()),
  })
  const providers = useQuery({
    queryKey: ['public-oidc-providers', 'default'],
    queryFn: () => executeApi(
      () => IdentityService.listPublicOidcProvidersApiV1AuthOidcProvidersGet({
        tenantSlug: 'default',
      }),
      { notifySessionExpired: false },
    ),
  })
  const revoke = useMutation({
    mutationFn: revokeBrowserSession,
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ['browser-sessions'] })
      if (result.current_session_revoked) {
        await refresh()
      }
    },
  })
  const unlink = useMutation({
    mutationFn: (linkId: string) => executeApi(
      () => IdentityService.unlinkIdentityApiV1AuthIdentityLinksLinkIdDelete({
        linkId,
      }),
    ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['identity-links'] }),
  })
  const bind = useMutation({
    mutationFn: (providerSlug: string) => executeApi(
      () => IdentityService.startOidcBindingApiV1AuthOidcProviderSlugBindStartPost({
        providerSlug,
        redirectPath: '/account',
      }),
    ),
    onSuccess: (result) => {
      window.location.assign(result.authorization_url)
    },
  })

  return (
    <div className="security-grid">
      <section className="security-card">
        <div className="section-heading">
          <div>
            <h2><KeyRound size={18} /> 密码与账号安全</h2>
            <p>修改密码会吊销全部旧浏览器和桌面会话。</p>
          </div>
        </div>
        <div className="security-card-body">
          <PasswordChangeForm onChanged={refresh} />
        </div>
      </section>

      <section className="security-card">
        <div className="section-heading">
          <div>
            <h2><MonitorSmartphone size={18} /> 浏览器会话</h2>
            <p>只显示当前账号的服务端 Cookie Session，不保存 bearer 凭据。</p>
          </div>
        </div>
        {sessions.isLoading ? <LoadingBlock /> : null}
        {sessions.error ? <ErrorNotice error={sessions.error} /> : null}
        {!sessions.isLoading && !sessions.error && !sessions.data?.items.length ? (
          <EmptyState
            description="当前没有可管理的浏览器会话。"
            icon={ShieldCheck}
            title="没有会话"
          />
        ) : null}
        <div className="compact-list security-list">
          {(sessions.data?.items ?? []).map((item) => (
            <article key={item.id}>
              <div>
                <div className="device-title">
                  <strong>{item.auth_method === 'oidc' ? 'OIDC 浏览器会话' : '本地浏览器会话'}</strong>
                  {item.current ? <StatusBadge tone="success">当前会话</StatusBadge> : null}
                </div>
                <p>{item.user_agent ?? '未知客户端'} · {item.ip ?? '未知 IP'}</p>
              </div>
              <IconButton
                disabled={revoke.isPending}
                icon={Unlink}
                label={item.current ? '吊销当前会话' : '吊销会话'}
                onClick={() => void revoke.mutateAsync(item.id)}
                tone="danger"
              />
            </article>
          ))}
        </div>
      </section>

      <section className="security-card">
        <div className="section-heading">
          <div>
            <h2><Link2 size={18} /> 企业单点登录绑定</h2>
            <p>绑定使用一次性 state、nonce 和 PKCE；页面只显示绑定状态。</p>
          </div>
        </div>
        {links.isLoading ? <LoadingBlock /> : null}
        {links.error ? <ErrorNotice error={links.error} /> : null}
        <div className="compact-list security-list">
          {(links.data?.items ?? []).map((link) => (
            <article key={link.id}>
              <div>
                <div className="device-title">
                  <strong>{link.provider_name}</strong>
                  <StatusBadge tone="success">已绑定</StatusBadge>
                </div>
                <p>{link.email ?? link.subject} · 最近登录 {link.last_login_at ?? '尚未登录'}</p>
              </div>
              <IconButton
                disabled={unlink.isPending}
                icon={Unlink}
                label="解除绑定"
                onClick={() => void unlink.mutateAsync(link.id)}
                tone="danger"
              />
            </article>
          ))}
        </div>
        <div className="identity-actions">
          {(providers.data?.items ?? []).map((provider) => (
            <button
              className="button secondary"
              disabled={bind.isPending}
              key={provider.slug}
              onClick={() => void bind.mutateAsync(provider.slug)}
              type="button"
            >
              绑定 {provider.name}
            </button>
          ))}
        </div>
      </section>
    </div>
  )
}
