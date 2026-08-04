import {
  BarChart3,
  Building2,
  ClipboardList,
  Database,
  Download,
  Gauge,
  Layers3,
  ListChecks,
  Plus,
  RefreshCw,
  Shield,
  Users,
  Wrench,
} from 'lucide-react'
import {
  useState,
  type ReactNode,
} from 'react'
import {
  Link,
  useRouterState,
} from '@tanstack/react-router'
import { useMutation, useQuery } from '@tanstack/react-query'

import {
  AdminGovernanceService,
  AdminOrganizationService,
  AdminQuotasService,
  AdminService,
  AdminSpacesService,
} from '../../api/generated'
import { executeApi } from '../../api/runtime'
import {
  EmptyState,
  ErrorNotice,
  LoadingBlock,
  Modal,
  PageHeader,
  StatusBadge,
} from '../../components/ui'
import { formatBytes, formatDate } from '../../lib/format'
import { queryClient } from '../../app/query-client'

const tabs = [
  { label: '概览', icon: BarChart3, to: '/admin' },
  { label: '用户', icon: Users, to: '/admin/users' },
  { label: '部门与组', icon: Building2, to: '/admin/organization' },
  { label: '空间', icon: Layers3, to: '/admin/spaces' },
  { label: '配额', icon: Gauge, to: '/admin/quotas' },
  { label: '审计', icon: Shield, to: '/admin/audit' },
  { label: '维护', icon: Wrench, to: '/admin/maintenance' },
  { label: '导出', icon: Download, to: '/admin/exports' },
]

export function AdminPage() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const section = pathname.split('/')[2] ?? 'overview'
  return (
    <div className="page-stack admin-page">
      <PageHeader
        description="管理员页面只提供操作入口，租户隔离、版本前置条件和审计仍由后端执行。"
        eyebrow="治理控制台"
        title="管理后台"
      />
      <nav className="admin-tabs" aria-label="管理后台导航">
        {tabs.map(({ icon: Icon, label, to }) => (
          <Link className={pathname === to || (to !== '/admin' && pathname.startsWith(to)) ? 'active' : ''} key={to} to={to}>
            <Icon size={16} /> {label}
          </Link>
        ))}
      </nav>
      {section === 'overview' ? <AdminOverview /> : null}
      {section === 'users' ? <AdminUsers /> : null}
      {section === 'organization' ? <AdminOrganization /> : null}
      {section === 'spaces' ? <AdminSpaces /> : null}
      {section === 'quotas' ? <AdminQuotas /> : null}
      {section === 'audit' ? <AdminAudit /> : null}
      {section === 'maintenance' ? <AdminMaintenance /> : null}
      {section === 'exports' ? <AdminExports /> : null}
    </div>
  )
}

function AdminOverview() {
  const stats = useQuery({
    queryKey: ['admin', 'overview'],
    queryFn: () => executeApi(() => AdminGovernanceService.getAdminOverviewStatsApiV1AdminStatsOverviewGet()),
  })
  const maintenance = useQuery({
    queryKey: ['admin', 'maintenance', 'tasks'],
    queryFn: () => executeApi(() => AdminGovernanceService.getAdminMaintenanceTasksApiV1AdminMaintenanceTasksGet()),
  })
  if (stats.isLoading) return <LoadingBlock label="正在汇总治理指标…" />
  if (stats.error) return <ErrorNotice error={stats.error} onRetry={() => void stats.refetch()} />
  const value = stats.data
  if (!value) return null
  const cards = [
    ['活跃用户', `${value.users_active} / ${value.users_total}`, Users],
    ['空间与节点', `${value.spaces_active} / ${value.nodes_total}`, Database],
    ['存储使用', formatBytes(value.stored_bytes), Layers3],
    ['待处理任务', `${value.pending_uploads + value.outbox_pending}`, ListChecks],
  ] as const
  return (
    <>
      <section className="metric-grid">
        {cards.map(([label, amount, Icon]) => <article className="metric-panel" key={label}><Icon size={19} /><span>{label}</span><strong>{amount}</strong></article>)}
      </section>
      <section className="split-grid">
        <div className="table-plane">
          <div className="section-heading"><div><h2>配额概览</h2><p>当前租户已用容量与上限。</p></div></div>
          <div className="quota-meter"><span style={{ width: `${Math.min(100, value.quota_limit_bytes ? (value.quota_used_bytes / value.quota_limit_bytes) * 100 : 0)}%` }} /></div>
          <div className="quota-line"><strong>{formatBytes(value.quota_used_bytes)}</strong><span>上限 {formatBytes(value.quota_limit_bytes)}</span></div>
        </div>
        <div className="table-plane">
          <div className="section-heading"><div><h2>维护健康</h2><p>过期任务和连续失败会在这里暴露。</p></div></div>
          {maintenance.data?.tasks.slice(0, 5).map((task) => <div className="health-row" key={task.task_name}><span>{task.task_name}</span><StatusBadge tone={task.alert_active || task.stale ? 'danger' : 'success'}>{task.last_status}</StatusBadge></div>)}
        </div>
      </section>
    </>
  )
}

function AdminUsers() {
  const [create, setCreate] = useState(false)
  const users = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: () => executeApi(() => AdminOrganizationService.listAdminUsersApiV1AdminUsersGet({ pageSize: 50 })),
  })
  const add = useMutation({
    mutationFn: (payload: { display_name: string; password: string; username: string }) => executeApi(() => AdminOrganizationService.createAdminUserApiV1AdminUsersPost({ requestBody: payload })),
    onSuccess: () => { setCreate(false); void queryClient.invalidateQueries({ queryKey: ['admin', 'users'] }) },
  })
  return (
    <AdminSection
      action={<button className="button primary" onClick={() => setCreate(true)} type="button"><Plus size={16} /> 新建用户</button>}
      description="用户生命周期、管理员标记和版本更新都由管理 API 控制。"
      title="用户"
    >
      <AdminTable
        columns={['用户', '状态', '权限', '版本', '更新时间']}
        empty="还没有用户记录。"
        error={users.error}
        loading={users.isLoading}
        rows={(users.data?.items ?? []).map((user) => ({
          cells: [<div className="cell-stack"><strong>{user.display_name}</strong><span>{user.username}</span></div>, <StatusBadge tone={user.is_active ? 'success' : 'warning'}>{user.is_active ? '启用' : '停用'}</StatusBadge>, user.is_super_admin ? <StatusBadge tone="info">超级管理员</StatusBadge> : '普通用户', user.version, formatDate(user.updated_at)],
          id: user.id,
        }))}
      />
      {create ? <Modal onClose={() => setCreate(false)} title="新建用户"><CreateUserForm onSubmit={(payload) => void add.mutateAsync(payload)} /></Modal> : null}
    </AdminSection>
  )
}

function AdminOrganization() {
  const [mode, setMode] = useState<'departments' | 'groups'>('departments')
  const departments = useQuery({ queryKey: ['admin', 'departments'], queryFn: () => executeApi(() => AdminOrganizationService.listAdminDepartmentsApiV1AdminDepartmentsGet({ pageSize: 50 })) })
  const groups = useQuery({ queryKey: ['admin', 'groups'], queryFn: () => executeApi(() => AdminOrganizationService.listAdminGroupsApiV1AdminGroupsGet({ pageSize: 50 })) })
  const items = mode === 'departments' ? departments.data?.items ?? [] : groups.data?.items ?? []
  return (
    <AdminSection description="组织对象用于内部分享与 ACL 授权，查询结果来自租户隔离的管理 API。" title="部门与用户组">
      <div className="segmented-control"><button className={mode === 'departments' ? 'active' : ''} onClick={() => setMode('departments')} type="button">部门</button><button className={mode === 'groups' ? 'active' : ''} onClick={() => setMode('groups')} type="button">用户组</button></div>
      <AdminTable
        columns={mode === 'departments' ? ['名称', '路径', '状态', '版本'] : ['名称', '标识', '状态', '版本']}
        empty="没有组织对象。"
        error={mode === 'departments' ? departments.error : groups.error}
        loading={mode === 'departments' ? departments.isLoading : groups.isLoading}
        rows={items.map((item) => ({
          cells: mode === 'departments'
            ? [<strong key="name">{item.name}</strong>, 'path' in item ? item.path : '', <StatusBadge tone={item.status === 'active' ? 'success' : 'warning'}>{item.status}</StatusBadge>, item.version]
            : [<strong key="name">{item.name}</strong>, 'slug' in item ? item.slug : '', <StatusBadge tone={item.status === 'active' ? 'success' : 'warning'}>{item.status}</StatusBadge>, item.version],
          id: item.id,
        }))}
      />
    </AdminSection>
  )
}

function AdminSpaces() {
  const spaces = useQuery({ queryKey: ['admin', 'spaces'], queryFn: () => executeApi(() => AdminSpacesService.listAdminSpacesApiV1AdminSpacesGet({ pageSize: 50 })) })
  return <AdminSection description="空间 owner、容量和成员数量是空间治理的核心视图。" title="空间"><AdminTable columns={['空间', '类型', '成员', '节点', '容量']} empty="没有空间。" error={spaces.error} loading={spaces.isLoading} rows={(spaces.data?.items ?? []).map((space) => ({ cells: [<div className="cell-stack"><strong>{space.name}</strong><span>{space.slug}</span></div>, space.space_type, space.member_count, space.node_count, `${formatBytes(space.used_bytes)} / ${formatBytes(space.limit_bytes)}`], id: space.id }))} /></AdminSection>
}

function AdminQuotas() {
  const accounts = useQuery({ queryKey: ['admin', 'quota-accounts'], queryFn: () => executeApi(() => AdminQuotasService.listQuotaAccountsApiV1AdminQuotasAccountsGet({ pageSize: 50 })) })
  const policies = useQuery({ queryKey: ['admin', 'quota-policies'], queryFn: () => executeApi(() => AdminQuotasService.listQuotaPoliciesApiV1AdminQuotasPoliciesGet({ pageSize: 50 })) })
  return <AdminSection description="容量账本和策略由后端原子更新，前端只显示剩余容量与策略状态。" title="配额"><div className="split-grid"><div><h2 className="subheading">账户</h2><AdminTable columns={['owner', '上限', '已用', '剩余']} empty="没有账户。" error={accounts.error} loading={accounts.isLoading} rows={(accounts.data?.items ?? []).map((account) => ({ cells: [account.owner_type, formatBytes(account.limit_bytes), formatBytes(account.used_bytes), formatBytes(account.remaining_bytes)], id: account.id }))} /></div><div><h2 className="subheading">策略</h2><AdminTable columns={['名称', '优先级', '上限', '状态']} empty="没有策略。" error={policies.error} loading={policies.isLoading} rows={(policies.data?.items ?? []).map((policy) => ({ cells: [policy.name, policy.priority, formatBytes(policy.limit_bytes), <StatusBadge tone={policy.is_active ? 'success' : 'warning'}>{policy.is_active ? '启用' : '停用'}</StatusBadge>], id: policy.id }))} /></div></div></AdminSection>
}

function AdminAudit() {
  const audit = useQuery({ queryKey: ['admin', 'audit'], queryFn: () => executeApi(() => AdminService.listAdminAuditLogsApiV1AdminAuditLogsGet({ pageSize: 50 })) })
  return <AdminSection description="审计事件保留 request_id、结果和风险等级，方便从用户操作回溯到 API 请求。" title="审计日志"><AdminTable columns={['动作', '资源', '结果', '风险', '时间']} empty="没有审计记录。" error={audit.error} loading={audit.isLoading} rows={(audit.data?.items ?? []).map((item) => ({ cells: [item.action, `${item.resource_type} ${item.resource_id?.slice(0, 8) ?? ''}`, item.result, item.risk_level, formatDate(item.created_at)], id: item.id }))} /></AdminSection>
}

function AdminMaintenance() {
  const tasks = useQuery({ queryKey: ['admin', 'maintenance', 'tasks'], queryFn: () => executeApi(() => AdminGovernanceService.getAdminMaintenanceTasksApiV1AdminMaintenanceTasksGet()) })
  const runs = useQuery({ queryKey: ['admin', 'maintenance', 'runs'], queryFn: () => executeApi(() => AdminGovernanceService.listAdminMaintenanceRunsApiV1AdminMaintenanceRunsGet({ pageSize: 50 })) })
  const run = useMutation({ mutationFn: () => executeApi(() => AdminGovernanceService.createAdminMaintenanceRunApiV1AdminMaintenanceRunsPost({ requestBody: { task_name: 'quota.reconcile_space_usage', dry_run: true } })), onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['admin', 'maintenance'] }) })
  return <AdminSection action={<button className="button primary" onClick={() => void run.mutateAsync()} type="button"><RefreshIcon /> 运行校准</button>} description="异步维护任务有持久化状态，重复点击不会把任务状态藏在浏览器里。" title="维护任务"><div className="health-list">{(tasks.data?.tasks ?? []).map((task) => <div className="health-row" key={task.task_name}><span>{task.task_name}</span><StatusBadge tone={task.alert_active || task.stale ? 'danger' : 'success'}>{task.last_status}</StatusBadge></div>)}</div><AdminTable columns={['任务', '状态', '创建时间', '错误']} empty="没有运行记录。" error={runs.error} loading={runs.isLoading} rows={(runs.data?.items ?? []).map((item) => ({ cells: [item.operation, <StatusBadge tone={item.status === 'succeeded' ? 'success' : item.status === 'failed' ? 'danger' : 'info'}>{item.status}</StatusBadge>, formatDate(item.created_at), item.error_code ?? '—'], id: item.id }))} /></AdminSection>
}

function AdminExports() {
  const [resource, setResource] = useState<'audit_logs' | 'spaces' | 'users'>('users')
  const exports = useQuery({ queryKey: ['admin', 'exports'], queryFn: () => executeApi(() => AdminGovernanceService.listAdminExportsApiV1AdminExportsGet({ pageSize: 50 })) })
  const create = useMutation({ mutationFn: () => executeApi(() => AdminGovernanceService.createAdminExportApiV1AdminExportsPost({ requestBody: { resource } })), onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['admin', 'exports'] }) })
  return <AdminSection action={<div className="page-actions"><select aria-label="导出资源" onChange={(event) => setResource(event.target.value as typeof resource)} value={resource}><option value="users">用户</option><option value="spaces">空间</option><option value="audit_logs">审计日志</option></select><button className="button primary" onClick={() => void create.mutateAsync()} type="button"><Download size={16} /> 创建导出</button></div>} description="大规模 CSV 通过后端异步任务生成，不在浏览器拼接全量数据。" title="异步导出"><AdminTable columns={['资源', '状态', '文件', '大小', '更新时间']} empty="没有导出任务。" error={exports.error} loading={exports.isLoading} rows={(exports.data?.items ?? []).map((item) => ({ cells: [item.operation, <StatusBadge tone={item.status === 'succeeded' ? 'success' : item.status === 'failed' ? 'danger' : 'info'}>{item.status}</StatusBadge>, item.file_name ?? '—', formatBytes(item.size_bytes), formatDate(item.updated_at)], id: item.id }))} /></AdminSection>
}

function AdminSection({ action, children, description, title }: { action?: ReactNode; children: ReactNode; description: string; title: string }) {
  return <section className="admin-section"><div className="section-heading"><div><h2>{title}</h2><p>{description}</p></div>{action ? <div className="page-actions">{action}</div> : null}</div>{children}</section>
}

function AdminTable({ columns, empty, error, loading, rows }: { columns: string[]; empty: string; error: unknown; loading: boolean; rows: Array<{ cells: ReactNode[]; id: string }> }) {
  if (loading) return <LoadingBlock />
  if (error) return <ErrorNotice error={error} />
  if (!rows.length) return <EmptyState description={empty} icon={ClipboardList} title="没有数据" />
  return <div className="table-plane"><div className="table-scroll"><table className="data-table"><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={row.id}>{row.cells.map((cell, index) => <td key={`${row.id}-${index}`}>{cell}</td>)}</tr>)}</tbody></table></div></div>
}

function CreateUserForm({ onSubmit }: { onSubmit: (payload: { display_name: string; password: string; username: string }) => void }) {
  const [payload, setPayload] = useState({ display_name: '', password: '', username: '' })
  return <form className="stack-form" onSubmit={(event) => { event.preventDefault(); onSubmit(payload) }}><label>显示名称<input onChange={(event) => setPayload({ ...payload, display_name: event.target.value })} required value={payload.display_name} /></label><label>用户名<input onChange={(event) => setPayload({ ...payload, username: event.target.value })} required value={payload.username} /></label><label>初始密码<input minLength={12} onChange={(event) => setPayload({ ...payload, password: event.target.value })} required type="password" value={payload.password} /></label><button className="button primary" type="submit">创建用户</button></form>
}

function RefreshIcon() {
  return <RefreshCw size={16} />
}
