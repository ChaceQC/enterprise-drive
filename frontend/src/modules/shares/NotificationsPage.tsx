import {
  Bell,
  BellRing,
  Check,
} from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { SharesService } from '../../api/generated'
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

export function NotificationsPage() {
  const notifications = useQuery({
    queryKey: ['share-notifications'],
    queryFn: () => executeApi(() => SharesService.listShareNotificationsApiV1SharesNotificationsGet({ pageSize: 50 })),
  })
  const markRead = useMutation({
    mutationFn: (notificationId: string) => executeApi(() => SharesService.markShareNotificationReadApiV1SharesNotificationsNotificationIdReadPost({ notificationId })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['share-notifications'] }),
  })
  return (
    <div className="page-stack">
      <PageHeader description="内部分享、撤销和失效事件会进入通知中心。" eyebrow="收件箱" title="通知中心" />
      {notifications.isLoading ? <LoadingBlock /> : null}
      {notifications.error ? <ErrorNotice error={notifications.error} /> : null}
      {notifications.data?.items.length === 0 ? <EmptyState description="新的内部分享和状态变化会显示在这里。" icon={Bell} title="没有新通知" /> : null}
      <section className="notification-list">
        {(notifications.data?.items ?? []).map((item) => (
          <article className={item.is_read ? '' : 'unread'} key={item.id}>
            <span className="notification-icon">{item.is_read ? <Bell size={17} /> : <BellRing size={17} />}</span>
            <div><div className="notification-title"><strong>{item.creator_name} 分享了「{item.root_name}」</strong>{item.invalidated_at ? <StatusBadge tone="warning">已失效</StatusBadge> : null}</div><p>{item.notification_type} · {formatDate(item.created_at)}</p></div>
            {!item.is_read ? <IconButton icon={Check} label="标记已读" onClick={() => void markRead.mutateAsync(item.id)} /> : null}
          </article>
        ))}
      </section>
    </div>
  )
}
