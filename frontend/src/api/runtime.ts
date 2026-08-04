import {
  ApiError as GeneratedApiError,
  OpenAPI,
} from './generated'
import type { ApiRequestOptions } from './generated/core/ApiRequestOptions'

const MUTATION_METHODS = new Set<ApiRequestOptions['method']>([
  'DELETE',
  'PATCH',
  'POST',
  'PUT',
])

const SESSION_ERROR_CODES = new Set([
  'AUTH_REQUIRED',
  'SESSION_EXPIRED',
  'SESSION_INVALID',
  'SESSION_REUSED',
])

export const SESSION_EXPIRED_EVENT = 'drive:session-expired'

export type ApiErrorDetails = unknown

export interface SessionExpiredEventDetail {
  error: ApiError
}

interface ApiErrorBody {
  code?: unknown
  details?: unknown
  message?: unknown
  request_id?: unknown
}

export class ApiError extends Error {
  readonly code: string
  readonly details: ApiErrorDetails
  readonly requestId: string
  readonly status: number

  constructor({
    cause,
    code,
    details,
    message,
    requestId,
    status,
  }: {
    cause?: unknown
    code: string
    details?: ApiErrorDetails
    message: string
    requestId: string
    status: number
  }) {
    super(message, cause === undefined ? undefined : { cause })
    this.name = 'ApiError'
    this.code = code
    this.details = details
    this.requestId = requestId
    this.status = status
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function errorBody(value: unknown): ApiErrorBody {
  return isRecord(value) ? value : {}
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

export function normalizeApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error
  }

  if (error instanceof GeneratedApiError) {
    const body = errorBody(error.body)
    return new ApiError({
      cause: error,
      code: stringValue(body.code) ?? `HTTP_${error.status}`,
      details: body.details,
      message: stringValue(body.message) ?? error.message,
      requestId: stringValue(body.request_id) ?? 'unknown',
      status: error.status,
    })
  }

  return new ApiError({
    cause: error,
    code: 'NETWORK_ERROR',
    message: error instanceof Error && error.message
      ? error.message
      : '网络请求失败',
    requestId: 'unknown',
    status: 0,
  })
}

export function readCookie(
  name: string,
  cookieSource = typeof document === 'undefined' ? '' : document.cookie,
): string | undefined {
  const encodedName = `${encodeURIComponent(name)}=`
  for (const part of cookieSource.split(';')) {
    const cookie = part.trim()
    if (cookie.startsWith(encodedName)) {
      return decodeURIComponent(cookie.slice(encodedName.length))
    }
  }
  return undefined
}

function apiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim()
  return configured ? configured.replace(/\/+$/, '') : ''
}

export function configureApiRuntime(): void {
  OpenAPI.BASE = apiBaseUrl()
  OpenAPI.WITH_CREDENTIALS = true
  OpenAPI.CREDENTIALS = 'include'
  OpenAPI.HEADERS = async (
    options,
  ): Promise<Record<string, string>> => {
    if (!MUTATION_METHODS.has(options.method)) {
      return {}
    }
    const csrfToken = readCookie('drive_csrf')
    return csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
  }
}

function dispatchSessionExpired(error: ApiError): void {
  if (
    typeof window === 'undefined'
    || error.status !== 401
    || !SESSION_ERROR_CODES.has(error.code)
  ) {
    return
  }
  window.dispatchEvent(
    new CustomEvent<SessionExpiredEventDetail>(
      SESSION_EXPIRED_EVENT,
      {
        detail: { error },
      },
    ),
  )
}

export async function executeApi<T>(
  operation: () => PromiseLike<T>,
  {
    notifySessionExpired = true,
  }: {
    notifySessionExpired?: boolean
  } = {},
): Promise<T> {
  try {
    return await operation()
  } catch (error) {
    const apiError = normalizeApiError(error)
    if (notifySessionExpired) {
      dispatchSessionExpired(apiError)
    }
    throw apiError
  }
}
