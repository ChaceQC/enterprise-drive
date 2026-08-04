import { createContext } from 'react'

import type {
  LoginCredentials,
} from '../api/auth'
import type {
  UserProfileResponse,
} from '../api/generated'
import type { ApiError } from '../api/runtime'

export type AuthStatus = 'anonymous' | 'authenticated' | 'loading'

export interface AuthContextValue {
  error: ApiError | null
  isPending: boolean
  login: (credentials: LoginCredentials) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  status: AuthStatus
  user: UserProfileResponse | null
}

export const AuthContext = createContext<AuthContextValue | undefined>(
  undefined,
)
