import { Download, Link2, LockKeyhole } from 'lucide-react'
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'

import { PublicSharesService } from '../../api/generated'
import { executeApi } from '../../api/runtime'
import {
  ErrorNotice,
  EmptyState,
  PageHeader,
  StatusBadge,
} from '../../components/ui'

export function PublicSharePage() {
  const params = new URLSearchParams(window.location.search)
  const [tenantSlug, setTenantSlug] = useState(params.get('tenant') ?? 'default')
  const [rawToken, setRawToken] = useState(params.get('token') ?? '')
  const [passcode, setPasscode] = useState('')
  const [access, setAccess] = useState<Awaited<ReturnType<typeof accessShare>> | null>(null)

  const unlock = useMutation({
    mutationFn: () => accessShare({ passcode, rawToken, tenantSlug }),
    onSuccess: setAccess,
  })
  const download = async (nodeId: string) => {
    const result = await executeApi(() => PublicSharesService.createExternalDownloadUrlApiV1PublicSharesDownloadPost({
      requestBody: {
        delivery_mode: 'presigned',
        node_id: nodeId,
        passcode: passcode || null,
        raw_token: rawToken,
        tenant_slug: tenantSlug,
      },
      xDriveTransferProtocol: 'DTP/1',
    }))
    window.open(result.download_url, '_blank', 'noopener,noreferrer')
  }

  return (
    <main className="public-share-shell">
      <div className="public-share-panel">
        <PageHeader description="外链访问不读取登录态，下载 URL 由后端按次数和权限签发。" eyebrow="安全外链" title="访问共享内容" />
        {!access ? (
          <form className="stack-form" onSubmit={(event) => { event.preventDefault(); void unlock.mutateAsync() }}>
            <label>企业标识<input onChange={(event) => setTenantSlug(event.target.value)} required value={tenantSlug} /></label>
            <label>分享凭据<input onChange={(event) => setRawToken(event.target.value)} required value={rawToken} /></label>
            <label>提取码（如有）<input onChange={(event) => setPasscode(event.target.value)} type="password" value={passcode} /></label>
            {unlock.error ? <ErrorNotice error={unlock.error} /> : null}
            <button className="button primary" disabled={unlock.isPending} type="submit"><LockKeyhole size={16} /> {unlock.isPending ? '正在验证…' : '验证并查看'}</button>
          </form>
        ) : (
          <>
            <div className="public-share-meta"><StatusBadge tone="success">访问已验证</StatusBadge><span>分享 ID {access.share_id.slice(0, 8)}</span><span>权限：{access.permission === 'download' ? '可下载' : '仅预览'}</span></div>
            {access.item_node_ids.length ? <div className="compact-list">{access.item_node_ids.map((nodeId) => <article key={nodeId}><div><strong><Link2 size={15} /> 共享节点</strong><span>{nodeId}</span></div>{access.permission === 'download' ? <button className="button secondary" onClick={() => void download(nodeId)} type="button"><Download size={15} /> 下载</button> : null}</article>)}</div> : <EmptyState description="分享中没有可访问的文件。" icon={Link2} title="内容为空" />}
          </>
        )}
      </div>
    </main>
  )
}

async function accessShare({
  passcode,
  rawToken,
  tenantSlug,
}: {
  passcode: string
  rawToken: string
  tenantSlug: string
}) {
  return executeApi(() => PublicSharesService.accessExternalShareApiV1PublicSharesAccessPost({
    requestBody: { passcode: passcode || null, raw_token: rawToken, tenant_slug: tenantSlug },
  }))
}
