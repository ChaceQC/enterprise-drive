import {
  AlertTriangle,
  Archive,
  BellRing,
  Clock3,
  DatabaseZap,
  ListRestart,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Workflow,
  type LucideIcon,
} from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  useState,
  type FormEvent,
  type ReactNode,
} from 'react'

import {
  AdminGovernanceService,
  AdminGovernanceSprint12Service,
  type AdminAuditGovernanceResponse,
  type AdminOutboxDeadLetterResponse,
  type AdminTreeOperationResponse,
  type LifecyclePolicyResponse,
  type LifecyclePolicyUpdateRequest,
  type LifecycleRunResponse,
  type PermissionRebuildCreateRequest,
  type PermissionRebuildOperationResponse,
} from '../../api/generated'
import { executeApi } from '../../api/runtime'
import { queryClient } from '../../app/query-client'
import {
  EmptyState,
  ErrorNotice,
  LoadingBlock,
  Modal,
  StatusBadge,
} from '../../components/ui'
import { formatBytes, formatDate } from '../../lib/format'

export function AdminGovernancePage() {
  const [editingPolicy, setEditingPolicy] = useState(false)
  const [creatingRebuild, setCreatingRebuild] = useState(false)

  const stats = useQuery({
    queryKey: ['admin', 'overview'],
    queryFn: () => executeApi(
      () => AdminGovernanceService.getAdminOverviewStatsApiV1AdminStatsOverviewGet(),
    ),
  })
  const maintenance = useQuery({
    queryKey: ['admin', 'maintenance', 'tasks'],
    queryFn: () => executeApi(
      () => AdminGovernanceService.getAdminMaintenanceTasksApiV1AdminMaintenanceTasksGet(),
    ),
  })
  const governanceOverview = useQuery({
    queryKey: ['admin', 'governance', 'overview'],
    queryFn: () => executeApi(
      () => AdminGovernanceSprint12Service.getGovernanceOverviewApiV1AdminGovernanceOverviewGet(),
    ),
  })
  const treeOperations = useQuery({
    queryKey: ['admin', 'governance', 'tree-operations'],
    queryFn: () => executeApi(
      () => AdminGovernanceSprint12Service
        .listGovernanceTreeOperationsApiV1AdminGovernanceTreeOperationsGet({
          pageSize: 50,
        }),
    ),
  })
  const permissionRebuilds = useQuery({
    queryKey: ['admin', 'governance', 'permission-rebuilds'],
    queryFn: () => executeApi(
      () => AdminGovernanceSprint12Service
        .listPermissionRebuildsApiV1AdminGovernancePermissionRebuildsGet({
          pageSize: 50,
        }),
    ),
  })
  const lifecyclePolicy = useQuery({
    queryKey: ['admin', 'governance', 'lifecycle', 'policy'],
    queryFn: () => executeApi(
      () => AdminGovernanceSprint12Service
        .getLifecyclePolicyApiV1AdminGovernanceLifecyclePolicyGet(),
    ),
  })
  const lifecycleRuns = useQuery({
    queryKey: ['admin', 'governance', 'lifecycle', 'runs'],
    queryFn: () => executeApi(
      () => AdminGovernanceSprint12Service
        .listLifecycleRunsApiV1AdminGovernanceLifecycleRunsGet({
          pageSize: 50,
        }),
    ),
  })
  const auditGovernance = useQuery({
    queryKey: ['admin', 'governance', 'audit'],
    queryFn: () => executeApi(
      () => AdminGovernanceService.getAdminAuditGovernanceApiV1AdminAuditGovernanceGet(),
    ),
  })
  const deadLetters = useQuery({
    queryKey: ['admin', 'governance', 'outbox', 'dead-letters'],
    queryFn: () => executeApi(
      () => AdminGovernanceService.listAdminOutboxDeadLettersApiV1AdminOutboxDeadLettersGet({
        pageSize: 50,
      }),
    ),
  })

  const updatePolicy = useMutation({
    mutationFn: (requestBody: LifecyclePolicyUpdateRequest) => executeApi(
      () => AdminGovernanceSprint12Service
        .updateLifecyclePolicyApiV1AdminGovernanceLifecyclePolicyPatch({
          requestBody,
        }),
    ),
    onSuccess: () => {
      setEditingPolicy(false)
      void queryClient.invalidateQueries({
        queryKey: ['admin', 'governance', 'lifecycle'],
      })
    },
  })
  const createLifecycleRun = useMutation({
    mutationFn: (dryRun: boolean) => executeApi(
      () => AdminGovernanceSprint12Service
        .createLifecycleRunApiV1AdminGovernanceLifecycleRunsPost({
          requestBody: {
            dry_run: dryRun,
            limit: 100,
          },
        }),
    ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['admin', 'governance', 'lifecycle', 'runs'],
      })
      void queryClient.invalidateQueries({
        queryKey: ['admin', 'governance', 'overview'],
      })
    },
  })
  const createPermissionRebuild = useMutation({
    mutationFn: (requestBody: PermissionRebuildCreateRequest) => executeApi(
      () => AdminGovernanceSprint12Service
        .createPermissionRebuildApiV1AdminGovernancePermissionRebuildsPost({
          requestBody,
        }),
    ),
    onSuccess: () => {
      setCreatingRebuild(false)
      void queryClient.invalidateQueries({
        queryKey: ['admin', 'governance', 'permission-rebuilds'],
      })
      void queryClient.invalidateQueries({
        queryKey: ['admin', 'governance', 'overview'],
      })
    },
  })
  const retryPermissionRebuild = useMutation({
    mutationFn: (operationId: string) => executeApi(
      () => AdminGovernanceSprint12Service
        .retryPermissionRebuildApiV1AdminGovernancePermissionRebuildsOperationIdRetryPost({
          operationId,
        }),
    ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['admin', 'governance', 'permission-rebuilds'],
      })
      void queryClient.invalidateQueries({
        queryKey: ['admin', 'governance', 'overview'],
      })
    },
  })
  const replay = useMutation({
    mutationFn: (eventId: string) => executeApi(
      () => AdminGovernanceService
        .replayAdminOutboxDeadLetterApiV1AdminOutboxDeadLettersEventIdReplayPost({
          eventId,
        }),
    ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['admin', 'governance', 'outbox'],
      })
      void queryClient.invalidateQueries({
        queryKey: ['admin', 'overview'],
      })
    },
  })

  if (stats.isLoading || maintenance.isLoading || governanceOverview.isLoading) {
    return <LoadingBlock label="正在汇总治理状态…" />
  }
  const primaryError = stats.error ?? maintenance.error ?? governanceOverview.error
  if (primaryError) {
    return (
      <ErrorNotice
        error={primaryError}
        onRetry={() => {
          void stats.refetch()
          void maintenance.refetch()
          void governanceOverview.refetch()
        }}
      />
    )
  }

  const overview = stats.data
  const sprint12Overview = governanceOverview.data
  const tasks = maintenance.data?.tasks ?? []
  const activeAlerts = tasks.filter(
    (task) => task.alert_active || task.stale,
  )
  const outboxDead = overview?.outbox_dead ?? 0

  const runLifecycle = (dryRun: boolean) => {
    if (
      !dryRun
      && !window.confirm('正式执行生命周期策略会清理符合条件的数据，确认继续吗？')
    ) {
      return
    }
    createLifecycleRun.mutate(dryRun)
  }

  return (
    <div className="governance-page">
      <section aria-label="治理摘要" className="governance-metric-grid">
        <GovernanceMetric
          detail={`待投递 ${overview?.outbox_pending ?? 0}`}
          icon={Workflow}
          label="Outbox dead-letter"
          tone={outboxDead > 0 ? 'danger' : 'success'}
          value={String(outboxDead)}
        />
        <GovernanceMetric
          detail={`已完成 ${sprint12Overview?.tree_operations_completed ?? 0}`}
          icon={ListRestart}
          label="大目录后台任务"
          tone={(sprint12Overview?.tree_operations_failed ?? 0) > 0
            ? 'danger'
            : 'success'}
          value={`${sprint12Overview?.tree_operations_pending ?? 0} / ${sprint12Overview?.tree_operations_running ?? 0}`}
        />
        <GovernanceMetric
          detail={`已完成 ${sprint12Overview?.permission_rebuild_completed ?? 0}`}
          icon={DatabaseZap}
          label="权限重算"
          tone={(sprint12Overview?.permission_rebuild_failed ?? 0) > 0
            ? 'danger'
            : 'success'}
          value={`${sprint12Overview?.permission_rebuild_pending ?? 0} / ${sprint12Overview?.permission_rebuild_running ?? 0}`}
        />
        <GovernanceMetric
          detail={`Stale ${sprint12Overview?.maintenance_stale ?? 0}`}
          icon={BellRing}
          label="活跃治理告警"
          tone={(sprint12Overview?.maintenance_alerts ?? 0) > 0
            ? 'danger'
            : 'success'}
          value={String(sprint12Overview?.maintenance_alerts ?? 0)}
        />
      </section>

      <section className="governance-layout">
        <GovernancePanel
          description="持续暴露 Stale、连续失败和 Outbox 积压，不在浏览器复制告警阈值。"
          icon={AlertTriangle}
          title="治理告警"
        >
          <GovernanceAlerts
            activeAlerts={activeAlerts}
            outboxDead={outboxDead}
          />
        </GovernancePanel>

        <GovernancePanel
          description="展示月分区、保留归档、外部日志投递和签名导出状态。"
          icon={Archive}
          title="审计归档与投递"
        >
          {auditGovernance.isLoading ? (
            <LoadingBlock />
          ) : auditGovernance.error ? (
            <ErrorNotice
              error={auditGovernance.error}
              onRetry={() => void auditGovernance.refetch()}
            />
          ) : auditGovernance.data ? (
            <AuditGovernanceSummary value={auditGovernance.data} />
          ) : null}
        </GovernancePanel>

        <GovernancePanel
          action={(
            <button
              className="button secondary"
              onClick={() => setCreatingRebuild(true)}
              type="button"
            >
              <Plus aria-hidden="true" size={16} />
              新建权限重算
            </button>
          )}
          description="查看文件树后台任务进度，并对空间或节点子树执行可恢复权限重算。"
          icon={ListRestart}
          title="大目录任务与权限重算"
          wide
        >
          <div className="governance-subsection">
            <h3>文件树后台任务</h3>
            {treeOperations.isLoading ? (
              <LoadingBlock />
            ) : treeOperations.error ? (
              <ErrorNotice
                error={treeOperations.error}
                onRetry={() => void treeOperations.refetch()}
              />
            ) : (
              <TreeOperationTable items={treeOperations.data?.items ?? []} />
            )}
          </div>
          <div className="governance-subsection">
            <h3>权限重算</h3>
            {permissionRebuilds.isLoading ? (
              <LoadingBlock />
            ) : permissionRebuilds.error ? (
              <ErrorNotice
                error={permissionRebuilds.error}
                onRetry={() => void permissionRebuilds.refetch()}
              />
            ) : (
              <PermissionRebuildTable
                items={permissionRebuilds.data?.items ?? []}
                onRetry={(operationId) => retryPermissionRebuild.mutate(operationId)}
                retrying={retryPermissionRebuild.isPending}
              />
            )}
            {retryPermissionRebuild.error ? (
              <ErrorNotice error={retryPermissionRebuild.error} />
            ) : null}
          </div>
        </GovernancePanel>

        <GovernancePanel
          action={(
            <div className="inline-actions">
              <button
                className="button secondary"
                disabled={createLifecycleRun.isPending}
                onClick={() => setEditingPolicy(true)}
                type="button"
              >
                <Pencil aria-hidden="true" size={15} />
                编辑策略
              </button>
              <button
                className="button secondary"
                disabled={createLifecycleRun.isPending}
                onClick={() => runLifecycle(true)}
                type="button"
              >
                <RefreshCw aria-hidden="true" size={15} />
                Dry-run
              </button>
              <button
                className="button primary"
                disabled={createLifecycleRun.isPending}
                onClick={() => runLifecycle(false)}
                type="button"
              >
                <Play aria-hidden="true" size={15} />
                执行策略
              </button>
            </div>
          )}
          description="租户策略、dry-run 和正式运行均由后端状态机、审计与版本前置条件控制。"
          icon={Clock3}
          title="生命周期策略与运行"
          wide
        >
          {lifecyclePolicy.isLoading || lifecycleRuns.isLoading ? (
            <LoadingBlock />
          ) : lifecyclePolicy.error || lifecycleRuns.error ? (
            <ErrorNotice
              error={lifecyclePolicy.error ?? lifecycleRuns.error}
              onRetry={() => {
                void lifecyclePolicy.refetch()
                void lifecycleRuns.refetch()
              }}
            />
          ) : lifecyclePolicy.data ? (
            <LifecycleSummary
              policy={lifecyclePolicy.data}
              runs={lifecycleRuns.data?.items ?? []}
            />
          ) : null}
          {createLifecycleRun.error ? (
            <ErrorNotice error={createLifecycleRun.error} />
          ) : null}
        </GovernancePanel>

        <GovernancePanel
          description="只展示受控错误摘要和 payload key；重复重放保持幂等。"
          icon={RotateCcw}
          title="Outbox dead-letter"
          wide
        >
          {deadLetters.isLoading ? (
            <LoadingBlock />
          ) : deadLetters.error ? (
            <ErrorNotice
              error={deadLetters.error}
              onRetry={() => void deadLetters.refetch()}
            />
          ) : (
            <DeadLetterTable
              items={deadLetters.data?.items ?? []}
              onReplay={(eventId) => replay.mutate(eventId)}
              replaying={replay.isPending}
            />
          )}
          {replay.data ? (
            <p aria-live="polite" className="governance-result">
              {replay.data.replayed
                ? '事件已重新进入投递队列。'
                : '事件已经被重放，本次请求未产生重复副作用。'}
            </p>
          ) : null}
          {replay.error ? <ErrorNotice error={replay.error} /> : null}
        </GovernancePanel>
      </section>

      {editingPolicy && lifecyclePolicy.data ? (
        <Modal
          onClose={() => setEditingPolicy(false)}
          title="编辑生命周期策略"
        >
          <LifecyclePolicyForm
            disabled={updatePolicy.isPending}
            error={updatePolicy.error}
            onSubmit={(request) => updatePolicy.mutate(request)}
            policy={lifecyclePolicy.data}
          />
        </Modal>
      ) : null}

      {creatingRebuild ? (
        <Modal
          onClose={() => setCreatingRebuild(false)}
          title="新建权限重算"
        >
          <PermissionRebuildForm
            disabled={createPermissionRebuild.isPending}
            error={createPermissionRebuild.error}
            onSubmit={(request) => createPermissionRebuild.mutate(request)}
          />
        </Modal>
      ) : null}
    </div>
  )
}

function GovernanceMetric({
  detail,
  icon: Icon,
  label,
  tone,
  value,
}: {
  detail: string
  icon: LucideIcon
  label: string
  tone: 'danger' | 'success' | 'warning'
  value: string
}) {
  return (
    <article className={`governance-metric ${tone}`}>
      <div>
        <Icon aria-hidden="true" size={18} />
        <span>{label}</span>
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  )
}

function GovernancePanel({
  action,
  children,
  description,
  icon: Icon,
  title,
  wide = false,
}: {
  action?: ReactNode
  children: ReactNode
  description: string
  icon: LucideIcon
  title: string
  wide?: boolean
}) {
  return (
    <section className={`governance-panel${wide ? ' wide' : ''}`}>
      <header>
        <span><Icon aria-hidden="true" size={18} /></span>
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        {action ? <div className="governance-panel-actions">{action}</div> : null}
      </header>
      <div className="governance-panel-body">{children}</div>
    </section>
  )
}

function GovernanceAlerts({
  activeAlerts,
  outboxDead,
}: {
  activeAlerts: Array<{
    alert_active: boolean
    last_status: string
    stale: boolean
    task_name: string
  }>
  outboxDead: number
}) {
  if (activeAlerts.length === 0 && outboxDead === 0) {
    return (
      <div className="governance-healthy">
        <ShieldCheck aria-hidden="true" size={20} />
        <div>
          <strong>当前没有活跃治理告警</strong>
          <span>维护任务与 Outbox 状态均未达到后端告警条件。</span>
        </div>
      </div>
    )
  }
  return (
    <div className="governance-alert-list">
      {outboxDead > 0 ? (
        <article>
          <AlertTriangle aria-hidden="true" size={18} />
          <div>
            <strong>Outbox 存在 {outboxDead} 个 dead 事件</strong>
            <span>检查错误分类后从 dead-letter 页面执行受控重放。</span>
          </div>
        </article>
      ) : null}
      {activeAlerts.map((task) => (
        <article key={task.task_name}>
          <AlertTriangle aria-hidden="true" size={18} />
          <div>
            <strong>{task.task_name}</strong>
            <span>
              {task.stale ? '任务已 Stale' : `连续失败状态 ${task.last_status}`}
            </span>
          </div>
        </article>
      ))}
    </div>
  )
}

function AuditGovernanceSummary({
  value,
}: {
  value: AdminAuditGovernanceResponse
}) {
  const latestArchive = value.recent_archives[0]
  return (
    <div>
      <div className="governance-definition-grid">
        <div>
          <span>分区与保留</span>
          <strong>提前 {value.partition_months_ahead} 个月</strong>
          <small>保留 {value.retention_days} 天</small>
        </div>
        <div>
          <span>归档记录</span>
          <strong>{value.archives_total} 个</strong>
          <small>失败 {value.archives_failed}</small>
        </div>
        <div>
          <span>外部投递</span>
          <StatusBadge tone={value.external_delivery_enabled ? 'success' : 'warning'}>
            {value.external_delivery_enabled ? '已启用' : '未启用'}
          </StatusBadge>
          <small>
            最近成功 {value.last_delivery_succeeded_at
              ? formatDate(value.last_delivery_succeeded_at)
              : '—'}
          </small>
        </div>
        <div>
          <span>Outbox 状态</span>
          <strong>{value.outbox_pending} 待投递</strong>
          <small>failed {value.outbox_failed} · dead {value.outbox_dead}</small>
        </div>
        <p>
          状态生成于 {formatDate(value.generated_at)}
          {value.oldest_pending_at
            ? ` · 最早积压 ${formatDate(value.oldest_pending_at)}`
            : ''}
        </p>
      </div>
      {latestArchive ? (
        <div className="governance-archive-line">
          <Archive aria-hidden="true" size={16} />
          <span>{latestArchive.file_name ?? '归档处理中'}</span>
          <StatusBadge tone={latestArchive.status === 'succeeded' ? 'success' : 'warning'}>
            {latestArchive.status}
          </StatusBadge>
          <small>
            {latestArchive.row_count} 行
            {latestArchive.signature_algorithm
              ? ` · ${latestArchive.signature_algorithm}`
              : ''}
          </small>
        </div>
      ) : null}
    </div>
  )
}

function TreeOperationTable({
  items,
}: {
  items: AdminTreeOperationResponse[]
}) {
  if (items.length === 0) {
    return (
      <EmptyState
        description="当前租户没有大目录后台任务。"
        icon={ShieldCheck}
        title="任务队列为空"
      />
    )
  }
  return (
    <div className="table-plane">
      <div className="table-scroll">
        <table className="data-table governance-table">
          <thead>
            <tr>
              <th>操作</th>
              <th>状态</th>
              <th>进度</th>
              <th>尝试</th>
              <th>释放容量</th>
              <th>更新时间</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>
                  <div className="cell-stack">
                    <strong>{treeOperationLabel(item.operation)}</strong>
                    <span>{item.node_id.slice(0, 8)}</span>
                  </div>
                </td>
                <td>
                  <StatusBadge tone={statusTone(item.status)}>
                    {item.status}
                  </StatusBadge>
                  {item.error_code ? (
                    <p className="governance-cell-error">{item.error_code}</p>
                  ) : null}
                </td>
                <td>
                  <ProgressValue
                    processed={item.processed_count}
                    total={item.total_count}
                  />
                </td>
                <td>{item.attempt_count}</td>
                <td>{formatBytes(item.released_bytes)}</td>
                <td>{formatDate(item.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function PermissionRebuildTable({
  items,
  onRetry,
  retrying,
}: {
  items: PermissionRebuildOperationResponse[]
  onRetry: (operationId: string) => void
  retrying: boolean
}) {
  if (items.length === 0) {
    return (
      <EmptyState
        description="当前租户没有权限重算任务。"
        icon={ShieldCheck}
        title="没有权限重算"
      />
    )
  }
  return (
    <div className="table-plane">
      <div className="table-scroll">
        <table className="data-table governance-table">
          <thead>
            <tr>
              <th>范围</th>
              <th>状态</th>
              <th>进度</th>
              <th>索引</th>
              <th>权限版本</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>
                  <div className="cell-stack">
                    <strong>{item.scope === 'space' ? '整个空间' : '节点子树'}</strong>
                    <span>{(item.root_node_id ?? item.space_id).slice(0, 8)}</span>
                  </div>
                </td>
                <td>
                  <StatusBadge tone={statusTone(item.status)}>
                    {item.status}
                  </StatusBadge>
                  {item.error_code ? (
                    <p className="governance-cell-error">{item.error_code}</p>
                  ) : null}
                </td>
                <td>
                  <ProgressValue
                    processed={item.processed_count}
                    total={item.total_count}
                  />
                </td>
                <td>{item.indexed_count}</td>
                <td>v{item.permission_version}</td>
                <td>
                  {item.status === 'failed' ? (
                    <button
                      className="button secondary compact"
                      disabled={retrying}
                      onClick={() => onRetry(item.id)}
                      type="button"
                    >
                      <RotateCcw aria-hidden="true" size={15} />
                      重试
                    </button>
                  ) : item.restart_requested ? (
                    <StatusBadge tone="warning">等待重启</StatusBadge>
                  ) : (
                    '—'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ProgressValue({
  processed,
  total,
}: {
  processed: number
  total: number
}) {
  const progress = total > 0
    ? Math.min(100, (processed / total) * 100)
    : 0
  return (
    <>
      <div className="governance-progress">
        <span style={{ width: `${progress}%` }} />
      </div>
      <small>{processed} / {total}</small>
    </>
  )
}

function LifecycleSummary({
  policy,
  runs,
}: {
  policy: LifecyclePolicyResponse
  runs: LifecycleRunResponse[]
}) {
  return (
    <div className="governance-lifecycle">
      <div className="governance-policy-grid">
        <div>
          <span>回收站保留</span>
          <strong>{policy.trash_retention_days} 天</strong>
        </div>
        <div>
          <span>预览保留</span>
          <strong>{policy.preview_retention_days} 天</strong>
        </div>
        <div>
          <span>过期清理</span>
          <strong>
            {policy.expire_uploads && policy.expire_shares ? '已启用' : '部分启用'}
          </strong>
        </div>
        <div>
          <span>孤儿对象</span>
          <strong>{policy.cleanup_orphaned_objects ? '正式清理' : '仅审计'}</strong>
        </div>
      </div>
      {runs.length === 0 ? (
        <EmptyState
          description="当前策略还没有运行记录。"
          icon={Clock3}
          title="没有生命周期运行"
        />
      ) : (
        <div className="table-plane">
          <div className="table-scroll">
            <table className="data-table governance-table">
              <thead>
                <tr>
                  <th>模式</th>
                  <th>状态</th>
                  <th>策略版本</th>
                  <th>结果</th>
                  <th>创建时间</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td>{run.dry_run ? 'Dry-run' : '正式执行'}</td>
                    <td>
                      <StatusBadge tone={statusTone(run.status)}>
                        {run.status}
                      </StatusBadge>
                    </td>
                    <td>v{run.policy_version}</td>
                    <td>{run.error_code ?? resultSummary(run.result)}</td>
                    <td>{formatDate(run.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function LifecyclePolicyForm({
  disabled,
  error,
  onSubmit,
  policy,
}: {
  disabled: boolean
  error: unknown
  onSubmit: (request: LifecyclePolicyUpdateRequest) => void
  policy: LifecyclePolicyResponse
}) {
  const [request, setRequest] = useState<LifecyclePolicyUpdateRequest>({
    cleanup_orphaned_objects: policy.cleanup_orphaned_objects,
    cleanup_unreferenced_blobs: policy.cleanup_unreferenced_blobs,
    expected_version: policy.version,
    expire_shares: policy.expire_shares,
    expire_uploads: policy.expire_uploads,
    preview_retention_days: policy.preview_retention_days,
    trash_retention_days: policy.trash_retention_days,
  })
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSubmit(request)
  }
  return (
    <form className="stack-form" onSubmit={submit}>
      <div className="form-grid">
        <label>
          回收站保留天数
          <input
            max={3650}
            min={1}
            onChange={(event) => setRequest({
              ...request,
              trash_retention_days: Number(event.target.value),
            })}
            required
            type="number"
            value={request.trash_retention_days}
          />
        </label>
        <label>
          预览保留天数
          <input
            max={3650}
            min={1}
            onChange={(event) => setRequest({
              ...request,
              preview_retention_days: Number(event.target.value),
            })}
            required
            type="number"
            value={request.preview_retention_days}
          />
        </label>
      </div>
      <PolicyCheckbox
        checked={Boolean(request.expire_uploads)}
        label="清理过期上传"
        onChange={(checked) => setRequest({ ...request, expire_uploads: checked })}
      />
      <PolicyCheckbox
        checked={Boolean(request.expire_shares)}
        label="失效过期分享"
        onChange={(checked) => setRequest({ ...request, expire_shares: checked })}
      />
      <PolicyCheckbox
        checked={Boolean(request.cleanup_unreferenced_blobs)}
        label="清理无引用 Blob"
        onChange={(checked) => setRequest({
          ...request,
          cleanup_unreferenced_blobs: checked,
        })}
      />
      <PolicyCheckbox
        checked={Boolean(request.cleanup_orphaned_objects)}
        label="正式清理孤儿对象"
        onChange={(checked) => setRequest({
          ...request,
          cleanup_orphaned_objects: checked,
        })}
      />
      {error ? <ErrorNotice error={error} /> : null}
      <button className="button primary" disabled={disabled} type="submit">
        保存策略
      </button>
    </form>
  )
}

function PolicyCheckbox({
  checked,
  label,
  onChange,
}: {
  checked: boolean
  label: string
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="checkbox-field">
      <input
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        type="checkbox"
      />
      {label}
    </label>
  )
}

function PermissionRebuildForm({
  disabled,
  error,
  onSubmit,
}: {
  disabled: boolean
  error: unknown
  onSubmit: (request: PermissionRebuildCreateRequest) => void
}) {
  const [request, setRequest] = useState<PermissionRebuildCreateRequest>({
    root_node_id: null,
    scope: 'space',
    space_id: '',
  })
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSubmit({
      ...request,
      root_node_id: request.scope === 'node'
        ? request.root_node_id
        : null,
    })
  }
  return (
    <form className="stack-form" onSubmit={submit}>
      <label>
        重算范围
        <select
          onChange={(event) => setRequest({
            ...request,
            scope: event.target.value as PermissionRebuildCreateRequest['scope'],
          })}
          value={request.scope}
        >
          <option value="space">整个空间</option>
          <option value="node">节点子树</option>
        </select>
      </label>
      <label>
        Space ID
        <input
          onChange={(event) => setRequest({
            ...request,
            space_id: event.target.value,
          })}
          required
          value={request.space_id}
        />
      </label>
      {request.scope === 'node' ? (
        <label>
          Root Node ID
          <input
            onChange={(event) => setRequest({
              ...request,
              root_node_id: event.target.value,
            })}
            required
            value={request.root_node_id ?? ''}
          />
        </label>
      ) : null}
      <p className="form-hint">
        服务端会重新加载空间和节点事实，并以可恢复后台任务批量重建权限与搜索 ACL。
      </p>
      {error ? <ErrorNotice error={error} /> : null}
      <button className="button primary" disabled={disabled} type="submit">
        创建权限重算
      </button>
    </form>
  )
}

function DeadLetterTable({
  items,
  onReplay,
  replaying,
}: {
  items: AdminOutboxDeadLetterResponse[]
  onReplay: (eventId: string) => void
  replaying: boolean
}) {
  if (items.length === 0) {
    return (
      <EmptyState
        description="当前租户没有需要人工处理的 dead-letter。"
        icon={ShieldCheck}
        title="Outbox 队列正常"
      />
    )
  }
  return (
    <div className="table-plane">
      <div className="table-scroll">
        <table className="data-table governance-table">
          <thead>
            <tr>
              <th>事件</th>
              <th>错误分类</th>
              <th>重试</th>
              <th>Payload keys</th>
              <th>进入 dead</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>
                  <div className="cell-stack">
                    <strong>{item.event_type}</strong>
                    <span>{item.id.slice(0, 8)}</span>
                  </div>
                </td>
                <td>
                  <div className="cell-stack">
                    <strong>{item.last_error_kind ?? 'unknown'}</strong>
                    <span>{item.last_error_code ?? '—'}</span>
                  </div>
                </td>
                <td>{item.retry_count} / 重放 {item.replay_count}</td>
                <td>{item.payload_keys.join(', ') || '—'}</td>
                <td>{item.dead_at ? formatDate(item.dead_at) : '—'}</td>
                <td>
                  <button
                    className="button secondary compact"
                    disabled={replaying}
                    onClick={() => onReplay(item.id)}
                    type="button"
                  >
                    <RotateCcw aria-hidden="true" size={15} />
                    重放
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function treeOperationLabel(operation: AdminTreeOperationResponse['operation']) {
  if (operation === 'delete') return '删除'
  if (operation === 'restore') return '恢复'
  return '彻底删除'
}

function resultSummary(result: Record<string, unknown>) {
  const entries = Object.entries(result)
    .filter(([, value]) => typeof value === 'number')
    .slice(0, 2)
  return entries.length > 0
    ? entries.map(([key, value]) => `${key} ${value}`).join(' · ')
    : '—'
}

function statusTone(
  status:
    | AdminTreeOperationResponse['status']
    | LifecycleRunResponse['status']
    | PermissionRebuildOperationResponse['status'],
): 'danger' | 'info' | 'neutral' | 'success' | 'warning' {
  if (status === 'completed' || status === 'succeeded') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'info'
  if (status === 'pending') return 'warning'
  return 'neutral'
}
