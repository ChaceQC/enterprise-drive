import {
  ArchiveRestore,
  Eraser,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { FilesService, SpacesService } from '../../api/generated'
import { executeApi } from '../../api/runtime'
import {
  EmptyState,
  ErrorNotice,
  IconButton,
  LoadingBlock,
  PageHeader,
  StatusBadge,
} from '../../components/ui'
import { createOperationId, formatDate } from '../../lib/format'
import { queryClient } from '../../app/query-client'

export function TrashPage() {
  const [spaceId, setSpaceId] = useState<string>()
  const [selected, setSelected] = useState<string[]>([])
  const spaces = useQuery({
    queryKey: ['spaces'],
    queryFn: () => executeApi(() => SpacesService.listSpacesApiV1SpacesGet({ pageSize: 50 })),
  })
  const activeSpaceId = spaceId ?? spaces.data?.items[0]?.id
  const trash = useQuery({
    enabled: Boolean(activeSpaceId),
    queryKey: ['trash', activeSpaceId],
    queryFn: () => executeApi(() => FilesService.listTrashApiV1FilesTrashGet({
      pageSize: 50,
      spaceId: activeSpaceId!,
    })),
  })
  const restore = useMutation({
    mutationFn: (nodeIds: string[]) => executeApi(() => FilesService.batchRestoreApiV1FilesBatchRestorePost({
      idempotencyKey: createOperationId(),
      requestBody: { node_ids: nodeIds },
    })),
    onSuccess: () => {
      setSelected([])
      void queryClient.invalidateQueries({ queryKey: ['trash', activeSpaceId] })
    },
  })
  const purge = useMutation({
    mutationFn: (nodeIds: string[]) => executeApi(() => FilesService.batchPurgeApiV1FilesBatchPurgePost({
      idempotencyKey: createOperationId(),
      requestBody: { node_ids: nodeIds },
    })),
    onSuccess: () => {
      setSelected([])
      void queryClient.invalidateQueries({ queryKey: ['trash', activeSpaceId] })
    },
  })

  return (
    <div className="page-stack">
      <PageHeader
        actions={(
          <div className="space-switcher">
            <span className="toolbar-label">空间</span>
            <select aria-label="选择空间" onChange={(event) => setSpaceId(event.target.value)} value={activeSpaceId ?? ''}>
              {(spaces.data?.items ?? []).map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
            </select>
          </div>
        )}
        description="删除的目录根节点会按服务端保留策略显示，恢复和彻底删除都逐项返回结果。"
        eyebrow="生命周期"
        title="回收站"
      />
      {trash.isLoading ? <LoadingBlock label="正在读取回收站…" /> : null}
      {trash.error ? <ErrorNotice error={trash.error} onRetry={() => void trash.refetch()} /> : null}
      {selected.length ? (
        <section className="bulk-toolbar">
          <strong>已选 {selected.length} 项</strong>
          <button className="text-button" onClick={() => void restore.mutateAsync(selected)} type="button"><ArchiveRestore size={15} /> 恢复</button>
          <button className="text-button danger" onClick={() => void purge.mutateAsync(selected)} type="button"><Eraser size={15} /> 彻底删除</button>
        </section>
      ) : null}
      {trash.data?.items.length === 0 ? <EmptyState description="回收站为空，暂时没有需要处理的文件。" icon={Trash2} title="没有已删除内容" /> : null}
      {trash.data?.items.length ? (
        <section className="table-plane">
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th className="check-cell">选择</th><th>名称</th><th>删除时间</th><th>状态</th><th className="numeric">操作</th></tr></thead>
              <tbody>
                {trash.data.items.map((node) => (
                  <tr key={node.id}>
                    <td className="check-cell"><input aria-label={`选择 ${node.name}`} checked={selected.includes(node.id)} onChange={() => setSelected((current) => current.includes(node.id) ? current.filter((id) => id !== node.id) : [...current, node.id])} type="checkbox" /></td>
                    <td><div className="file-name-button"><span className="file-glyph folder"><Trash2 size={16} /></span><span><strong>{node.name}</strong><small>{node.node_type}</small></span></div></td>
                    <td className="muted-cell">{formatDate(node.deleted_at)}</td>
                    <td><StatusBadge tone="warning">待处理</StatusBadge></td>
                    <td className="numeric"><IconButton icon={RefreshCw} label="恢复此项" onClick={() => void restore.mutateAsync([node.id])} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  )
}
