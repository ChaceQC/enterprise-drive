import type { CompleteUploadPartRequest } from '../../api/generated'
import {
  buildCompleteUploadParts,
  mergeUploadPart,
} from './upload-helpers'

const options = {
  fileSize: 10,
  partSize: 5,
  totalParts: 2,
}

function part(
  partNo: number,
  etag: string,
  sizeBytes: number,
): CompleteUploadPartRequest {
  return { etag, part_no: partNo, size_bytes: sizeBytes }
}

describe('upload part completion guards', () => {
  it('drops missing or empty ETags before completion', () => {
    expect(buildCompleteUploadParts([
      part(1, '', 5),
      part(2, 'etag-2', 5),
    ], options)).toBeUndefined()
  })

  it('rejects stale sizes and duplicate part numbers', () => {
    expect(buildCompleteUploadParts([
      part(1, 'old', 4),
      part(1, 'new', 5),
      part(2, 'etag-2', 5),
    ], options)).toEqual([
      part(1, 'new', 5),
      part(2, 'etag-2', 5),
    ])
  })

  it('replaces a retried part and keeps the canonical order', () => {
    expect(mergeUploadPart([
      part(2, 'etag-2', 5),
      part(1, 'old', 5),
    ], part(1, 'new', 5), options)).toEqual([
      part(1, 'new', 5),
      part(2, 'etag-2', 5),
    ])
  })
})
