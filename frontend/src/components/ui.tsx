import {
  X,
  type LucideIcon,
} from 'lucide-react'
import {
  type PropsWithChildren,
  type ReactNode,
} from 'react'

import { ApiError } from '../api/runtime'

export function PageHeader({
  actions,
  eyebrow,
  title,
  description,
}: {
  actions?: ReactNode
  eyebrow?: string
  title: string
  description?: string
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  )
}

export function IconButton({
  icon: Icon,
  label,
  onClick,
  disabled,
  tone = 'neutral',
}: {
  icon: LucideIcon
  label: string
  onClick?: () => void
  disabled?: boolean
  tone?: 'accent' | 'danger' | 'neutral'
}) {
  return (
    <button
      aria-label={label}
      className={`icon-button ${tone}`}
      disabled={disabled}
      onClick={onClick}
      title={label}
      type="button"
    >
      <Icon aria-hidden="true" size={17} strokeWidth={1.8} />
    </button>
  )
}

export function StatusBadge({
  children,
  tone = 'neutral',
}: PropsWithChildren<{
  tone?: 'danger' | 'info' | 'neutral' | 'success' | 'warning'
}>) {
  return <span className={`status-badge ${tone}`}>{children}</span>
}

export function EmptyState({
  action,
  description,
  icon: Icon,
  title,
}: {
  action?: ReactNode
  description: string
  icon: LucideIcon
  title: string
}) {
  return (
    <div className="empty-state">
      <Icon aria-hidden="true" size={30} strokeWidth={1.4} />
      <strong>{title}</strong>
      <p>{description}</p>
      {action}
    </div>
  )
}

export function LoadingBlock({ label = '正在加载…' }: { label?: string }) {
  return (
    <div aria-live="polite" className="loading-block">
      <span className="loading-dot" />
      {label}
    </div>
  )
}

export function ErrorNotice({
  error,
  onRetry,
}: {
  error: unknown
  onRetry?: () => void
}) {
  const normalized = error instanceof ApiError
    ? error
    : new ApiError({
        code: 'UNKNOWN_ERROR',
        message: error instanceof Error ? error.message : '操作未完成',
        requestId: 'unknown',
        status: 0,
      })
  return (
    <div className="error-notice" role="alert">
      <div>
        <strong>{normalized.message}</strong>
        <span>
          {normalized.code}
          {normalized.requestId !== 'unknown'
            ? ` · 请求编号 ${normalized.requestId}`
            : ''}
        </span>
      </div>
      {onRetry ? (
        <button className="text-button" onClick={onRetry} type="button">
          重试
        </button>
      ) : null}
    </div>
  )
}

export function Modal({
  children,
  onClose,
  title,
  wide = false,
}: PropsWithChildren<{
  onClose: () => void
  title: string
  wide?: boolean
}>) {
  return (
    <div
      aria-label={title}
      aria-modal="true"
      className="modal-backdrop"
      role="dialog"
    >
      <section className={`modal ${wide ? 'wide' : ''}`}>
        <header>
          <h2>{title}</h2>
          <IconButton icon={X} label="关闭" onClick={onClose} />
        </header>
        {children}
      </section>
    </div>
  )
}

export function SegmentedControl<T extends string>({
  onChange,
  options,
  value,
}: {
  onChange: (value: T) => void
  options: Array<{ label: string; value: T }>
  value: T
}) {
  return (
    <div className="segmented-control" role="tablist">
      {options.map((option) => (
        <button
          aria-selected={value === option.value}
          className={value === option.value ? 'active' : ''}
          key={option.value}
          onClick={() => onChange(option.value)}
          role="tab"
          type="button"
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
