import type { Page, Route } from '@playwright/test'

const user = {
  display_name: '系统管理员',
  email: 'admin@example.com',
  id: '4c9bf310-0e58-4ca3-a582-8214e51f32f1',
  is_super_admin: true,
  must_change_password: false,
  tenant_id: '73cd16f1-ac07-40d6-8c92-5de97e4b710b',
  username: 'admin',
}

const space = {
  created_at: '2026-08-01T00:00:00Z',
  id: '11111111-1111-4111-8111-111111111111',
  is_active: true,
  name: '产品资料',
  owner_id: user.id,
  permission_version: 1,
  slug: 'product',
  space_type: 'team',
  tenant_id: user.tenant_id,
  updated_at: '2026-08-04T03:00:00Z',
  version: 1,
}

const file = {
  created_at: '2026-08-01T00:00:00Z',
  current_version_id: '33333333-3333-4333-8333-333333333333',
  id: '22222222-2222-4222-8222-222222222222',
  name: '发布说明.pdf',
  node_type: 'file',
  parent_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  permission_version: 1,
  permissions: {
    delete: true,
    download: true,
    preview: true,
    read_meta: true,
    share: true,
    update: true,
  },
  space_id: space.id,
  tenant_id: user.tenant_id,
  updated_at: '2026-08-04T03:00:00Z',
}

const folder = {
  ...file,
  current_version_id: null,
  id: '44444444-4444-4444-8444-444444444444',
  name: '设计素材',
  node_type: 'folder',
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    body: JSON.stringify(body),
    contentType: 'application/json',
    status,
  })
}

export async function installMockApi(
  page: Page,
  {
    authenticated = true,
  }: {
    authenticated?: boolean
  } = {},
) {
  let signedIn = authenticated

  await page.context().addCookies([{
    domain: '127.0.0.1',
    name: 'drive_csrf',
    path: '/',
    value: 'csrf-e2e',
  }])

  await page.route('https://storage.test/**', async (route) => {
    await route.fulfill({
      body: '',
      headers: {
        'access-control-expose-headers': 'etag',
        etag: '"part-etag-1"',
      },
      status: 200,
    })
  })

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()

    if (path === '/api/v1/auth/me') {
      return signedIn
        ? json(route, user)
        : json(route, {
          code: 'AUTH_REQUIRED',
          message: '请先登录',
          request_id: 'req_initial',
        }, 401)
    }
    if (path === '/api/v1/auth/login') {
      signedIn = true
      return json(route, {
        authenticated: true,
        expires_at: '2026-09-03T00:00:00Z',
        user,
      })
    }
    if (path === '/api/v1/auth/logout') {
      signedIn = false
      return json(route, { authenticated: false })
    }
    if (path === '/api/v1/auth/session/rotate') {
      return json(route, {
        authenticated: true,
        expires_at: '2026-09-03T00:00:00Z',
        user,
      })
    }
    if (path === '/api/v1/spaces') {
      return json(route, { items: [space], next_cursor: null })
    }
    if (path === '/api/v1/files' && method === 'GET') {
      return json(route, {
        items: [folder, file],
        next_cursor: null,
        parent_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        space_id: space.id,
      })
    }
    if (path === '/api/v1/files/batch-delete') {
      return json(route, {
        results: [
          { node_id: folder.id, status: 'success' },
          { code: 'FILE_LOCKED', node_id: file.id, status: 'failed' },
        ],
      })
    }
    if (path === '/api/v1/files/batch-restore' || path === '/api/v1/files/batch-purge') {
      const payload = request.postDataJSON() as { node_ids: string[] }
      return json(route, {
        results: payload.node_ids.map((node_id) => ({ node_id, status: 'success' })),
      })
    }
    if (path === '/api/v1/files/trash') {
      return json(route, {
        items: [{
          ...file,
          deleted_at: '2026-08-03T10:00:00Z',
          deleted_by: user.id,
          id: '55555555-5555-4555-8555-555555555555',
          name: '旧方案.docx',
        }],
        next_cursor: null,
        space_id: space.id,
      })
    }
    if (path === `/api/v1/files/${file.id}/versions` && method === 'GET') {
      return json(route, {
        current_version_id: file.current_version_id,
        items: [
          {
            created_at: '2026-08-04T03:00:00Z',
            created_by: user.id,
            id: file.current_version_id,
            is_current: true,
            mime_type: 'application/pdf',
            node_id: file.id,
            size_bytes: 2048,
            version_no: 2,
          },
          {
            created_at: '2026-08-03T03:00:00Z',
            created_by: user.id,
            id: '12121212-1212-4212-8212-121212121212',
            is_current: false,
            mime_type: 'application/pdf',
            node_id: file.id,
            size_bytes: 1024,
            version_no: 1,
          },
        ],
        next_cursor: null,
        node_id: file.id,
      })
    }
    if (path.endsWith('/rollback') && method === 'POST') {
      const sourceVersionId = path.split('/').at(-2)!
      return json(route, {
        current_version_id: '13131313-1313-4313-8313-131313131313',
        new_version_id: '13131313-1313-4313-8313-131313131313',
        node_id: file.id,
        source_version_id: sourceVersionId,
        version_no: 3,
      })
    }
    if (path.endsWith('/preview')) {
      return json(route, {
        artifact: {
          artifact_id: 'preview-1',
          artifact_type: 'image',
          expires_at: '2026-08-04T05:00:00Z',
          headers: {},
          mime_type: 'image/svg+xml',
          preview_url: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="500" height="300"%3E%3Crect width="100%25" height="100%25" fill="%23e2f3f1"/%3E%3Ctext x="50%25" y="50%25" text-anchor="middle" fill="%23087e7b" font-size="28"%3EPreview%3C/text%3E%3C/svg%3E',
          size_bytes: 1024,
        },
        error: null,
        node_id: file.id,
        status: 'ready',
        version_id: file.current_version_id,
      })
    }
    if (path.endsWith('/download')) {
      return json(route, {
        content_hash: 'a'.repeat(64),
        download_url: 'data:text/plain,enterprise-drive',
        expires_at: '2026-08-04T05:00:00Z',
        file_name: file.name,
        hash_algo: 'sha256',
        headers: {},
        mime_type: 'application/pdf',
        node_id: file.id,
        size_bytes: 2048,
        version_id: file.current_version_id,
      })
    }
    if (path === '/api/v1/search') {
      return json(route, {
        items: [{
          highlights: { content: ['发布说明'] },
          mime_type: 'application/pdf',
          name: file.name,
          node_id: file.id,
          score: 1,
          size_bytes: 2048,
          space_id: space.id,
          updated_at: file.updated_at,
        }],
        next_cursor: null,
        query: url.searchParams.get('q'),
        total: 1,
      })
    }
    if (path === '/api/v1/directory/users') {
      return json(route, {
        items: [{
          display_name: '协作用户',
          id: '14141414-1414-4414-8414-141414141414',
          username: 'collaborator',
        }],
        next_cursor: null,
      })
    }
    if (path === '/api/v1/directory/departments' || path === '/api/v1/directory/groups') {
      return json(route, { items: [], next_cursor: null })
    }
    if (path === '/api/v1/shares' && method === 'POST') {
      return json(route, {
        expires_at: null,
        id: '15151515-1515-4515-8515-151515151515',
        max_downloads: null,
        max_views: null,
        permission: 'download',
        raw_token: null,
        root_node_id: file.id,
        share_type: 'internal',
        status: 'active',
      }, 201)
    }
    if (path === '/api/v1/shares/created' || path === '/api/v1/shares/received') {
      return json(route, {
        items: [{
          available: true,
          created_at: '2026-08-04T01:00:00Z',
          created_by: user.id,
          creator_name: user.display_name,
          download_count: 1,
          expires_at: null,
          id: '66666666-6666-4666-8666-666666666666',
          max_downloads: 10,
          max_views: 20,
          permission: 'download',
          root_name: file.name,
          root_node_id: file.id,
          root_node_type: 'file',
          share_type: path.endsWith('created') ? 'external' : 'internal',
          status: 'active',
          view_count: 2,
        }],
        next_cursor: null,
      })
    }
    if (path === '/api/v1/shares/notifications') {
      return json(route, {
        items: [{
          created_at: '2026-08-04T01:00:00Z',
          created_by: user.id,
          creator_name: '协作者',
          id: '77777777-7777-4777-8777-777777777777',
          invalidated_at: null,
          is_read: false,
          notification_type: 'share.created',
          read_at: null,
          root_name: file.name,
          root_node_id: file.id,
          share_id: '66666666-6666-4666-8666-666666666666',
        }],
        next_cursor: null,
      })
    }
    if (path.includes('/notifications/') && path.endsWith('/read')) {
      return json(route, { id: path.split('/').at(-2), is_read: true })
    }
    if (path === '/api/v1/device-sessions') {
      return json(route, {
        items: [{
          client_version: '0.7.0',
          created_at: '2026-08-01T00:00:00Z',
          current: false,
          id: '88888888-8888-4888-8888-888888888888',
          last_seen_at: '2026-08-04T03:00:00Z',
          name: 'Windows 11 工作站',
          platform: 'windows',
          revoked_at: null,
          revoked_reason: null,
          status: 'active',
        }],
      })
    }
    if (path === '/api/v1/uploads/init') {
      return json(route, {
        expires_at: '2026-08-04T05:00:00Z',
        max_parallelism: 2,
        mode: 'multipart',
        part_size_bytes: 1024,
        session_id: '99999999-9999-4999-8999-999999999999',
        total_parts: 1,
      }, 201)
    }
    if (path.includes('/uploads/') && path.endsWith('/presign')) {
      return json(route, {
        expires_at: '2026-08-04T05:00:00Z',
        headers: {},
        part_no: 1,
        upload_url: 'https://storage.test/part/1',
      })
    }
    if (path.includes('/uploads/') && path.endsWith('/confirm')) {
      return json(route, {
        part_no: 1,
        session_id: '99999999-9999-4999-8999-999999999999',
        uploaded_parts: [1],
      })
    }
    if (path.includes('/uploads/') && path.endsWith('/complete')) {
      return json(route, {
        blob_id: 'blob-1',
        node_id: file.id,
        session_id: '99999999-9999-4999-8999-999999999999',
        status: 'completed',
        version_id: file.current_version_id,
      })
    }
    if (path === '/api/v1/admin/stats/overview') {
      return json(route, {
        active_shares: 3,
        file_versions_total: 18,
        generated_at: '2026-08-04T03:00:00Z',
        nodes_deleted: 2,
        nodes_total: 42,
        outbox_dead: 0,
        outbox_pending: 1,
        pending_uploads: 1,
        quota_limit_bytes: 1000000000,
        quota_used_bytes: 250000000,
        spaces_active: 1,
        spaces_total: 1,
        stored_bytes: 250000000,
        users_active: 4,
        users_total: 5,
      })
    }
    if (path === '/api/v1/admin/maintenance/tasks') {
      return json(route, {
        generated_at: '2026-08-04T03:00:00Z',
        tasks: [{
          alert_active: false,
          consecutive_failures: 0,
          expected_interval_seconds: 3600,
          last_failure_at: null,
          last_finished_at: '2026-08-04T03:00:00Z',
          last_status: 'succeeded',
          last_success_at: '2026-08-04T03:00:00Z',
          stale: false,
          task_name: 'quota.reconcile_space_usage',
        }],
      })
    }
    if (path === '/api/v1/admin/users') {
      return json(route, { items: [{ ...user, created_at: '2026-08-01T00:00:00Z', is_active: true, updated_at: '2026-08-04T03:00:00Z', version: 1 }], next_cursor: null })
    }
    if (path === '/api/v1/admin/audit-logs') {
      return json(route, { items: [{ action: 'file.downloaded', actor_id: user.id, actor_type: 'user', created_at: '2026-08-04T02:00:00Z', id: 'audit-1', ip: '127.0.0.1', metadata: {}, request_id: 'req-audit', resource_id: file.id, resource_type: 'file', result: 'allowed', risk_level: 'low', tenant_id: user.tenant_id, user_agent: 'Playwright' }], next_cursor: null })
    }

    return json(route, { items: [], next_cursor: null })
  })
}
