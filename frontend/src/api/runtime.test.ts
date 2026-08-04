import {
  ApiError as GeneratedApiError,
  OpenAPI,
} from './generated'
import type { ApiRequestOptions } from './generated/core/ApiRequestOptions'
import type { ApiResult } from './generated/core/ApiResult'
import {
  ApiError,
  SESSION_EXPIRED_EVENT,
  configureApiRuntime,
  executeApi,
  normalizeApiError,
  readCookie,
} from './runtime'

const baseRequest: ApiRequestOptions = {
  method: 'GET',
  url: '/api/v1/auth/me',
}

function generatedError({
  body,
  status,
}: {
  body: unknown
  status: number
}) {
  const result: ApiResult = {
    body,
    ok: false,
    status,
    statusText: 'Unauthorized',
    url: '/api/v1/auth/me',
  }
  return new GeneratedApiError(
    baseRequest,
    result,
    'Request failed',
  )
}

describe('API runtime', () => {
  beforeEach(() => {
    document.cookie = 'drive_csrf=; Max-Age=0; Path=/'
    configureApiRuntime()
  })

  it('uses browser credentials and only injects CSRF for mutations', async () => {
    document.cookie = 'drive_csrf=csrf%20token; Path=/'

    expect(OpenAPI.WITH_CREDENTIALS).toBe(true)
    expect(OpenAPI.CREDENTIALS).toBe('include')
    expect(readCookie('drive_csrf')).toBe('csrf token')

    const resolveHeaders = OpenAPI.HEADERS
    expect(typeof resolveHeaders).toBe('function')
    if (typeof resolveHeaders !== 'function') {
      throw new Error('OpenAPI.HEADERS is not configured')
    }

    await expect(resolveHeaders(baseRequest)).resolves.toEqual({})
    await expect(
      resolveHeaders({
        method: 'POST',
        url: '/api/v1/auth/logout',
      }),
    ).resolves.toEqual({
      'X-CSRF-Token': 'csrf token',
    })
  })

  it('normalizes backend error code, details and request_id', () => {
    const normalized = normalizeApiError(
      generatedError({
        body: {
          code: 'CSRF_TOKEN_INVALID',
          details: { field: 'header' },
          message: 'CSRF 校验失败',
          request_id: 'req_csrf',
        },
        status: 403,
      }),
    )

    expect(normalized).toBeInstanceOf(ApiError)
    expect(normalized).toMatchObject({
      code: 'CSRF_TOKEN_INVALID',
      details: { field: 'header' },
      message: 'CSRF 校验失败',
      requestId: 'req_csrf',
      status: 403,
    })
  })

  it('dispatches the session-expired event for session-related 401s', async () => {
    const listener = vi.fn()
    window.addEventListener(SESSION_EXPIRED_EVENT, listener)

    const error = generatedError({
      body: {
        code: 'SESSION_EXPIRED',
        message: '登录会话已过期',
        request_id: 'req_expired',
      },
      status: 401,
    })

    await expect(
      executeApi(() => Promise.reject(error)),
    ).rejects.toMatchObject({
      code: 'SESSION_EXPIRED',
      requestId: 'req_expired',
    })
    expect(listener).toHaveBeenCalledOnce()

    window.removeEventListener(SESSION_EXPIRED_EVENT, listener)
  })

  it('does not turn invalid login credentials into a session event', async () => {
    const listener = vi.fn()
    window.addEventListener(SESSION_EXPIRED_EVENT, listener)

    const error = generatedError({
      body: {
        code: 'AUTH_INVALID_CREDENTIALS',
        message: '用户名或密码错误',
        request_id: 'req_login',
      },
      status: 401,
    })

    await expect(
      executeApi(() => Promise.reject(error)),
    ).rejects.toMatchObject({
      code: 'AUTH_INVALID_CREDENTIALS',
    })
    expect(listener).not.toHaveBeenCalled()

    window.removeEventListener(SESSION_EXPIRED_EVENT, listener)
  })
})
