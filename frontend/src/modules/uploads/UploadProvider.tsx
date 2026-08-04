import { createSHA256 } from 'hash-wasm'
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react'

import {
  type CancelablePromise,
  UploadsService,
  type CompleteUploadPartRequest,
} from '../../api/generated'
import {
  ApiError,
  executeApi,
  normalizeApiError,
} from '../../api/runtime'
import {
  UploadContext,
  type UploadTask,
} from './upload-context'
import {
  buildCompleteUploadParts,
  mergeUploadPart,
  isUsableUploadPart,
} from './upload-helpers'

const STORAGE_KEY = 'drive_upload_queue_v1'
const CHUNK_SIZE = 4 * 1024 * 1024
const PROTOCOL = 'DTP/1'

function loadPersistedTasks(): UploadTask[] {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    if (!value) return []
    const tasks = JSON.parse(value) as UploadTask[]
    return tasks
      .filter((task) => task.status !== 'completed' && task.status !== 'cancelled')
      .map((task) => ({
        ...task,
        status: 'waiting-file',
        progress: Math.min(task.progress, 99),
      }))
  } catch {
    return []
  }
}

async function hashFile(
  file: File,
  onProgress: (value: number) => void,
  signal: AbortSignal,
) {
  const hasher = await createSHA256()
  hasher.init()
  for (let offset = 0; offset < file.size; offset += CHUNK_SIZE) {
    if (signal.aborted) throw new DOMException('Upload paused', 'AbortError')
    const bytes = new Uint8Array(
      await file.slice(offset, offset + CHUNK_SIZE).arrayBuffer(),
    )
    hasher.update(bytes)
    onProgress(Math.min(12, Math.round(((offset + bytes.byteLength) / file.size) * 12)))
  }
  return hasher.digest('hex')
}

function uploadAbortError(): DOMException {
  return new DOMException('Upload paused', 'AbortError')
}

function isUploadAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

async function executeUploadApi<T>(
  operation: () => CancelablePromise<T>,
  signal: AbortSignal,
): Promise<T> {
  const request = operation()
  const cancel = () => request.cancel()
  if (signal.aborted) {
    request.cancel()
  } else {
    signal.addEventListener('abort', cancel, { once: true })
  }
  try {
    return await executeApi(() => request)
  } finally {
    signal.removeEventListener('abort', cancel)
  }
}

function canRestartUploadSession(error: ApiError): boolean {
  return error.code === 'UPLOAD_SESSION_EXPIRED'
    || error.code === 'UPLOAD_SESSION_NOT_FOUND'
}

function isExpiredUploadSession(expiresAt: string): boolean {
  const expiresAtMilliseconds = Date.parse(expiresAt)
  return Number.isFinite(expiresAtMilliseconds)
    && expiresAtMilliseconds <= Date.now()
}

export function UploadProvider({ children }: PropsWithChildren) {
  const [tasks, setTasks] = useState<UploadTask[]>(loadPersistedTasks)
  const tasksRef = useRef(tasks)
  const files = useRef(new Map<string, File>())
  const controllers = useRef(new Map<string, AbortController>())
  const cancelledTasks = useRef(new Set<string>())
  const runningTasks = useRef(new Map<string, Promise<void>>())

  useEffect(() => {
    tasksRef.current = tasks
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(tasks.filter((task) => task.status !== 'completed')),
    )
  }, [tasks])

  const updateTask = useCallback((id: string, update: Partial<UploadTask>) => {
    setTasks((current) => {
      const next = current.map((task) => (
        task.id === id ? { ...task, ...update } : task
      ))
      tasksRef.current = next
      return next
    })
  }, [])

  const run = useCallback(async (taskId: string) => {
    while (runningTasks.current.has(taskId)) {
      await runningTasks.current.get(taskId)
    }

    const file = files.current.get(taskId)
    const task = tasksRef.current.find((item) => item.id === taskId)
    if (
      !file
      || !task
      || task.status !== 'queued'
      || cancelledTasks.current.has(taskId)
    ) return

    let resolveRun: () => void = () => undefined
    const runCompletion = new Promise<void>((resolve) => {
      resolveRun = resolve
    })
    runningTasks.current.set(taskId, runCompletion)
    const controller = new AbortController()
    controllers.current.set(taskId, controller)
    const operationId = crypto.randomUUID()
    const isActive = () => (
      controllers.current.get(taskId) === controller
      && !controller.signal.aborted
      && !cancelledTasks.current.has(taskId)
    )
    const assertActive = () => {
      if (!isActive()) throw uploadAbortError()
    }
    const updateIfActive = (update: Partial<UploadTask>) => {
      if (isActive()) updateTask(taskId, update)
    }

    try {
      let hash = task.hash
      if (!hash || task.verifyHashOnResume) {
        updateIfActive({ error: undefined, status: 'hashing' })
        const computedHash = await hashFile(
          file,
          (progress) => updateIfActive({ progress }),
          controller.signal,
        )
        assertActive()
        if (hash && computedHash !== hash) {
          files.current.delete(taskId)
          updateIfActive({
            error: '所选文件内容与原上传任务不一致',
            status: 'waiting-file',
          })
          return
        }
        hash = computedHash
        updateIfActive({ hash, verifyHashOnResume: false })
      }

      let sessionId = task.sessionId
      let partSize = 0
      let totalParts = 0
      let uploadedParts = new Set<number>()

      if (sessionId) {
        try {
          const status = await executeUploadApi(
            () => UploadsService.getUploadStatusApiV1UploadsSessionIdGet({
              sessionId: sessionId!,
              xDriveTransferProtocol: PROTOCOL,
            }),
            controller.signal,
          )
          assertActive()
          if (status.status === 'completed') {
            updateIfActive({ progress: 100, status: 'completed' })
            return
          }
          if (status.status === 'completing') {
            throw new Error('上传正在服务端完成，请稍后重试')
          }
          if (
            (status.status !== 'initiated' && status.status !== 'uploading')
            || isExpiredUploadSession(status.expires_at)
          ) {
            sessionId = undefined
            updateIfActive({ parts: [], progress: 12, sessionId: undefined })
          } else {
            partSize = status.part_size_bytes
            totalParts = status.total_parts
            uploadedParts = new Set(status.uploaded_parts.filter((partNo) => (
              Number.isInteger(partNo) && partNo >= 1 && partNo <= totalParts
            )))
          }
        } catch (error) {
          assertActive()
          const normalized = normalizeApiError(error)
          if (!canRestartUploadSession(normalized)) throw error
          sessionId = undefined
          updateIfActive({ parts: [], progress: 12, sessionId: undefined })
        }
      }

      if (!sessionId) {
        const initialized = await executeUploadApi(() => (
          UploadsService.initUploadApiV1UploadsInitPost({
            requestBody: {
              content_hash: hash!,
              file_name: file.name,
              mime_type: file.type || null,
              parent_id: task.parentId,
              size_bytes: file.size,
              space_id: task.spaceId,
            },
            xClientOperationId: operationId,
            xDriveTransferProtocol: PROTOCOL,
          })
        ), controller.signal)
        assertActive()
        if (!('session_id' in initialized)) {
          updateIfActive({ progress: 100, status: 'completed' })
          return
        }
        sessionId = initialized.session_id
        partSize = initialized.part_size_bytes
        totalParts = initialized.total_parts
        updateIfActive({ sessionId })
      }

      assertActive()
      updateIfActive({ error: undefined, status: 'uploading' })
      const partOptions = { fileSize: file.size, partSize, totalParts }
      let completedParts: CompleteUploadPartRequest[] = (task.parts ?? []).filter((part) => (
        isUsableUploadPart(part, partOptions)
      ))
      for (let partNo = 1; partNo <= totalParts; partNo += 1) {
        assertActive()
        const start = (partNo - 1) * partSize
        const body = file.slice(start, Math.min(start + partSize, file.size))
        const cachedPart = completedParts.find((part) => part.part_no === partNo)
        if (!uploadedParts.has(partNo) || !cachedPart) {
          const signed = await executeUploadApi(() => (
            UploadsService.presignUploadPartApiV1UploadsSessionIdPartsPartNoPresignPost({
              partNo,
              sessionId: sessionId!,
              xDriveTransferProtocol: PROTOCOL,
            })
          ), controller.signal)
          assertActive()
          const response = await fetch(signed.upload_url, {
            body,
            credentials: 'omit',
            headers: signed.headers,
            method: 'PUT',
            signal: controller.signal,
          })
          if (!response.ok) {
            throw new Error(`分片 ${partNo} 上传失败（HTTP ${response.status}）`)
          }
          assertActive()
          const etag = response.headers.get('etag')?.replaceAll('"', '').trim()
          if (!etag) throw new Error(`分片 ${partNo} 缺少 ETag`)
          const confirmation = await executeUploadApi(() => (
            UploadsService.confirmUploadPartApiV1UploadsSessionIdPartsPartNoConfirmPost({
              partNo,
              requestBody: { etag, size_bytes: body.size },
              sessionId: sessionId!,
              xDriveTransferProtocol: PROTOCOL,
            })
          ), controller.signal)
          assertActive()
          if (!confirmation.uploaded_parts.includes(partNo)) {
            throw new Error(`分片 ${partNo} 未被服务端确认`)
          }
          uploadedParts = new Set(confirmation.uploaded_parts)
          const confirmedPart = { etag, part_no: partNo, size_bytes: body.size }
          completedParts = mergeUploadPart(completedParts, confirmedPart, partOptions)
          updateIfActive({ parts: completedParts })
        }
        updateIfActive({
          progress: 12 + Math.round((partNo / totalParts) * 84),
        })
      }

      assertActive()
      const finalParts = buildCompleteUploadParts(completedParts, partOptions)
      if (!finalParts) {
        throw new Error('上传分片缺少有效 ETag，请重试')
      }
      updateIfActive({ error: undefined, progress: 97, status: 'completing' })
      await executeApi(() => (
        UploadsService.completeUploadApiV1UploadsSessionIdCompletePost({
          requestBody: { parts: finalParts },
          sessionId: sessionId!,
          xClientOperationId: operationId,
          xDriveTransferProtocol: PROTOCOL,
        })
      ))
      assertActive()
      updateIfActive({ progress: 100, status: 'completed' })
    } catch (error) {
      if (isUploadAbortError(error) || cancelledTasks.current.has(taskId) || !isActive()) {
        return
      }
      updateIfActive({
        error: normalizeApiError(error).message,
        status: 'failed',
      })
    } finally {
      if (controllers.current.get(taskId) === controller) {
        controllers.current.delete(taskId)
      }
      if (runningTasks.current.get(taskId) === runCompletion) {
        runningTasks.current.delete(taskId)
      }
      resolveRun()
    }
  }, [updateTask])

  const enqueue = useCallback((
    nextFiles: File[],
    spaceId: string,
    parentId: string,
  ) => {
    const created = nextFiles.map<UploadTask>((file) => {
      const id = crypto.randomUUID()
      cancelledTasks.current.delete(id)
      files.current.set(id, file)
      return {
        fileName: file.name,
        id,
        lastModified: file.lastModified,
        parentId,
        progress: 0,
        size: file.size,
        spaceId,
        status: 'queued',
      }
    })
    setTasks((current) => {
      const next = [...created, ...current]
      tasksRef.current = next
      return next
    })
    created.forEach((task) => window.setTimeout(() => void run(task.id), 0))
  }, [run])

  const pause = useCallback((taskId: string) => {
    const task = tasksRef.current.find((item) => item.id === taskId)
    if (
      !task
      || task.status === 'completed'
      || task.status === 'cancelled'
      || task.status === 'completing'
    ) return
    controllers.current.get(taskId)?.abort()
    updateTask(taskId, { status: 'paused' })
  }, [updateTask])

  const resume = useCallback((taskId: string) => {
    const task = tasksRef.current.find((item) => item.id === taskId)
    if (
      !task
      || task.status === 'completed'
      || task.status === 'cancelled'
      || task.status === 'completing'
    ) return
    cancelledTasks.current.delete(taskId)
    updateTask(taskId, { error: undefined, status: 'queued' })
    window.setTimeout(() => void run(taskId), 0)
  }, [run, updateTask])

  const reattach = useCallback(async (taskId: string, file: File) => {
    const task = tasksRef.current.find((item) => item.id === taskId)
    if (
      !task
      || task.fileName !== file.name
      || task.size !== file.size
      || (
        task.lastModified !== undefined
        && task.lastModified > 0
        && file.lastModified > 0
        && task.lastModified !== file.lastModified
      )
    ) {
      updateTask(taskId, { error: '请选择名称、大小和修改时间一致的原文件' })
      return
    }
    files.current.set(taskId, file)
    cancelledTasks.current.delete(taskId)
    updateTask(taskId, {
      error: undefined,
      status: 'queued',
      verifyHashOnResume: Boolean(task.hash),
    })
    window.setTimeout(() => void run(taskId), 0)
  }, [run, updateTask])

  const cancel = useCallback(async (taskId: string) => {
    const task = tasksRef.current.find((item) => item.id === taskId)
    if (
      !task
      || task.status === 'completed'
      || task.status === 'cancelled'
      || task.status === 'completing'
    ) return
    cancelledTasks.current.add(taskId)
    controllers.current.get(taskId)?.abort()
    updateTask(taskId, { error: undefined, progress: 0, status: 'cancelled' })
    if (task?.sessionId) {
      await executeApi(() => (
        UploadsService.abortUploadApiV1UploadsSessionIdAbortPost({
          sessionId: task.sessionId!,
          xClientOperationId: crypto.randomUUID(),
          xDriveTransferProtocol: PROTOCOL,
        })
      )).catch(() => undefined)
    }
    files.current.delete(taskId)
  }, [updateTask])

  const dismiss = useCallback((taskId: string) => {
    setTasks((current) => {
      const next = current.filter((task) => task.id !== taskId)
      tasksRef.current = next
      return next
    })
    cancelledTasks.current.delete(taskId)
    files.current.delete(taskId)
  }, [])

  const value = useMemo(() => ({
    cancel,
    dismiss,
    enqueue,
    pause,
    reattach,
    resume,
    tasks,
  }), [cancel, dismiss, enqueue, pause, reattach, resume, tasks])

  return <UploadContext.Provider value={value}>{children}</UploadContext.Provider>
}
