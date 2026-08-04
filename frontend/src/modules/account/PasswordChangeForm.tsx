import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import {
  changePassword,
  getPasswordPolicy,
} from '../../api/auth'
import { ErrorNotice } from '../../components/ui'

export function PasswordChangeForm({
  forced = false,
  onChanged,
}: {
  forced?: boolean
  onChanged: () => Promise<void> | void
}) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const policy = useQuery({
    queryKey: ['password-policy'],
    queryFn: getPasswordPolicy,
  })
  const change = useMutation({
    mutationFn: changePassword,
    onSuccess: async () => {
      setCurrentPassword('')
      setNewPassword('')
      setConfirmation('')
      await onChanged()
    },
  })

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (newPassword !== confirmation) {
      return
    }
    void change.mutateAsync({
      current_password: currentPassword,
      new_password: newPassword,
    })
  }

  const rules = policy.data
    ? [
        `至少 ${policy.data.min_length} 个字符`,
        policy.data.require_uppercase ? '包含大写字母' : null,
        policy.data.require_lowercase ? '包含小写字母' : null,
        policy.data.require_digit ? '包含数字' : null,
        policy.data.require_special ? '包含特殊字符' : null,
      ].filter(Boolean)
    : []

  return (
    <form className="stack-form password-change-form" onSubmit={submit}>
      <div>
        <h2>{forced ? '首次登录必须修改密码' : '修改密码'}</h2>
        <p className="muted">
          修改成功后会吊销浏览器和桌面端的全部旧会话，并要求重新登录。
        </p>
      </div>
      <label>
        当前密码
        <input
          autoComplete="current-password"
          disabled={change.isPending}
          onChange={(event) => setCurrentPassword(event.target.value)}
          required
          type="password"
          value={currentPassword}
        />
      </label>
      <label>
        新密码
        <input
          autoComplete="new-password"
          disabled={change.isPending}
          onChange={(event) => setNewPassword(event.target.value)}
          required
          type="password"
          value={newPassword}
        />
      </label>
      <label>
        确认新密码
        <input
          autoComplete="new-password"
          disabled={change.isPending}
          onChange={(event) => setConfirmation(event.target.value)}
          required
          type="password"
          value={confirmation}
        />
      </label>
      {confirmation && confirmation !== newPassword ? (
        <p className="form-hint danger" role="alert">两次输入的新密码不一致。</p>
      ) : null}
      {rules.length ? (
        <p className="form-hint">密码策略：{rules.join('、')}。</p>
      ) : null}
      {change.error ? <ErrorNotice error={change.error} /> : null}
      <button
        className="button primary"
        disabled={change.isPending || newPassword !== confirmation}
        type="submit"
      >
        {change.isPending ? '正在修改…' : '修改密码并重新登录'}
      </button>
    </form>
  )
}
