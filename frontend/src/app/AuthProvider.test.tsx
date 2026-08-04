import { act, renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'

import {
  getCurrentUser,
  login,
  logout,
} from '../api/auth'
import {
  ApiError,
  SESSION_EXPIRED_EVENT,
} from '../api/runtime'
import { AuthProvider } from './AuthProvider'
import { useAuth } from './useAuth'

vi.mock('../api/auth', () => ({
  getCurrentUser: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}))

const profile = {
  display_name: '系统管理员',
  email: 'admin@example.com',
  id: '4c9bf310-0e58-4ca3-a582-8214e51f32f1',
  is_super_admin: true,
  must_change_password: false,
  tenant_id: '73cd16f1-ac07-40d6-8c92-5de97e4b710b',
  username: 'admin',
}

function wrapper({ children }: PropsWithChildren) {
  return <AuthProvider>{children}</AuthProvider>
}

describe('AuthProvider', () => {
  beforeEach(() => {
    vi.mocked(getCurrentUser).mockReset()
    vi.mocked(login).mockReset()
    vi.mocked(logout).mockReset()
  })

  it('restores an existing Cookie session', async () => {
    vi.mocked(getCurrentUser).mockResolvedValue(profile)

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => {
      expect(result.current.status).toBe('authenticated')
    })
    expect(getCurrentUser).toHaveBeenCalledWith({
      notifySessionExpired: false,
    })
    expect(result.current.user).toEqual(profile)
  })

  it('logs in and logs out through the generated auth client wrapper', async () => {
    vi.mocked(getCurrentUser).mockRejectedValue(
      new ApiError({
        code: 'AUTH_REQUIRED',
        message: '请先登录',
        requestId: 'req_initial',
        status: 401,
      }),
    )
    vi.mocked(login).mockResolvedValue({
      authenticated: true,
      expires_at: '2026-09-03T00:00:00Z',
      user: profile,
    })
    vi.mocked(logout).mockResolvedValue({
      authenticated: false,
    })

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => {
      expect(result.current.status).toBe('anonymous')
    })

    await act(async () => {
      await result.current.login({
        password: 'admin-password',
        tenant_slug: 'default',
        username: 'admin',
      })
    })

    expect(result.current.status).toBe('authenticated')
    expect(result.current.user).toEqual(profile)

    await act(async () => {
      await result.current.logout()
    })

    expect(result.current.status).toBe('anonymous')
    expect(result.current.user).toBeNull()
  })

  it('clears local auth state when a session-expired event arrives', async () => {
    vi.mocked(getCurrentUser).mockResolvedValue(profile)

    const { result } = renderHook(() => useAuth(), { wrapper })
    await waitFor(() => {
      expect(result.current.status).toBe('authenticated')
    })

    const error = new ApiError({
      code: 'SESSION_EXPIRED',
      message: '登录会话已过期',
      requestId: 'req_expired',
      status: 401,
    })

    act(() => {
      window.dispatchEvent(
        new CustomEvent(SESSION_EXPIRED_EVENT, {
          detail: { error },
        }),
      )
    })

    expect(result.current.status).toBe('anonymous')
    expect(result.current.user).toBeNull()
    expect(result.current.error).toBe(error)
  })
})
