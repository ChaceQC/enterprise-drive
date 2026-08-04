import {
  Braces,
  CloudCog,
  Network,
  Plus,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  useMemo,
  useState,
  type FormEvent,
} from 'react'

import {
  AdminIdentityService,
  type LdapSourceCreateRequest,
  type LdapSourceResponse,
  type LdapSyncRequest,
  type OidcProviderCreateRequest,
  type OidcProviderResponse,
} from '../../api/generated'
import { executeApi } from '../../api/runtime'
import {
  EmptyState,
  ErrorNotice,
  LoadingBlock,
  Modal,
  StatusBadge,
} from '../../components/ui'
import { formatDate } from '../../lib/format'
import { queryClient } from '../../app/query-client'

const ldapModeLabels: Record<LdapSyncRequest['mode'], string> = {
  dry_run: 'Dry-run',
  full: '全量',
  incremental: '增量',
}

const initialOidcDraft: OidcProviderCreateRequest = {
  client_id: '',
  client_secret_ref: null,
  enabled: true,
  issuer_url: '',
  name: '',
  scopes: ['openid', 'profile', 'email'],
  slug: '',
}

type LdapDraft = Omit<LdapSourceCreateRequest, 'attribute_mapping'> & {
  attributeMappingText: string
}

const initialLdapDraft: LdapDraft = {
  attributeMappingText: JSON.stringify({
    user_display_name: 'displayName',
    user_external_id: 'entryUUID',
    user_username: 'uid',
  }, null, 2),
  base_dn: '',
  bind_dn: null,
  bind_password_ref: null,
  department_base_dn: null,
  department_filter: null,
  enabled: true,
  group_base_dn: null,
  group_filter: null,
  name: '',
  server_url: 'ldaps://',
  slug: '',
  user_base_dn: '',
  user_filter: '(objectClass=person)',
}

function runTone(status: string) {
  if (status === 'succeeded') return 'success' as const
  if (status === 'failed') return 'danger' as const
  return 'info' as const
}

function formatRunStats(stats: Record<string, number>) {
  const entries = Object.entries(stats)
  return entries.length
    ? entries.map(([key, value]) => `${key} ${value}`).join(' · ')
    : '尚无统计'
}

function parseAttributeMapping(value: string): Record<string, string> {
  const parsed: unknown = JSON.parse(value)
  if (
    typeof parsed !== 'object'
    || parsed === null
    || Array.isArray(parsed)
    || Object.values(parsed).some((item) => typeof item !== 'string')
  ) {
    throw new Error('属性映射必须是值均为字符串的 JSON 对象。')
  }
  return parsed as Record<string, string>
}

export function AdminIdentityPage() {
  const [showOidcCreate, setShowOidcCreate] = useState(false)
  const [showLdapCreate, setShowLdapCreate] = useState(false)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [oidcTest, setOidcTest] = useState<{
    id: string
    message: string
  } | null>(null)
  const [ldapTest, setLdapTest] = useState<{
    id: string
    message: string
  } | null>(null)

  const oidcProviders = useQuery({
    queryKey: ['admin', 'identity', 'oidc-providers'],
    queryFn: () => executeApi(
      () => AdminIdentityService.listOidcProvidersApiV1AdminIdentityOidcProvidersGet(),
    ),
  })
  const ldapSources = useQuery({
    queryKey: ['admin', 'identity', 'ldap-sources'],
    queryFn: () => executeApi(
      () => AdminIdentityService.listLdapSourcesApiV1AdminIdentityLdapSourcesGet(),
    ),
  })
  const ldapRuns = useQuery({
    queryKey: ['admin', 'identity', 'ldap-runs'],
    queryFn: () => executeApi(
      () => AdminIdentityService.listLdapSyncRunsApiV1AdminIdentityLdapRunsGet({
        limit: 50,
      }),
    ),
  })
  const conflicts = useQuery({
    queryKey: ['admin', 'identity', 'ldap-conflicts', selectedRunId],
    queryFn: () => executeApi(
      () => AdminIdentityService.listLdapSyncConflictsApiV1AdminIdentityLdapRunsRunIdConflictsGet({
        runId: selectedRunId!,
      }),
    ),
    enabled: selectedRunId !== null,
  })

  const sourceNames = useMemo(
    () => new Map(
      (ldapSources.data?.items ?? []).map((source) => [source.id, source.name]),
    ),
    [ldapSources.data?.items],
  )

  const createOidc = useMutation({
    mutationFn: (requestBody: OidcProviderCreateRequest) => executeApi(
      () => AdminIdentityService.createOidcProviderApiV1AdminIdentityOidcProvidersPost({
        requestBody,
      }),
    ),
    onSuccess: async () => {
      setShowOidcCreate(false)
      await queryClient.invalidateQueries({
        queryKey: ['admin', 'identity', 'oidc-providers'],
      })
      await queryClient.invalidateQueries({
        queryKey: ['public-oidc-providers'],
      })
    },
  })
  const toggleOidc = useMutation({
    mutationFn: (provider: OidcProviderResponse) => executeApi(
      () => AdminIdentityService.updateOidcProviderApiV1AdminIdentityOidcProvidersProviderIdPatch({
        providerId: provider.id,
        requestBody: {
          enabled: !provider.enabled,
          expected_version: provider.version,
        },
      }),
    ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['admin', 'identity', 'oidc-providers'],
      })
      await queryClient.invalidateQueries({
        queryKey: ['public-oidc-providers'],
      })
    },
  })
  const testOidc = useMutation({
    mutationFn: (provider: OidcProviderResponse) => executeApi(
      () => AdminIdentityService.testOidcProviderApiV1AdminIdentityOidcProvidersProviderIdTestPost({
        providerId: provider.id,
      }),
    ),
    onSuccess: (result, provider) => {
      setOidcTest({
        id: provider.id,
        message: `发现文档连接成功 · issuer ${result.issuer} · ${result.supports_logout ? '支持 RP logout' : '未声明 RP logout'}`,
      })
    },
  })

  const createLdap = useMutation({
    mutationFn: (requestBody: LdapSourceCreateRequest) => executeApi(
      () => AdminIdentityService.createLdapSourceApiV1AdminIdentityLdapSourcesPost({
        requestBody,
      }),
    ),
    onSuccess: async () => {
      setShowLdapCreate(false)
      await queryClient.invalidateQueries({
        queryKey: ['admin', 'identity', 'ldap-sources'],
      })
    },
  })
  const toggleLdap = useMutation({
    mutationFn: (source: LdapSourceResponse) => executeApi(
      () => AdminIdentityService.updateLdapSourceApiV1AdminIdentityLdapSourcesSourceIdPatch({
        sourceId: source.id,
        requestBody: {
          enabled: !source.enabled,
          expected_version: source.version,
        },
      }),
    ),
    onSuccess: () => queryClient.invalidateQueries({
      queryKey: ['admin', 'identity', 'ldap-sources'],
    }),
  })
  const testLdap = useMutation({
    mutationFn: (source: LdapSourceResponse) => executeApi(
      () => AdminIdentityService.testLdapSourceApiV1AdminIdentityLdapSourcesSourceIdTestPost({
        sourceId: source.id,
      }),
    ),
    onSuccess: (result, source) => {
      setLdapTest({
        id: source.id,
        message: `连接成功 · ${result.server} · ${result.base_dn_found ? '已找到 Base DN' : '未找到 Base DN'}`,
      })
    },
  })
  const startSync = useMutation({
    mutationFn: ({
      mode,
      sourceId,
    }: {
      mode: LdapSyncRequest['mode']
      sourceId: string
    }) => executeApi(
      () => AdminIdentityService.startLdapSyncApiV1AdminIdentityLdapSourcesSourceIdSyncPost({
        sourceId,
        requestBody: { mode },
      }),
    ),
    onSuccess: async () => {
      setSelectedRunId(null)
      await queryClient.invalidateQueries({
        queryKey: ['admin', 'identity', 'ldap-runs'],
      })
    },
  })

  return (
    <>
      <section className="admin-section identity-admin-section">
        <div className="section-heading">
          <div>
            <h2><CloudCog size={18} /> OIDC Provider</h2>
            <p>通过发现文档、PKCE、state 和 nonce 接入企业单点登录；密钥值不会返回浏览器。</p>
          </div>
          <button
            className="button primary"
            onClick={() => setShowOidcCreate(true)}
            type="button"
          >
            <Plus size={16} /> 新建 OIDC Provider
          </button>
        </div>
        {oidcProviders.isLoading ? <LoadingBlock label="正在加载 OIDC Provider…" /> : null}
        {oidcProviders.error ? (
          <ErrorNotice
            error={oidcProviders.error}
            onRetry={() => void oidcProviders.refetch()}
          />
        ) : null}
        {!oidcProviders.isLoading
        && !oidcProviders.error
        && !oidcProviders.data?.items.length ? (
          <EmptyState
            description="创建 Provider 后，启用项会出现在登录页和账号绑定入口。"
            icon={CloudCog}
            title="尚未配置 OIDC"
          />
          ) : null}
        {(oidcProviders.data?.items.length ?? 0) > 0 ? (
          <div className="table-plane">
            <div className="table-scroll">
              <table className="data-table identity-table">
                <thead>
                  <tr>
                    <th>Provider</th>
                    <th>Issuer / Client</th>
                    <th>密钥</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {oidcProviders.data?.items.map((provider) => (
                    <tr key={provider.id}>
                      <td>
                        <div className="cell-stack">
                          <strong>{provider.name}</strong>
                          <span>{provider.slug} · v{provider.version}</span>
                        </div>
                      </td>
                      <td>
                        <div className="cell-stack">
                          <strong>{provider.issuer_url}</strong>
                          <span>{provider.client_id} · {provider.scopes.join(' ')}</span>
                        </div>
                      </td>
                      <td>
                        <StatusBadge tone={provider.client_secret_configured ? 'success' : 'warning'}>
                          {provider.client_secret_configured ? '已配置' : '未配置'}
                        </StatusBadge>
                      </td>
                      <td>
                        <StatusBadge tone={provider.enabled ? 'success' : 'warning'}>
                          {provider.enabled ? '启用' : '停用'}
                        </StatusBadge>
                      </td>
                      <td>
                        <div className="inline-actions">
                          <button
                            className="text-button"
                            disabled={testOidc.isPending}
                            onClick={() => void testOidc.mutateAsync(provider)}
                            type="button"
                          >
                            <ShieldCheck size={15} /> 测试连接
                          </button>
                          <button
                            className="text-button"
                            disabled={toggleOidc.isPending}
                            onClick={() => void toggleOidc.mutateAsync(provider)}
                            type="button"
                          >
                            {provider.enabled ? '停用' : '启用'}
                          </button>
                        </div>
                        {oidcTest?.id === provider.id ? (
                          <p className="inline-result" role="status">{oidcTest.message}</p>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
        {toggleOidc.error ? <ErrorNotice error={toggleOidc.error} /> : null}
        {testOidc.error ? <ErrorNotice error={testOidc.error} /> : null}
      </section>

      <section className="admin-section identity-admin-section">
        <div className="section-heading">
          <div>
            <h2><Network size={18} /> LDAP 身份源</h2>
            <p>凭据只保存环境变量引用；先测试连接或 dry-run，再执行增量或全量同步。</p>
          </div>
          <button
            className="button primary"
            onClick={() => setShowLdapCreate(true)}
            type="button"
          >
            <Plus size={16} /> 新建 LDAP 身份源
          </button>
        </div>
        {ldapSources.isLoading ? <LoadingBlock label="正在加载 LDAP 身份源…" /> : null}
        {ldapSources.error ? (
          <ErrorNotice
            error={ldapSources.error}
            onRetry={() => void ldapSources.refetch()}
          />
        ) : null}
        {!ldapSources.isLoading
        && !ldapSources.error
        && !ldapSources.data?.items.length ? (
          <EmptyState
            description="配置 LDAPS 目录、查询范围和稳定外部 ID 映射后再开始同步。"
            icon={Network}
            title="尚未配置 LDAP"
          />
          ) : null}
        {(ldapSources.data?.items.length ?? 0) > 0 ? (
          <div className="table-plane">
            <div className="table-scroll">
              <table className="data-table identity-table">
                <thead>
                  <tr>
                    <th>身份源</th>
                    <th>目录范围</th>
                    <th>绑定凭据</th>
                    <th>同步状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {ldapSources.data?.items.map((source) => (
                    <tr key={source.id}>
                      <td>
                        <div className="cell-stack">
                          <strong>{source.name}</strong>
                          <span>{source.slug} · v{source.version}</span>
                        </div>
                      </td>
                      <td>
                        <div className="cell-stack">
                          <strong>{source.server_url}</strong>
                          <span>{source.user_base_dn}</span>
                        </div>
                      </td>
                      <td>
                        <div className="cell-stack">
                          <strong>{source.bind_dn ?? '匿名绑定'}</strong>
                          <span>
                            密码 {source.bind_password_configured ? '已配置' : '未配置'}
                          </span>
                        </div>
                      </td>
                      <td>
                        <div className="cell-stack">
                          <StatusBadge tone={source.enabled ? 'success' : 'warning'}>
                            {source.enabled ? '启用' : '停用'}
                          </StatusBadge>
                          <span>
                            最近成功 {source.last_success_at
                              ? formatDate(source.last_success_at)
                              : '尚未同步'}
                          </span>
                        </div>
                      </td>
                      <td>
                        <div className="inline-actions identity-action-group">
                          <button
                            className="text-button"
                            disabled={testLdap.isPending}
                            onClick={() => void testLdap.mutateAsync(source)}
                            type="button"
                          >
                            <ShieldCheck size={15} /> 测试连接
                          </button>
                          <button
                            className="text-button"
                            disabled={toggleLdap.isPending}
                            onClick={() => void toggleLdap.mutateAsync(source)}
                            type="button"
                          >
                            {source.enabled ? '停用' : '启用'}
                          </button>
                          {(['dry_run', 'full', 'incremental'] as const).map((mode) => (
                            <button
                              className="text-button"
                              disabled={!source.enabled || startSync.isPending}
                              key={mode}
                              onClick={() => void startSync.mutateAsync({
                                mode,
                                sourceId: source.id,
                              })}
                              type="button"
                            >
                              {ldapModeLabels[mode]}
                            </button>
                          ))}
                        </div>
                        {ldapTest?.id === source.id ? (
                          <p className="inline-result" role="status">{ldapTest.message}</p>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
        {toggleLdap.error ? <ErrorNotice error={toggleLdap.error} /> : null}
        {testLdap.error ? <ErrorNotice error={testLdap.error} /> : null}
        {startSync.error ? <ErrorNotice error={startSync.error} /> : null}
      </section>

      <section className="admin-section identity-admin-section">
        <div className="section-heading">
          <div>
            <h2><RefreshCw size={18} /> LDAP 同步运行</h2>
            <p>运行记录和冲突由服务端持久化，页面不把异步状态藏在本地。</p>
          </div>
          <button
            className="button secondary"
            disabled={ldapRuns.isFetching}
            onClick={() => void ldapRuns.refetch()}
            type="button"
          >
            <RefreshCw size={16} /> 刷新记录
          </button>
        </div>
        {ldapRuns.isLoading ? <LoadingBlock label="正在加载同步记录…" /> : null}
        {ldapRuns.error ? (
          <ErrorNotice
            error={ldapRuns.error}
            onRetry={() => void ldapRuns.refetch()}
          />
        ) : null}
        {!ldapRuns.isLoading && !ldapRuns.error && !ldapRuns.data?.items.length ? (
          <EmptyState
            description="从 LDAP 身份源发起 dry-run、增量或全量同步后会显示运行记录。"
            icon={RefreshCw}
            title="没有同步记录"
          />
        ) : null}
        {(ldapRuns.data?.items.length ?? 0) > 0 ? (
          <div className="table-plane">
            <div className="table-scroll">
              <table className="data-table identity-table">
                <thead>
                  <tr>
                    <th>身份源</th>
                    <th>模式</th>
                    <th>状态</th>
                    <th>统计</th>
                    <th>时间</th>
                    <th>冲突</th>
                  </tr>
                </thead>
                <tbody>
                  {ldapRuns.data?.items.map((run) => (
                    <tr key={run.id}>
                      <td>{sourceNames.get(run.source_id) ?? run.source_id.slice(0, 8)}</td>
                      <td>{ldapModeLabels[run.mode]}</td>
                      <td>
                        <StatusBadge tone={runTone(run.status)}>{run.status}</StatusBadge>
                        {run.error_code ? (
                          <p className="inline-result danger">{run.error_code}</p>
                        ) : null}
                      </td>
                      <td>{formatRunStats(run.stats)}</td>
                      <td>{formatDate(run.created_at)}</td>
                      <td>
                        <button
                          className="text-button"
                          onClick={() => setSelectedRunId(run.id)}
                          type="button"
                        >
                          <TriangleAlert size={15} /> 查看冲突
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
        {selectedRunId ? (
          <div className="identity-conflict-panel">
            <div className="result-heading">
              <div>
                <h2>同步冲突</h2>
                <span>运行 {selectedRunId.slice(0, 8)}</span>
              </div>
              <button
                className="text-button"
                onClick={() => setSelectedRunId(null)}
                type="button"
              >
                收起
              </button>
            </div>
            {conflicts.isLoading ? <LoadingBlock label="正在加载冲突…" /> : null}
            {conflicts.error ? (
              <ErrorNotice
                error={conflicts.error}
                onRetry={() => void conflicts.refetch()}
              />
            ) : null}
            {!conflicts.isLoading && !conflicts.error && !conflicts.data?.items.length ? (
              <p className="identity-empty-line">
                <ShieldCheck size={16} /> 本次运行没有冲突。
              </p>
            ) : null}
            {(conflicts.data?.items.length ?? 0) > 0 ? (
              <div className="conflict-list">
                {conflicts.data?.items.map((conflict) => (
                  <article key={conflict.id}>
                    <TriangleAlert size={18} />
                    <div>
                      <div className="device-title">
                        <strong>{conflict.code}</strong>
                        <StatusBadge tone="warning">{conflict.object_type}</StatusBadge>
                      </div>
                      <p>{conflict.external_id} · {formatDate(conflict.created_at)}</p>
                      <code>{JSON.stringify(conflict.details)}</code>
                    </div>
                  </article>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      {showOidcCreate ? (
        <Modal onClose={() => setShowOidcCreate(false)} title="新建 OIDC Provider">
          <OidcCreateForm
            error={createOidc.error}
            pending={createOidc.isPending}
            onSubmit={(payload) => void createOidc.mutateAsync(payload)}
          />
        </Modal>
      ) : null}

      {showLdapCreate ? (
        <Modal
          onClose={() => setShowLdapCreate(false)}
          title="新建 LDAP 身份源"
          wide
        >
          <LdapCreateForm
            error={createLdap.error}
            pending={createLdap.isPending}
            onSubmit={(payload) => void createLdap.mutateAsync(payload)}
          />
        </Modal>
      ) : null}
    </>
  )
}

function OidcCreateForm({
  error,
  onSubmit,
  pending,
}: {
  error: unknown
  onSubmit: (payload: OidcProviderCreateRequest) => void
  pending: boolean
}) {
  const [draft, setDraft] = useState(initialOidcDraft)
  const [scopes, setScopes] = useState(initialOidcDraft.scopes?.join(' ') ?? '')

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSubmit({
      ...draft,
      client_secret_ref: draft.client_secret_ref || null,
      scopes: scopes.split(/[\s,]+/).filter(Boolean),
    })
  }

  return (
    <form className="stack-form" onSubmit={submit}>
      <div className="form-grid">
        <label>
          显示名称
          <input
            disabled={pending}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            required
            value={draft.name}
          />
        </label>
        <label>
          唯一标识
          <input
            disabled={pending}
            onChange={(event) => setDraft({ ...draft, slug: event.target.value })}
            pattern="[A-Za-z0-9][A-Za-z0-9_-]*"
            required
            value={draft.slug}
          />
        </label>
        <label className="span-2">
          Issuer URL
          <input
            disabled={pending}
            onChange={(event) => setDraft({ ...draft, issuer_url: event.target.value })}
            placeholder="https://idp.example.com"
            required
            type="url"
            value={draft.issuer_url}
          />
        </label>
        <label>
          Client ID
          <input
            disabled={pending}
            onChange={(event) => setDraft({ ...draft, client_id: event.target.value })}
            required
            value={draft.client_id}
          />
        </label>
        <label>
          客户端密钥引用
          <input
            autoComplete="new-password"
            disabled={pending}
            onChange={(event) => setDraft({
              ...draft,
              client_secret_ref: event.target.value,
            })}
            placeholder="env:OIDC_CLIENT_SECRET"
            type="password"
            value={draft.client_secret_ref ?? ''}
          />
        </label>
        <label className="span-2">
          Scopes
          <input
            disabled={pending}
            onChange={(event) => setScopes(event.target.value)}
            required
            value={scopes}
          />
        </label>
      </div>
      <label className="checkbox-field">
        <input
          checked={draft.enabled}
          disabled={pending}
          onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })}
          type="checkbox"
        />
        创建后立即启用
      </label>
      <p className="form-hint">
        密钥字段只接受服务端可解析的引用，例如 env:VARIABLE；保存后页面只显示“已配置”。
      </p>
      {error ? <ErrorNotice error={error} /> : null}
      <button className="button primary" disabled={pending} type="submit">
        {pending ? '正在创建…' : '创建 OIDC Provider'}
      </button>
    </form>
  )
}

function LdapCreateForm({
  error,
  onSubmit,
  pending,
}: {
  error: unknown
  onSubmit: (payload: LdapSourceCreateRequest) => void
  pending: boolean
}) {
  const [draft, setDraft] = useState(initialLdapDraft)
  const [mappingError, setMappingError] = useState<string | null>(null)

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    try {
      const attributeMapping = parseAttributeMapping(draft.attributeMappingText)
      setMappingError(null)
      onSubmit({
        attribute_mapping: attributeMapping,
        base_dn: draft.base_dn,
        bind_dn: draft.bind_dn || null,
        bind_password_ref: draft.bind_password_ref || null,
        department_base_dn: draft.department_base_dn || null,
        department_filter: draft.department_filter || null,
        enabled: draft.enabled,
        group_base_dn: draft.group_base_dn || null,
        group_filter: draft.group_filter || null,
        name: draft.name,
        server_url: draft.server_url,
        slug: draft.slug,
        user_base_dn: draft.user_base_dn,
        user_filter: draft.user_filter,
      })
    } catch (parseError) {
      setMappingError(
        parseError instanceof Error ? parseError.message : '属性映射 JSON 无效。',
      )
    }
  }

  return (
    <form className="stack-form" onSubmit={submit}>
      <div className="form-grid">
        <label>
          显示名称
          <input
            disabled={pending}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            required
            value={draft.name}
          />
        </label>
        <label>
          唯一标识
          <input
            disabled={pending}
            onChange={(event) => setDraft({ ...draft, slug: event.target.value })}
            pattern="[A-Za-z0-9][A-Za-z0-9_-]*"
            required
            value={draft.slug}
          />
        </label>
        <label className="span-2">
          LDAP Server URL
          <input
            disabled={pending}
            onChange={(event) => setDraft({ ...draft, server_url: event.target.value })}
            placeholder="ldaps://ldap.example.com"
            required
            value={draft.server_url}
          />
        </label>
        <label className="span-2">
          Base DN
          <input
            disabled={pending}
            onChange={(event) => setDraft({ ...draft, base_dn: event.target.value })}
            placeholder="dc=example,dc=com"
            required
            value={draft.base_dn}
          />
        </label>
        <label>
          Bind DN
          <input
            disabled={pending}
            onChange={(event) => setDraft({ ...draft, bind_dn: event.target.value })}
            value={draft.bind_dn ?? ''}
          />
        </label>
        <label>
          Bind 密码引用
          <input
            autoComplete="new-password"
            disabled={pending}
            onChange={(event) => setDraft({
              ...draft,
              bind_password_ref: event.target.value,
            })}
            placeholder="env:LDAP_BIND_PASSWORD"
            type="password"
            value={draft.bind_password_ref ?? ''}
          />
        </label>
        <label>
          用户 Base DN
          <input
            disabled={pending}
            onChange={(event) => setDraft({
              ...draft,
              user_base_dn: event.target.value,
            })}
            required
            value={draft.user_base_dn}
          />
        </label>
        <label>
          用户过滤器
          <input
            disabled={pending}
            onChange={(event) => setDraft({
              ...draft,
              user_filter: event.target.value,
            })}
            required
            value={draft.user_filter}
          />
        </label>
        <label>
          部门 Base DN
          <input
            disabled={pending}
            onChange={(event) => setDraft({
              ...draft,
              department_base_dn: event.target.value,
            })}
            value={draft.department_base_dn ?? ''}
          />
        </label>
        <label>
          部门过滤器
          <input
            disabled={pending}
            onChange={(event) => setDraft({
              ...draft,
              department_filter: event.target.value,
            })}
            value={draft.department_filter ?? ''}
          />
        </label>
        <label>
          用户组 Base DN
          <input
            disabled={pending}
            onChange={(event) => setDraft({
              ...draft,
              group_base_dn: event.target.value,
            })}
            value={draft.group_base_dn ?? ''}
          />
        </label>
        <label>
          用户组过滤器
          <input
            disabled={pending}
            onChange={(event) => setDraft({
              ...draft,
              group_filter: event.target.value,
            })}
            value={draft.group_filter ?? ''}
          />
        </label>
        <label className="span-2">
          属性映射 JSON
          <textarea
            disabled={pending}
            onChange={(event) => setDraft({
              ...draft,
              attributeMappingText: event.target.value,
            })}
            rows={7}
            value={draft.attributeMappingText}
          />
        </label>
      </div>
      <label className="checkbox-field">
        <input
          checked={draft.enabled}
          disabled={pending}
          onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })}
          type="checkbox"
        />
        创建后立即启用
      </label>
      <p className="form-hint">
        生产目录建议使用 LDAPS；密码引用保存后不会回显，只显示是否已配置。
      </p>
      {mappingError ? (
        <p className="form-hint danger" role="alert">
          <Braces size={15} /> {mappingError}
        </p>
      ) : null}
      {error ? <ErrorNotice error={error} /> : null}
      <button className="button primary" disabled={pending} type="submit">
        {pending ? '正在创建…' : '创建 LDAP 身份源'}
      </button>
    </form>
  )
}
