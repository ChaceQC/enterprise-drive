import {
  Download,
  FileSearch,
  Search,
  Sparkles,
} from 'lucide-react'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { FilesService, SearchService } from '../../api/generated'
import { executeApi } from '../../api/runtime'
import {
  EmptyState,
  ErrorNotice,
  IconButton,
  LoadingBlock,
  PageHeader,
} from '../../components/ui'
import { formatBytes, formatDate } from '../../lib/format'

export function SearchPage() {
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const result = useQuery({
    enabled: query.length > 0,
    queryKey: ['search', query],
    queryFn: () => executeApi(() => SearchService.searchFilesApiV1SearchGet({
      limit: 50,
      q: query,
    })),
  })

  const download = async (nodeId: string) => {
    const response = await executeApi(() => FilesService.createDownloadUrlApiV1FilesNodeIdDownloadGet({
      nodeId,
      xDriveTransferProtocol: 'DTP/1',
    }))
    window.open(response.download_url, '_blank', 'noopener,noreferrer')
  }

  return (
    <div className="page-stack">
      <PageHeader
        description="搜索只展示当前会话有权限读取的文件，服务端负责 ACL 过滤。"
        eyebrow="内容检索"
        title="搜索文件"
      />
      <form
        className="search-bar"
        onSubmit={(event) => {
          event.preventDefault()
          setQuery(input.trim())
        }}
      >
        <Search size={19} />
        <input
          aria-label="搜索关键词"
          onChange={(event) => setInput(event.target.value)}
          placeholder="输入文件名、正文或标签…"
          value={input}
        />
        <button className="button primary" disabled={!input.trim()} type="submit">
          搜索
        </button>
      </form>

      {query ? (
        <div className="result-heading">
          <div>
            <span className="eyebrow">结果</span>
            <h2>“{query}”</h2>
          </div>
          {result.data ? <span>{result.data.total} 个结果</span> : null}
        </div>
      ) : (
        <EmptyState
          description="支持文件名和已建立索引的正文内容。"
          icon={Sparkles}
          title="从一个关键词开始"
        />
      )}

      {result.isLoading ? <LoadingBlock label="正在检索…" /> : null}
      {result.error ? <ErrorNotice error={result.error} onRetry={() => void result.refetch()} /> : null}
      {result.data && result.data.items.length === 0 ? (
        <EmptyState description="换一个更短的关键词，或确认文件已经完成索引。" icon={FileSearch} title="没有匹配结果" />
      ) : null}
      {result.data?.items.length ? (
        <section className="table-plane">
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>文件</th><th>空间</th><th>大小</th><th>更新时间</th><th className="numeric">操作</th></tr></thead>
              <tbody>
                {result.data.items.map((item) => (
                  <tr key={item.node_id}>
                    <td><div className="file-name-button"><span className="file-glyph"><FileSearch size={16} /></span><span><strong>{item.name}</strong><small>{item.mime_type ?? '未知类型'}</small></span></div></td>
                    <td className="muted-cell">{item.space_id.slice(0, 8)}</td>
                    <td className="muted-cell">{formatBytes(item.size_bytes)}</td>
                    <td className="muted-cell">{formatDate(item.updated_at)}</td>
                    <td className="numeric"><IconButton icon={Download} label="下载" onClick={() => void download(item.node_id)} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  )
}
