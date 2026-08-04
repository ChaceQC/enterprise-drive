import { act, render, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  CancelablePromise,
  type InstantUploadResponse,
  type MultipartUploadResponse,
  type UploadSessionStatusResponse,
  UploadsService,
} from '../../api/generated'
import {
  type UploadContextValue,
  type UploadTask,
} from './upload-context'
import { UploadProvider } from './UploadProvider'
import { useUploads } from './useUploads'

const hashMocks = vi.hoisted(() => ({
  createSHA256: vi.fn(),
}))

vi.mock('hash-wasm', () => ({
  createSHA256: hashMocks.createSHA256,
}))

const STORAGE_KEY = 'drive_upload_queue_v1'
const FILE_HASH = 'a'.repeat(64)

function resolvedCancelable<T>(value: T): CancelablePromise<T> {
  return new CancelablePromise<T>((resolve) => resolve(value))
}

function uploadStatus(
  overrides: Partial<UploadSessionStatusResponse> = {},
): UploadSessionStatusResponse {
  return {
    completed_node_id: null,
    completed_version_id: null,
    expected_current_version_id: null,
    expires_at: '2099-01-01T00:00:00Z',
    file_name: 'resume.txt',
    max_parallelism: 1,
    part_size_bytes: 1,
    session_id: 'session-existing',
    size_bytes: 1,
    status: 'uploading',
    target_node_id: null,
    total_parts: 1,
    uploaded_parts: [],
    ...overrides,
  }
}

function instantUpload(): InstantUploadResponse | MultipartUploadResponse {
  return {
    blob_id: 'blob-1',
    node_id: 'node-1',
    version_id: 'version-1',
  }
}

function UploadProbe({
  onChange,
}: {
  onChange: (value: UploadContextValue) => void
}) {
  const uploads = useUploads()

  useEffect(() => {
    onChange(uploads)
  }, [onChange, uploads])

  return null
}

async function renderProvider(): Promise<() => UploadContextValue> {
  let current: UploadContextValue | undefined
  const onChange = (value: UploadContextValue) => {
    current = value
  }

  render(
    <UploadProvider>
      <UploadProbe onChange={onChange} />
    </UploadProvider>,
  )

  await waitFor(() => expect(current).toBeDefined())
  return () => current!
}

describe('UploadProvider resume boundaries', () => {
  beforeEach(() => {
    localStorage.clear()
    hashMocks.createSHA256.mockReset()
    hashMocks.createSHA256.mockImplementation(async () => ({
      digest: () => FILE_HASH,
      init: vi.fn(),
      update: vi.fn(),
    }))
  })

  it('reinitializes an active-looking session whose expires_at has passed', async () => {
    const persistedTask: UploadTask = {
      fileName: 'resume.txt',
      hash: FILE_HASH,
      id: 'upload-expired',
      lastModified: 123,
      parentId: 'parent-1',
      parts: [],
      progress: 45,
      sessionId: 'session-expired',
      size: 1,
      spaceId: 'space-1',
      status: 'uploading',
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify([persistedTask]))

    const statusSpy = vi.spyOn(
      UploadsService,
      'getUploadStatusApiV1UploadsSessionIdGet',
    ).mockReturnValue(resolvedCancelable(uploadStatus({
      expires_at: '2000-01-01T00:00:00Z',
      session_id: 'session-expired',
    })))
    const initSpy = vi.spyOn(
      UploadsService,
      'initUploadApiV1UploadsInitPost',
    ).mockReturnValue(resolvedCancelable(instantUpload()))
    const presignSpy = vi.spyOn(
      UploadsService,
      'presignUploadPartApiV1UploadsSessionIdPartsPartNoPresignPost',
    )

    const uploads = await renderProvider()
    const file = new File(['x'], 'resume.txt', {
      lastModified: 123,
      type: 'text/plain',
    })

    await act(async () => {
      await uploads().reattach('upload-expired', file)
    })

    await waitFor(() => {
      expect(uploads().tasks[0]?.status).toBe('completed')
    })
    expect(statusSpy).toHaveBeenCalledOnce()
    expect(initSpy).toHaveBeenCalledOnce()
    expect(presignSpy).not.toHaveBeenCalled()
  })

  it('starts the queued continuation after a paused hashing run exits', async () => {
    let resolveFirstRead: ((value: ArrayBuffer) => void) | undefined
    const firstRead = new Promise<ArrayBuffer>((resolve) => {
      resolveFirstRead = resolve
    })
    const file = new File(['x'], 'fast-resume.txt', {
      lastModified: 456,
      type: 'text/plain',
    })
    let sliceCount = 0
    Object.defineProperty(file, 'slice', {
      configurable: true,
      value: vi.fn(() => {
        sliceCount += 1
        return {
          arrayBuffer: () => (
            sliceCount === 1
              ? firstRead
              : Promise.resolve(new Uint8Array([120]).buffer)
          ),
          size: 1,
        } as Blob
      }),
    })

    const initSpy = vi.spyOn(
      UploadsService,
      'initUploadApiV1UploadsInitPost',
    ).mockReturnValue(resolvedCancelable(instantUpload()))
    const uploads = await renderProvider()

    act(() => {
      uploads().enqueue([file], 'space-1', 'parent-1')
    })
    await waitFor(() => {
      expect(uploads().tasks[0]?.status).toBe('hashing')
    })
    const taskId = uploads().tasks[0]!.id

    act(() => {
      uploads().pause(taskId)
      uploads().resume(taskId)
    })
    await new Promise((resolve) => window.setTimeout(resolve, 10))
    expect(initSpy).not.toHaveBeenCalled()

    await act(async () => {
      resolveFirstRead!(new Uint8Array([120]).buffer)
      await firstRead
    })

    await waitFor(() => {
      expect(uploads().tasks[0]?.status).toBe('completed')
    })
    expect(sliceCount).toBe(2)
    expect(initSpy).toHaveBeenCalledOnce()
  })
})
