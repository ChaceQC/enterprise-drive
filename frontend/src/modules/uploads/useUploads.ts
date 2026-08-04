import { useContext } from 'react'

import { UploadContext } from './upload-context'

export function useUploads() {
  const context = useContext(UploadContext)
  if (!context) {
    throw new Error('useUploads 必须在 UploadProvider 内使用')
  }
  return context
}
