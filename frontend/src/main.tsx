import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'

import { AuthProvider } from './app/AuthProvider'
import { queryClient } from './app/query-client'
import { configureApiRuntime } from './api/runtime'
import { UploadProvider } from './modules/uploads/UploadProvider'
import { RouterProvider } from '@tanstack/react-router'
import { router } from './app/router'
import './styles.css'

configureApiRuntime()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <UploadProvider>
          <RouterProvider router={router} />
        </UploadProvider>
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
