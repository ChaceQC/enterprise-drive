import { createContext } from 'react'

import type { CompleteUploadPartRequest } from '../../api/generated'

export type UploadStatus =
  | 'cancelled'
  | 'completing'
  | 'completed'
  | 'failed'
  | 'hashing'
  | 'paused'
  | 'queued'
  | 'uploading'
  | 'waiting-file'

export interface UploadTask {
  error?: string
  fileName: string
  hash?: string
  id: string
  lastModified?: number
  parentId: string
  parts?: CompleteUploadPartRequest[]
  progress: number
  sessionId?: string
  size: number
  spaceId: string
  status: UploadStatus
  verifyHashOnResume?: boolean
}

export interface UploadContextValue {
  cancel: (taskId: string) => Promise<void>
  dismiss: (taskId: string) => void
  enqueue: (files: File[], spaceId: string, parentId: string) => void
  pause: (taskId: string) => void
  reattach: (taskId: string, file: File) => Promise<void>
  resume: (taskId: string) => void
  tasks: UploadTask[]
}

export const UploadContext = createContext<UploadContextValue | undefined>(
  undefined,
)
