import {
  MutationCache,
  QueryCache,
  QueryClient,
} from '@tanstack/react-query'

import { normalizeApiError } from '../api/runtime'

function handleError(error: unknown) {
  normalizeApiError(error)
}

export const queryClient = new QueryClient({
  mutationCache: new MutationCache({
    onError: handleError,
  }),
  queryCache: new QueryCache({
    onError: handleError,
  }),
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry(failureCount, error) {
        const normalized = normalizeApiError(error)
        return normalized.status === 0 && failureCount < 1
      },
      staleTime: 20_000,
    },
  },
})
