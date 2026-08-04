import {
  Laptop,
  RefreshCw,
  ShieldCheck,
  Smartphone,
  Unplug,
  UserRound,
} from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { DeviceSessionsService } from '../../api/generated'
import { rotateSession } from '../../api/auth'
import { executeApi } from '../../api/runtime'
import {
  EmptyState,
  ErrorNotice,
  IconButton,
  LoadingBlock,
  PageHeader,
  StatusBadge,
} from '../../components/ui'
import { formatDate } from '../../lib/format'
import { queryClient } from '../../app/query-client'
import { useAuth } from '../../app/useAuth'
import { AccountSecurityPanel } from './AccountSecurityPanel'

export function AccountPage() {
  const { refresh, user } = useAuth()
  const devices = useQuery({
    queryKey: ['devices'],
    queryFn: () => executeApi(() => DeviceSessionsService.listDevicesApiV1DeviceSessionsGet()),
  })
  const revoke = useMutation({
    mutationFn: (deviceId: string) => executeApi(() => DeviceSessionsService.revokeDeviceApiV1DeviceSessionsDeviceIdDelete({ deviceId })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['devices'] }),
  })
  const rotate = useMutation({
    mutationFn: rotateSession,
    onSuccess: () => void refresh(),
  })
  return (
    <div className="page-stack">
      <PageHeader
        actions={<button className="button secondary" onClick={() => void rotate.mutateAsync()} type="button"><RefreshCw size={16} /> 轮换当前会话</button>}
        description="浏览器只使用 HttpOnly Cookie Session，页面不会保存 bearer 凭据。"
        eyebrow="账户"
        title="账户与设备"
      />
      <section className="account-identity">
        <div className="account-avatar">{user?.display_name.slice(0, 1)}</div>
        <div><h2>{user?.display_name}</h2><p>{user?.username} · {user?.email ?? '未设置邮箱'}</p><div className="permission-dots"><StatusBadge tone="success"><ShieldCheck size={13} /> 会话已验证</StatusBadge>{user?.is_super_admin ? <StatusBadge tone="info">系统管理员</StatusBadge> : null}</div></div>
      </section>
      <AccountSecurityPanel />
      <div className="section-heading"><div><h2>桌面设备会话</h2><p>设备吊销会立即停止对应同步会话。</p></div></div>
      {devices.isLoading ? <LoadingBlock /> : null}
      {devices.error ? <ErrorNotice error={devices.error} /> : null}
      {devices.data?.items.length === 0 ? <EmptyState description="使用 Windows 桌面端登录后，设备会显示在这里。" icon={UserRound} title="没有桌面设备" /> : null}
      <section className="device-list">
        {(devices.data?.items ?? []).map((device) => (
          <article key={device.id}>
            <span className="device-icon">{device.platform.toLowerCase().includes('mobile') ? <Smartphone size={20} /> : <Laptop size={20} />}</span>
            <div><div className="device-title"><strong>{device.name}</strong>{device.current ? <StatusBadge tone="success">当前设备</StatusBadge> : null}</div><p>{device.platform} · 客户端 {device.client_version} · 最近在线 {formatDate(device.last_seen_at)}</p></div>
            {!device.revoked_at ? <IconButton icon={Unplug} label="吊销设备" onClick={() => void revoke.mutateAsync(device.id)} tone="danger" /> : <StatusBadge tone="warning">已吊销</StatusBadge>}
          </article>
        ))}
      </section>
    </div>
  )
}
