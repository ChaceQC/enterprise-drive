import {
  Download,
  Eye,
  Link2,
  Share2,
  ShieldOff,
} from 'lucide-react'
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import {
  SharesService,
  type ShareListItem,
} from '../../api/generated'
import { executeApi } from '../../api/runtime'
import {
  EmptyState,
  ErrorNotice,
  IconButton,
  LoadingBlock,
  Modal,
  PageHeader,
  SegmentedControl,
  StatusBadge,
} from '../../components/ui'
import { formatDate } from '../../lib/format'
import { queryClient } from '../../app/query-client'

export function SharesPage() {
  const [mode, setMode] = useState<'created' | 'received'>('created')
  const [activeShare, setActiveShare] = useState<ShareListItem | null>(null)
  const list = useQuery({
    queryKey: ['shares', mode],
    queryFn: () => executeApi(() => mode === 'created'
      ? SharesService.listCreatedSharesApiV1SharesCreatedGet({ pageSize: 50 })
      : SharesService.listReceivedSharesApiV1SharesReceivedGet({ pageSize: 50 })),
  })
  const revoke = useMutation({
    mutationFn: (shareId: string) => executeApi(() => SharesService.revokeShareApiV1SharesShareIdRevokePost({ shareId })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['shares', 'created'] }),
  })

  return (
    <div className="page-stack">
      <PageHeader
        actions={<SegmentedControl onChange={setMode} options={[{ label: '我创建的', value: 'created' }, { label: '分享给我的', value: 'received' }]} value={mode} />}
        description="外链、内部接收人、访问次数和撤销状态都以服务端事实为准。"
        eyebrow="协作"
        title="分享"
      />
      {list.isLoading ? <LoadingBlock label="正在读取分享…" /> : null}
      {list.error ? <ErrorNotice error={list.error} onRetry={() => void list.refetch()} /> : null}
      {list.data?.items.length === 0 ? <EmptyState description={mode === 'created' ? '在文件页选择文件并创建分享。' : '收到的内部分享会显示在这里。'} icon={Share2} title="暂时没有分享" /> : null}
      {list.data?.items.length ? (
        <section className="table-plane">
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>名称</th><th>类型</th><th>权限</th><th>创建者</th><th>有效期</th><th className="numeric">操作</th></tr></thead>
              <tbody>
                {list.data.items.map((share) => (
                  <tr key={share.id}>
                    <td><button className="file-name-button" onClick={() => setActiveShare(share)} type="button"><span className="file-glyph"><Link2 size={16} /></span><span><strong>{share.root_name}</strong><small>{share.id.slice(0, 8)}</small></span></button></td>
                    <td><StatusBadge tone={share.share_type === 'external' ? 'warning' : 'info'}>{share.share_type === 'external' ? '外链' : '内部'}</StatusBadge></td>
                    <td>{share.permission === 'download' ? '可下载' : '仅预览'}</td>
                    <td className="muted-cell">{share.creator_name}</td>
                    <td className="muted-cell">{share.expires_at ? formatDate(share.expires_at) : '长期'}</td>
                    <td className="numeric"><div className="row-actions"><IconButton icon={Eye} label="查看详情" onClick={() => setActiveShare(share)} />{mode === 'created' && share.status === 'active' ? <IconButton icon={ShieldOff} label="撤销分享" onClick={() => void revoke.mutateAsync(share.id)} tone="danger" /> : null}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
      {activeShare ? <ShareItemsDialog onClose={() => setActiveShare(null)} share={activeShare} /> : null}
    </div>
  )
}

function ShareItemsDialog({ onClose, share }: { onClose: () => void; share: ShareListItem }) {
  const items = useQuery({
    enabled: share.share_type === 'internal',
    queryKey: ['share-items', share.id],
    queryFn: () => executeApi(() => SharesService.listInternalShareItemsApiV1SharesShareIdItemsGet({ shareId: share.id })),
  })
  const download = async (nodeId: string) => {
    const result = await executeApi(() => SharesService.createInternalShareDownloadUrlApiV1SharesShareIdDownloadPost({
      requestBody: { node_id: nodeId },
      shareId: share.id,
      xDriveTransferProtocol: 'DTP/1',
    }))
    window.open(result.download_url, '_blank', 'noopener,noreferrer')
  }
  return (
    <Modal onClose={onClose} title={`分享详情 · ${share.root_name}`} wide>
      <div className="share-summary">
        <div><span>状态</span><strong>{share.status}</strong></div>
        <div><span>浏览</span><strong>{share.view_count}{share.max_views ? ` / ${share.max_views}` : ''}</strong></div>
        <div><span>下载</span><strong>{share.download_count}{share.max_downloads ? ` / ${share.max_downloads}` : ''}</strong></div>
      </div>
      {share.share_type === 'external' ? (
        <EmptyState description="外链访问凭据只在创建时返回；撤销与次数限制仍可在列表中管理。" icon={Link2} title="外链分享" />
      ) : null}
      {items.isLoading ? <LoadingBlock /> : null}
      {items.error ? <ErrorNotice error={items.error} /> : null}
      {items.data ? (
        <div className="compact-list">
          {items.data.items.map((item) => (
            <article key={item.node_id}><div><strong>{item.name}</strong><span>{item.node_type}</span></div>{share.permission === 'download' && item.node_type !== 'folder' ? <IconButton icon={Download} label="下载" onClick={() => void download(item.node_id)} /> : null}</article>
          ))}
        </div>
      ) : null}
    </Modal>
  )
}
