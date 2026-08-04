import {
  KeyRound,
  LockKeyholeOpen,
  ShieldAlert,
} from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import {
  AdminOrganizationService,
  type AdminUserResponse,
} from '../../api/generated'
import { executeApi } from '../../api/runtime'
import {
  EmptyState,
  ErrorNotice,
  LoadingBlock,
  Modal,
  StatusBadge,
} from '../../components/ui'
import { formatDate } from '../../lib/format'
import { queryClient } from '../../app/query-client'

export function AdminAccountSecurity() {
  const [resetUser, setResetUser] = useState<AdminUserResponse | null>(null)
  const users = useQuery({
    queryKey: ['admin', 'users', 'account-security'],
    queryFn: () => executeApi(
      () => AdminOrganizationService.listAdminUsersApiV1AdminUsersGet({
        pageSize: 100,
      }),
    ),
  })
  const unlock = useMutation({
    mutationFn: (user: AdminUserResponse) => executeApi(
      () => AdminOrganizationService.unlockAdminUserApiV1AdminUsersUserIdUnlockPost({
        userId: user.id,
        requestBody: { expected_version: user.version },
      }),
    ),
    onSuccess: () => void queryClient.invalidateQueries({
      queryKey: ['admin', 'users'],
    }),
  })
  const reset = useMutation({
    mutationFn: ({
      password,
      user,
    }: {
      password: string
      user: AdminUserResponse
    }) => executeApi(
      () => AdminOrganizationService.resetAdminUserPasswordApiV1AdminUsersUserIdPasswordResetPost({
        userId: user.id,
        requestBody: {
          expected_version: user.version,
          new_password: password,
        },
      }),
    ),
    onSuccess: () => {
      setResetUser(null)
      void queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })
    },
  })

  if (users.isLoading) return <LoadingBlock label="正在加载账号安全状态…" />
  if (users.error) return <ErrorNotice error={users.error} onRetry={() => void users.refetch()} />
  const items = users.data?.items ?? []
  if (!items.length) {
    return (
      <EmptyState
        description="当前租户没有可管理的用户。"
        icon={ShieldAlert}
        title="没有用户"
      />
    )
  }

  return (
    <section className="admin-section">
      <div className="section-heading">
        <div>
          <h2>账号安全</h2>
          <p>解锁和密码重置均由后端执行版本前置条件、全会话吊销与审计。</p>
        </div>
      </div>
      <div className="table-plane">
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>用户</th>
                <th>账号状态</th>
                <th>失败次数</th>
                <th>强制改密</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((user) => (
                <tr key={user.id}>
                  <td>
                    <div className="cell-stack">
                      <strong>{user.display_name}</strong>
                      <span>{user.username}</span>
                    </div>
                  </td>
                  <td>
                    <StatusBadge tone={user.locked ? 'danger' : user.is_active ? 'success' : 'warning'}>
                      {user.locked
                        ? `锁定至 ${user.locked_until ? formatDate(user.locked_until) : '待管理员处理'}`
                        : user.is_active ? '正常' : '停用'}
                    </StatusBadge>
                  </td>
                  <td>{user.failed_login_attempts}</td>
                  <td>{user.must_change_password ? '是' : '否'}</td>
                  <td>
                    <div className="inline-actions">
                      <button
                        className="text-button"
                        disabled={!user.locked || unlock.isPending}
                        onClick={() => void unlock.mutateAsync(user)}
                        type="button"
                      >
                        <LockKeyholeOpen size={15} /> 解锁
                      </button>
                      <button
                        className="text-button"
                        onClick={() => setResetUser(user)}
                        type="button"
                      >
                        <KeyRound size={15} /> 重置密码
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {unlock.error ? <ErrorNotice error={unlock.error} /> : null}
      {resetUser ? (
        <Modal
          onClose={() => setResetUser(null)}
          title={`重置密码 · ${resetUser.display_name}`}
        >
          <ResetPasswordForm
            pending={reset.isPending}
            onSubmit={(password) => void reset.mutateAsync({
              password,
              user: resetUser,
            })}
          />
          {reset.error ? <ErrorNotice error={reset.error} /> : null}
        </Modal>
      ) : null}
    </section>
  )
}

function ResetPasswordForm({
  onSubmit,
  pending,
}: {
  onSubmit: (password: string) => void
  pending: boolean
}) {
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (password === confirmation) onSubmit(password)
  }

  return (
    <form className="stack-form" onSubmit={submit}>
      <p className="muted">重置后用户下次登录必须改密，旧浏览器与桌面会话立即失效。</p>
      <label>
        临时密码
        <input
          autoComplete="new-password"
          minLength={12}
          onChange={(event) => setPassword(event.target.value)}
          required
          type="password"
          value={password}
        />
      </label>
      <label>
        确认临时密码
        <input
          autoComplete="new-password"
          minLength={12}
          onChange={(event) => setConfirmation(event.target.value)}
          required
          type="password"
          value={confirmation}
        />
      </label>
      {confirmation && password !== confirmation ? (
        <p className="form-hint danger">两次输入的临时密码不一致。</p>
      ) : null}
      <button
        className="button primary"
        disabled={pending || password !== confirmation}
        type="submit"
      >
        {pending ? '正在重置…' : '重置并吊销全部会话'}
      </button>
    </form>
  )
}
