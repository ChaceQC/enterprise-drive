export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '—'
  }
  if (value < 1024) {
    return `${value} B`
  }
  const units = ['KB', 'MB', 'GB', 'TB']
  let size = value
  let unitIndex = -1
  do {
    size /= 1024
    unitIndex += 1
  } while (size >= 1024 && unitIndex < units.length - 1)
  return `${size >= 10 ? size.toFixed(1) : size.toFixed(2)} ${units[unitIndex]}`
}

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return '—'
  }
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export function compactId(value: string | null | undefined): string {
  if (!value) {
    return '—'
  }
  return value.length > 14 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value
}

export function createOperationId(): string {
  return crypto.randomUUID()
}
