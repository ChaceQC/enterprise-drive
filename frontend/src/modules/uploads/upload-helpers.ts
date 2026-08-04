import type { CompleteUploadPartRequest } from '../../api/generated'

export function expectedPartSize(
  fileSize: number,
  partSize: number,
  partNo: number,
): number {
  const start = (partNo - 1) * partSize
  return Math.max(0, Math.min(partSize, fileSize - start))
}

export function isUsableUploadPart(
  part: CompleteUploadPartRequest | undefined,
  {
    fileSize,
    partSize,
    totalParts,
  }: {
    fileSize: number
    partSize: number
    totalParts: number
  },
): part is CompleteUploadPartRequest & { size_bytes: number } {
  if (!part || !Number.isInteger(part.part_no) || part.part_no < 1 || part.part_no > totalParts) {
    return false
  }
  if (!part.etag?.trim() || !Number.isInteger(part.size_bytes)) {
    return false
  }
  return part.size_bytes === expectedPartSize(fileSize, partSize, part.part_no)
}

export function mergeUploadPart(
  parts: CompleteUploadPartRequest[],
  nextPart: CompleteUploadPartRequest,
  options: {
    fileSize: number
    partSize: number
    totalParts: number
  },
): CompleteUploadPartRequest[] {
  const merged = parts.filter((part) => part.part_no !== nextPart.part_no)
  if (isUsableUploadPart(nextPart, options)) {
    merged.push({
      ...nextPart,
      etag: nextPart.etag.trim(),
      size_bytes: nextPart.size_bytes,
    })
  }
  return merged.sort((left, right) => left.part_no - right.part_no)
}

export function buildCompleteUploadParts(
  parts: CompleteUploadPartRequest[],
  options: {
    fileSize: number
    partSize: number
    totalParts: number
  },
): CompleteUploadPartRequest[] | undefined {
  const byPartNo = new Map<number, CompleteUploadPartRequest>()
  for (const part of parts) {
    if (isUsableUploadPart(part, options)) {
      byPartNo.set(part.part_no, {
        ...part,
        etag: part.etag.trim(),
        size_bytes: part.size_bytes,
      })
    }
  }
  if (byPartNo.size !== options.totalParts) {
    return undefined
  }
  return Array.from(byPartNo.values()).sort((left, right) => left.part_no - right.part_no)
}
