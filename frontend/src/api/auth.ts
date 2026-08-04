import {
  AuthService,
  type BrowserSessionListResponse,
  type BrowserSessionRevokeResponse,
  type LoginRequest,
  type LogoutResponse,
  type PasswordChangeRequest,
  type PasswordChangeResponse,
  type PasswordPolicyResponse,
  type SessionResponse,
  type UserProfileResponse,
} from './generated'
import { configureApiRuntime, executeApi } from './runtime'

configureApiRuntime()

export type LoginCredentials = LoginRequest

export function login(
  credentials: LoginCredentials,
): Promise<SessionResponse> {
  return executeApi(
    () => AuthService.loginApiV1AuthLoginPost({
      requestBody: credentials,
    }),
    { notifySessionExpired: false },
  )
}

export function logout(): Promise<LogoutResponse> {
  return executeApi(() => AuthService.logoutApiV1AuthLogoutPost())
}

export function getCurrentUser({
  notifySessionExpired = true,
}: {
  notifySessionExpired?: boolean
} = {}): Promise<UserProfileResponse> {
  return executeApi(
    () => AuthService.meApiV1AuthMeGet(),
    { notifySessionExpired },
  )
}

export function rotateSession(): Promise<SessionResponse> {
  return executeApi(
    () => AuthService.rotateSessionApiV1AuthSessionRotatePost(),
  )
}

export function getPasswordPolicy(): Promise<PasswordPolicyResponse> {
  return executeApi(
    () => AuthService.getPasswordPolicyApiV1AuthPasswordPolicyGet(),
    { notifySessionExpired: false },
  )
}

export function changePassword(
  requestBody: PasswordChangeRequest,
): Promise<PasswordChangeResponse> {
  return executeApi(
    () => AuthService.changePasswordApiV1AuthPasswordChangePost({
      requestBody,
    }),
  )
}

export function listBrowserSessions(): Promise<BrowserSessionListResponse> {
  return executeApi(
    () => AuthService.listBrowserSessionsApiV1AuthSessionsGet(),
  )
}

export function revokeBrowserSession(
  sessionId: string,
): Promise<BrowserSessionRevokeResponse> {
  return executeApi(
    () => AuthService.revokeBrowserSessionApiV1AuthSessionsSessionIdDelete({
      sessionId,
    }),
  )
}
