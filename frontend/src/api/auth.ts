import {
  AuthService,
  type LoginRequest,
  type LogoutResponse,
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
