import {
  ChevronRight,
  Download,
  Eye,
  Folder,
  FolderPlus,
  History,
  MoreHorizontal,
  Move,
  Pencil,
  RefreshCw,
  Share2,
  Trash2,
  Upload,
  File,
} from 'lucide-react'
import {
  useRef,
  useState,
} from 'react'
import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/react-query'

import {
  DirectoryService,
  FilesService,
  SharesService,
  SpacesService,
  type DirectoryDepartmentResponse,
  type DirectoryGroupResponse,
  type DirectoryUserResponse,
  type FileNodeResponse,
  type FileVersionResponse,
} from '../../api/generated'
import { executeApi } from '../../api/runtime'
import {
  EmptyState,
  ErrorNotice,
  IconButton,
  LoadingBlock,
  Modal,
  PageHeader,
  StatusBadge,
} from '../../components/ui'
import { createOperationId, formatBytes, formatDate } from '../../lib/format'
import { queryClient } from '../../app/query-client'
import { useUploads } from '../uploads/useUploads'
import { UploadQueue } from '../uploads/UploadQueue'

type Dialog = 'folder' | 'move' | 'preview' | 'rename' | 'share' | 'versions' | null

const permission = (node: FileNodeResponse, action: string) =>
  node.permissions?.[action] ?? false

export function DrivePage() {
  const [spaceId, setSpaceId] = useState<string | undefined>()
  const [parentId, setParentId] = useState<string | null>(null)
  const [breadcrumb, setBreadcrumb] = useState<Array<{ id: string | null; name: string }>>([
    { id: null, name: '根目录' },
  ])
  const [selected, setSelected] = useState<string[]>([])
  const [dialog, setDialog] = useState<Dialog>(null)
  const [activeNode, setActiveNode] = useState<FileNodeResponse | null>(null)
  const [batchResult, setBatchResult] = useState<Array<{ code?: string | null; node_id: string; status: string }>>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const { enqueue } = useUploads()

  const spacesQuery = useQuery({
    queryKey: ['spaces'],
    queryFn: () => executeApi(() => SpacesService.listSpacesApiV1SpacesGet({ pageSize: 50 })),
  })
  const activeSpaceId = spaceId ?? spacesQuery.data?.items[0]?.id
  const filesQuery = useQuery({
    enabled: Boolean(activeSpaceId),
    queryKey: ['files', activeSpaceId, parentId],
    queryFn: () => executeApi(() => FilesService.listFilesApiV1FilesGet({
      parentId,
      pageSize: 50,
      spaceId: activeSpaceId!,
    })),
  })

  const createFolder = useMutation({
    mutationFn: (name: string) => executeApi(() => FilesService.createFolderApiV1FilesFoldersPost({
      requestBody: { name, parent_id: parentId, space_id: activeSpaceId! },
      xClientOperationId: createOperationId(),
    })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['files', activeSpaceId, parentId] })
      setDialog(null)
    },
  })

  const rename = useMutation({
    mutationFn: ({ name, node }: { name: string; node: FileNodeResponse }) => executeApi(() => (
      FilesService.renameNodeApiV1FilesNodeIdPatch({
        nodeId: node.id,
        requestBody: {
          expected_current_version_id: node.current_version_id,
          name,
        },
        xClientOperationId: createOperationId(),
      })
    )),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['files', activeSpaceId, parentId] })
      setDialog(null)
    },
  })

  const batchDelete = useMutation({
    mutationFn: (nodeIds: string[]) => executeApi(() => FilesService.batchDeleteApiV1FilesBatchDeletePost({
      idempotencyKey: createOperationId(),
      requestBody: { mode: 'trash', node_ids: nodeIds },
    })),
    onSuccess: (result) => {
      setBatchResult(result.results)
      setSelected([])
      void queryClient.invalidateQueries({ queryKey: ['files', activeSpaceId, parentId] })
    },
  })

  const batchMove = useMutation({
    mutationFn: ({ nodeIds, targetParentId }: { nodeIds: string[]; targetParentId: string }) => (
      executeApi(() => FilesService.batchMoveApiV1FilesBatchMovePost({
        idempotencyKey: createOperationId(),
        requestBody: {
          conflict_policy: 'fail',
          node_ids: nodeIds,
          target_parent_id: targetParentId,
        },
      }))
    ),
    onSuccess: (result) => {
      setBatchResult(result.results)
      setSelected([])
      setDialog(null)
      void queryClient.invalidateQueries({ queryKey: ['files', activeSpaceId, parentId] })
    },
  })

  const switchSpace = (nextSpaceId: string) => {
    setSpaceId(nextSpaceId)
    setParentId(null)
    setBreadcrumb([{ id: null, name: '根目录' }])
    setSelected([])
  }

  const openFolder = (node: FileNodeResponse) => {
    setParentId(node.id)
    setBreadcrumb((current) => [...current, { id: node.id, name: node.name }])
    setSelected([])
  }

  const goBreadcrumb = (index: number) => {
    const crumb = breadcrumb[index]
    setParentId(crumb.id)
    setBreadcrumb(breadcrumb.slice(0, index + 1))
    setSelected([])
  }

  const toggleSelected = (id: string) => {
    setSelected((current) => (
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id]
    ))
  }

  const toggleAll = () => {
    const ids = filesQuery.data?.items.map((node) => node.id) ?? []
    setSelected((current) => current.length === ids.length ? [] : ids)
  }

  const download = async (node: FileNodeResponse) => {
    const result = await executeApi(() => FilesService.createDownloadUrlApiV1FilesNodeIdDownloadGet({
      nodeId: node.id,
      xDriveTransferProtocol: 'DTP/1',
    }))
    const anchor = document.createElement('a')
    anchor.href = result.download_url
    anchor.download = result.file_name
    anchor.rel = 'noreferrer'
    anchor.click()
  }

  const preview = async (node: FileNodeResponse) => {
    setActiveNode(node)
    setDialog('preview')
  }

  return (
    <div className="page-stack">
      <PageHeader
        actions={(
          <div className="page-actions">
            <button
              className="button secondary"
              disabled={!activeSpaceId}
              onClick={() => setDialog('folder')}
              type="button"
            >
              <FolderPlus size={16} /> 新建文件夹
            </button>
            <button
              className="button primary"
              disabled={!activeSpaceId || !filesQuery.data?.parent_id}
              onClick={() => inputRef.current?.click()}
              type="button"
            >
              <Upload size={16} /> 上传文件
            </button>
            <input
              hidden
              multiple
              onChange={(event) => {
                const files = Array.from(event.target.files ?? [])
                if (files.length && activeSpaceId && filesQuery.data?.parent_id) {
                  enqueue(files, activeSpaceId, filesQuery.data.parent_id)
                }
                event.target.value = ''
              }}
              ref={inputRef}
              type="file"
            />
          </div>
        )}
        description="在同一个安全工作区里浏览、上传、分享和恢复文件。"
        eyebrow="文件工作区"
        title="我的文件"
      />

      <section className="workspace-toolbar">
        <div className="space-switcher">
          <span className="toolbar-label">空间</span>
          <select
            aria-label="选择空间"
            onChange={(event) => switchSpace(event.target.value)}
            value={activeSpaceId ?? ''}
          >
            {(spacesQuery.data?.items ?? []).map((space) => (
              <option key={space.id} value={space.id}>{space.name}</option>
            ))}
          </select>
        </div>
        <div className="breadcrumbs" aria-label="文件路径">
          {breadcrumb.map((crumb, index) => (
            <span key={`${crumb.id ?? 'root'}-${index}`}>
              <button className="breadcrumb-button" onClick={() => goBreadcrumb(index)} type="button">
                {crumb.name}
              </button>
              {index < breadcrumb.length - 1 ? <ChevronRight size={14} /> : null}
            </span>
          ))}
        </div>
        <IconButton
          icon={RefreshCw}
          label="刷新文件列表"
          onClick={() => void filesQuery.refetch()}
        />
      </section>

      {selected.length ? (
        <section className="bulk-toolbar" aria-label="批量操作">
          <strong>已选 {selected.length} 项</strong>
          <button className="text-button" onClick={() => setDialog('move')} type="button">
            <Move size={15} /> 移动
          </button>
          <button
            className="text-button danger"
            onClick={() => void batchDelete.mutateAsync(selected)}
            type="button"
          >
            <Trash2 size={15} /> 移到回收站
          </button>
          <button className="text-button" onClick={() => setSelected([])} type="button">取消选择</button>
        </section>
      ) : null}

      {batchResult.length ? (
        <section className="result-strip" aria-live="polite">
          {batchResult.map((result) => (
            <span className={result.status === 'success' ? 'result-ok' : 'result-fail'} key={result.node_id}>
              {result.status === 'success' ? '成功' : result.code ?? '失败'} · {result.node_id.slice(0, 8)}
            </span>
          ))}
          <button className="text-button" onClick={() => setBatchResult([])} type="button">收起</button>
        </section>
      ) : null}

      {spacesQuery.isLoading || filesQuery.isLoading ? <LoadingBlock label="正在加载文件树…" /> : null}
      {spacesQuery.error ? <ErrorNotice error={spacesQuery.error} onRetry={() => void spacesQuery.refetch()} /> : null}
      {filesQuery.error ? <ErrorNotice error={filesQuery.error} onRetry={() => void filesQuery.refetch()} /> : null}

      {!filesQuery.isLoading && !filesQuery.error && (filesQuery.data?.items.length ?? 0) === 0 ? (
        <EmptyState
          action={(
            <button
              className="button primary"
              disabled={!filesQuery.data?.parent_id}
              onClick={() => inputRef.current?.click()}
              type="button"
            >
              <Upload size={16} /> 上传第一份文件
            </button>
          )}
          description="上传文件或先创建一个文件夹，工作区会从这里开始积累。"
          icon={Folder}
          title="这个目录还没有内容"
        />
      ) : null}

      {filesQuery.data?.items.length ? (
        <section className="table-plane">
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="check-cell">
                    <input
                      aria-label="全选文件"
                      checked={selected.length === filesQuery.data.items.length}
                      onChange={toggleAll}
                      type="checkbox"
                    />
                  </th>
                  <th>名称</th>
                  <th>权限</th>
                  <th>更新时间</th>
                  <th className="numeric">操作</th>
                </tr>
              </thead>
              <tbody>
                {filesQuery.data.items.map((node) => (
                  <tr className={selected.includes(node.id) ? 'selected' : ''} key={node.id}>
                    <td className="check-cell">
                      <input
                        aria-label={`选择 ${node.name}`}
                        checked={selected.includes(node.id)}
                        onChange={() => toggleSelected(node.id)}
                        type="checkbox"
                      />
                    </td>
                    <td>
                      <button
                        className="file-name-button"
                        onClick={() => node.node_type === 'folder' ? openFolder(node) : preview(node)}
                        type="button"
                      >
                        <span className={`file-glyph ${node.node_type === 'folder' ? 'folder' : ''}`}>
                          {node.node_type === 'folder' ? <Folder size={16} /> : <File size={16} />}
                        </span>
                        <span>
                          <strong>{node.name}</strong>
                          <small>{node.node_type === 'folder' ? '文件夹' : '文件'}</small>
                        </span>
                      </button>
                    </td>
                    <td>
                      <div className="permission-dots">
                        {permission(node, 'read_meta') ? <StatusBadge tone="info">可查看</StatusBadge> : null}
                        {permission(node, 'download') ? <StatusBadge tone="success">可下载</StatusBadge> : null}
                        {permission(node, 'update') ? <StatusBadge tone="neutral">可编辑</StatusBadge> : null}
                      </div>
                    </td>
                    <td className="muted-cell">{formatDate(node.updated_at)}</td>
                    <td className="numeric">
                      <div className="row-actions">
                        {permission(node, 'preview') ? (
                          <IconButton icon={Eye} label="预览" onClick={() => void preview(node)} />
                        ) : null}
                        {permission(node, 'read_meta') && node.current_version_id ? (
                          <IconButton
                            icon={History}
                            label="文件版本"
                            onClick={() => { setActiveNode(node); setDialog('versions') }}
                          />
                        ) : null}
                        {permission(node, 'download') ? (
                          <IconButton icon={Download} label="下载" onClick={() => void download(node)} />
                        ) : null}
                        {permission(node, 'update') ? (
                          <IconButton icon={Pencil} label="重命名" onClick={() => { setActiveNode(node); setDialog('rename') }} />
                        ) : null}
                        {permission(node, 'share') ? (
                          <IconButton icon={Share2} label="创建分享" onClick={() => { setActiveNode(node); setDialog('share') }} />
                        ) : null}
                        <IconButton icon={MoreHorizontal} label="更多操作" />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {filesQuery.data.next_cursor ? (
            <div className="table-footer"><span>还有更多内容</span><button className="text-button">加载下一页</button></div>
          ) : null}
        </section>
      ) : null}

      <UploadQueue />

      {dialog === 'folder' ? (
        <Modal onClose={() => setDialog(null)} title="新建文件夹">
          <FormDialog
            submitLabel="创建文件夹"
            onSubmit={(value) => void createFolder.mutateAsync(value)}
          />
        </Modal>
      ) : null}
      {dialog === 'rename' && activeNode ? (
        <Modal onClose={() => setDialog(null)} title="重命名">
          <FormDialog
            initialValue={activeNode.name}
            submitLabel="保存名称"
            onSubmit={(value) => void rename.mutateAsync({ name: value, node: activeNode })}
          />
        </Modal>
      ) : null}
      {dialog === 'move' ? (
        <Modal onClose={() => setDialog(null)} title={`移动 ${selected.length} 项`}>
          <FormDialog
            label="目标文件夹 ID"
            submitLabel="移动"
            onSubmit={(value) => void batchMove.mutateAsync({ nodeIds: selected, targetParentId: value })}
          />
        </Modal>
      ) : null}
      {dialog === 'preview' && activeNode ? (
        <PreviewDialog node={activeNode} onClose={() => setDialog(null)} />
      ) : null}
      {dialog === 'versions' && activeNode ? (
        <VersionDialog node={activeNode} onClose={() => setDialog(null)} />
      ) : null}
      {dialog === 'share' && activeNode ? (
        <ShareDialog node={activeNode} onClose={() => setDialog(null)} />
      ) : null}
    </div>
  )
}

function FormDialog({
  initialValue = '',
  label = '名称',
  onSubmit,
  submitLabel,
}: {
  initialValue?: string
  label?: string
  onSubmit: (value: string) => void
  submitLabel: string
}) {
  const [value, setValue] = useState(initialValue)
  return (
    <form
      className="stack-form"
      onSubmit={(event) => {
        event.preventDefault()
        if (value.trim()) onSubmit(value.trim())
      }}
    >
      <label>{label}<input autoFocus onChange={(event) => setValue(event.target.value)} required value={value} /></label>
      <button className="button primary" type="submit">{submitLabel}</button>
    </form>
  )
}

function PreviewDialog({ node, onClose }: { node: FileNodeResponse; onClose: () => void }) {
  const previewQuery = useQuery({
    queryKey: ['preview', node.id],
    queryFn: () => executeApi(() => FilesService.createPreviewUrlApiV1FilesNodeIdPreviewGet({ nodeId: node.id })),
  })
  return (
    <Modal onClose={onClose} title={`预览 · ${node.name}`} wide>
      {previewQuery.isLoading ? <LoadingBlock label="正在生成预览…" /> : null}
      {previewQuery.error ? <ErrorNotice error={previewQuery.error} onRetry={() => void previewQuery.refetch()} /> : null}
      {previewQuery.data?.artifact ? (
        <div className="preview-frame">
          <img alt={node.name} src={previewQuery.data.artifact.preview_url} />
          <p>{previewQuery.data.status} · {formatBytes(previewQuery.data.artifact.size_bytes)}</p>
        </div>
      ) : previewQuery.data ? <EmptyState description={previewQuery.data.error ?? '暂时没有可用预览。'} icon={Eye} title="预览尚未就绪" /> : null}
    </Modal>
  )
}

function VersionDialog({ node, onClose }: { node: FileNodeResponse; onClose: () => void }) {
  const [downloadError, setDownloadError] = useState<unknown>()
  const versionsQuery = useInfiniteQuery({
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage: { next_cursor?: string | null }) => (
      lastPage.next_cursor ?? undefined
    ),
    queryFn: ({ pageParam }) => executeApi(() => (
      FilesService.listFileVersionsApiV1FilesNodeIdVersionsGet({
        cursor: pageParam,
        nodeId: node.id,
        pageSize: 50,
      })
    )),
    queryKey: ['file-versions', node.id],
  })
  const rollback = useMutation({
    mutationFn: (versionId: string) => executeApi(() => (
      FilesService.rollbackFileVersionApiV1FilesNodeIdVersionsVersionIdRollbackPost({
        nodeId: node.id,
        requestBody: {
          expected_current_version_id: versionsQuery.data?.pages[0]?.current_version_id
            ?? node.current_version_id,
        },
        versionId,
      })
    )),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['files'] })
      void versionsQuery.refetch()
    },
  })
  const versions = versionsQuery.data?.pages.flatMap((page) => page.items) ?? []
  const currentVersionId = versionsQuery.data?.pages[0]?.current_version_id
    ?? node.current_version_id
  const canDownload = permission(node, 'download')
  const canRollback = permission(node, 'update')

  const downloadVersion = async (version: FileVersionResponse) => {
    try {
      setDownloadError(undefined)
      const result = await executeApi(() => (
        FilesService.createVersionDownloadUrlApiV1FilesNodeIdVersionsVersionIdDownloadGet({
          nodeId: node.id,
          versionId: version.id,
          xDriveTransferProtocol: 'DTP/1',
        })
      ))
      const anchor = document.createElement('a')
      anchor.href = result.download_url
      anchor.download = result.file_name
      anchor.rel = 'noreferrer'
      anchor.click()
    } catch (error) {
      setDownloadError(error)
    }
  }

  return (
    <Modal onClose={onClose} title={`文件版本 · ${node.name}`} wide>
      {versionsQuery.isLoading ? <LoadingBlock label="正在加载版本…" /> : null}
      {versionsQuery.error ? (
        <ErrorNotice error={versionsQuery.error} onRetry={() => void versionsQuery.refetch()} />
      ) : null}
      {downloadError ? <ErrorNotice error={downloadError} /> : null}
      {!versionsQuery.isLoading && !versionsQuery.error && versions.length === 0 ? (
        <EmptyState description="这个文件还没有可用版本。" icon={History} title="暂无版本" />
      ) : null}
      {versions.length ? (
        <div className="version-list">
          {versions.map((version) => (
            <article className="version-row" key={version.id}>
              <div>
                <strong>版本 {version.version_no}</strong>
                <span>
                  {formatDate(version.created_at)} · {formatBytes(version.size_bytes)}
                  {version.mime_type ? ` · ${version.mime_type}` : ''}
                </span>
              </div>
              <div className="row-actions">
                {version.id === currentVersionId || version.is_current ? (
                  <StatusBadge tone="success">当前版本</StatusBadge>
                ) : canRollback ? (
                  <button
                    className="text-button"
                    disabled={rollback.isPending}
                    onClick={() => {
                      if (window.confirm(`确定回滚到版本 ${version.version_no} 吗？`)) {
                        rollback.mutate(version.id)
                      }
                    }}
                    type="button"
                  >
                    回滚
                  </button>
                ) : null}
                {canDownload ? (
                  <IconButton
                    icon={Download}
                    label={`下载版本 ${version.version_no}`}
                    onClick={() => void downloadVersion(version)}
                  />
                ) : null}
              </div>
            </article>
          ))}
          {versionsQuery.hasNextPage ? (
            <button
              className="button secondary"
              disabled={versionsQuery.isFetchingNextPage}
              onClick={() => void versionsQuery.fetchNextPage()}
              type="button"
            >
              {versionsQuery.isFetchingNextPage ? '正在加载…' : '加载更多版本'}
            </button>
          ) : null}
        </div>
      ) : null}
      {rollback.error ? <ErrorNotice error={rollback.error} /> : null}
    </Modal>
  )
}

function ShareDialog({ node, onClose }: { node: FileNodeResponse; onClose: () => void }) {
  const [shareType, setShareType] = useState<'external' | 'internal'>('internal')
  const [permissionValue, setPermissionValue] = useState<'download' | 'preview'>('download')
  const [passcode, setPasscode] = useState('')
  const [recipients, setRecipients] = useState<DirectoryRecipient[]>([])
  const [created, setCreated] = useState<string | null>(null)
  const mutation = useMutation({
    mutationFn: () => executeApi(() => {
      return SharesService.createShareApiV1SharesPost({
        requestBody: {
          item_node_ids: [],
          passcode: passcode || null,
          permission: permissionValue,
          recipients: shareType === 'internal'
            ? recipients.map(({ id, type }) => ({
                subject_id: id,
                subject_type: type,
              }))
            : [],
          root_node_id: node.id,
          share_type: shareType,
        },
      })
    }),
    onSuccess: (result) => setCreated(result.raw_token ?? result.id),
  })
  return (
    <Modal onClose={onClose} title={`创建分享 · ${node.name}`}>
      {created ? (
        <div className="share-result">
          <StatusBadge tone="success">分享已创建</StatusBadge>
          <p>请复制这次返回的分享凭据，之后不会再次显示。</p>
          <code>{created}</code>
          <button className="button primary" onClick={onClose} type="button">完成</button>
        </div>
      ) : (
        <form className="stack-form" onSubmit={(event) => { event.preventDefault(); void mutation.mutateAsync() }}>
          <label>分享类型<select onChange={(event) => setShareType(event.target.value as 'external' | 'internal')} value={shareType}><option value="internal">内部分享</option><option value="external">外链分享</option></select></label>
          <label>权限<select onChange={(event) => setPermissionValue(event.target.value as 'download' | 'preview')} value={permissionValue}><option value="download">允许下载</option><option value="preview">仅预览</option></select></label>
          {shareType === 'external' ? (
            <label>提取码（可选）<input onChange={(event) => setPasscode(event.target.value)} value={passcode} /></label>
          ) : (
            <DirectoryRecipientPicker
              onChange={setRecipients}
              recipients={recipients}
            />
          )}
          {mutation.error ? <ErrorNotice error={mutation.error} /> : null}
          <button
            className="button primary"
            disabled={mutation.isPending || (shareType === 'internal' && recipients.length === 0)}
            type="submit"
          >
            {mutation.isPending ? '正在创建…' : '创建分享'}
          </button>
        </form>
      )}
    </Modal>
  )
}

type DirectoryRecipientType = 'department' | 'group' | 'user'

export interface DirectoryRecipient {
  description: string
  id: string
  label: string
  type: DirectoryRecipientType
}

export function DirectoryRecipientPicker({
  onChange,
  recipients,
}: {
  onChange: (value: DirectoryRecipient[]) => void
  recipients: DirectoryRecipient[]
}) {
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const normalizedQuery = query.trim()
  const usersQuery = useQuery({
    enabled: normalizedQuery.length > 0,
    queryFn: () => executeApi(() => DirectoryService.listDirectoryUsersApiV1DirectoryUsersGet({
      pageSize: 10,
      q: normalizedQuery,
    })),
    queryKey: ['directory', 'users', normalizedQuery],
  })
  const departmentsQuery = useQuery({
    enabled: normalizedQuery.length > 0,
    queryFn: () => executeApi(() => (
      DirectoryService.listDirectoryDepartmentsApiV1DirectoryDepartmentsGet({
        pageSize: 10,
        q: normalizedQuery,
      })
    )),
    queryKey: ['directory', 'departments', normalizedQuery],
  })
  const groupsQuery = useQuery({
    enabled: normalizedQuery.length > 0,
    queryFn: () => executeApi(() => DirectoryService.listDirectoryGroupsApiV1DirectoryGroupsGet({
      pageSize: 10,
      q: normalizedQuery,
    })),
    queryKey: ['directory', 'groups', normalizedQuery],
  })
  const options: DirectoryRecipient[] = [
    ...(usersQuery.data?.items ?? []).map((user: DirectoryUserResponse) => ({
      description: `用户 · @${user.username}`,
      id: user.id,
      label: user.display_name,
      type: 'user' as const,
    })),
    ...(departmentsQuery.data?.items ?? []).map((department: DirectoryDepartmentResponse) => ({
      description: `部门 · ${department.path}`,
      id: department.id,
      label: department.name,
      type: 'department' as const,
    })),
    ...(groupsQuery.data?.items ?? []).map((group: DirectoryGroupResponse) => ({
      description: `用户组 · ${group.slug}`,
      id: group.id,
      label: group.name,
      type: 'group' as const,
    })),
  ].filter((option) => !recipients.some((recipient) => (
    recipient.id === option.id && recipient.type === option.type
  )))
  const boundedActiveIndex = options.length
    ? Math.min(activeIndex, options.length - 1)
    : 0

  const selectRecipient = (recipient: DirectoryRecipient) => {
    onChange([...recipients, recipient])
    setQuery('')
    setActiveIndex(0)
  }

  return (
    <div className="recipient-picker">
      <label htmlFor="share-recipient-search">接收人</label>
      <div className="recipient-chips" aria-label="已选接收人">
        {recipients.length ? recipients.map((recipient) => (
          <span key={`${recipient.type}:${recipient.id}`}>
            {recipient.label}
            <button
              aria-label={`移除 ${recipient.label}`}
              onClick={() => onChange(recipients.filter((item) => item !== recipient))}
              type="button"
            >
              ×
            </button>
          </span>
        )) : <small>搜索并选择用户、部门或用户组。</small>}
      </div>
      <input
        aria-activedescendant={options[boundedActiveIndex]
          ? `share-recipient-option-${boundedActiveIndex}`
          : undefined}
        aria-autocomplete="list"
        aria-controls="share-recipient-options"
        autoComplete="off"
        id="share-recipient-search"
        onChange={(event) => {
          setQuery(event.target.value)
          setActiveIndex(0)
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && normalizedQuery) {
            event.preventDefault()
            if (options.length) selectRecipient(options[boundedActiveIndex])
          } else if (event.key === 'ArrowDown' && options.length) {
            event.preventDefault()
            setActiveIndex((current) => (current + 1) % options.length)
          } else if (event.key === 'ArrowUp' && options.length) {
            event.preventDefault()
            setActiveIndex((current) => (current - 1 + options.length) % options.length)
          } else if (event.key === 'Escape') {
            setQuery('')
            setActiveIndex(0)
          }
        }}
        placeholder="输入姓名、用户名、部门或用户组"
        role="combobox"
        aria-expanded={Boolean(normalizedQuery)}
        value={query}
      />
      {normalizedQuery ? (
        <div className="recipient-options" id="share-recipient-options" role="listbox">
          {usersQuery.isLoading || departmentsQuery.isLoading || groupsQuery.isLoading ? (
            <span>正在搜索目录…</span>
          ) : null}
          {options.map((option, index) => (
            <button
              aria-selected={boundedActiveIndex === index}
              className={boundedActiveIndex === index ? 'active' : ''}
              id={`share-recipient-option-${index}`}
              key={`${option.type}:${option.id}`}
              onClick={() => selectRecipient(option)}
              onMouseEnter={() => setActiveIndex(index)}
              role="option"
              type="button"
            >
              <strong>{option.label}</strong>
              <span>{option.description}</span>
            </button>
          ))}
          {!usersQuery.isLoading
            && !departmentsQuery.isLoading
            && !groupsQuery.isLoading
            && options.length === 0 ? <span>没有匹配的目录对象</span> : null}
        </div>
      ) : null}
      {usersQuery.error || departmentsQuery.error || groupsQuery.error ? (
        <ErrorNotice error={usersQuery.error ?? departmentsQuery.error ?? groupsQuery.error} />
      ) : null}
    </div>
  )
}
