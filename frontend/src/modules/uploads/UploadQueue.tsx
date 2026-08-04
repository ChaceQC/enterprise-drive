import {
  CircleCheck,
  Pause,
  Play,
  RotateCcw,
  Trash2,
  UploadCloud,
} from 'lucide-react'

import { formatBytes } from '../../lib/format'
import { IconButton } from '../../components/ui'
import { useUploads } from './useUploads'

const statusLabels = {
  cancelled: '已取消',
  completing: '正在完成',
  completed: '已完成',
  failed: '需要重试',
  hashing: '正在校验',
  paused: '已暂停',
  queued: '等待中',
  uploading: '正在上传',
  'waiting-file': '等待重新选择文件',
} as const

export function UploadQueue() {
  const {
    cancel,
    dismiss,
    pause,
    reattach,
    resume,
    tasks,
  } = useUploads()

  if (tasks.length === 0) return null

  return (
    <aside aria-label="上传队列" className="upload-queue">
      <header>
        <div>
          <UploadCloud size={18} />
          <strong>上传队列</strong>
        </div>
        <span>{tasks.filter((task) => task.status === 'completed').length}/{tasks.length}</span>
      </header>
      <div className="upload-list">
        {tasks.map((task) => (
          <article key={task.id}>
            <div className="upload-copy">
              <strong title={task.fileName}>{task.fileName}</strong>
              <span>{formatBytes(task.size)} · {statusLabels[task.status]}</span>
            </div>
            <div className="progress-track">
              <span style={{ width: `${task.progress}%` }} />
            </div>
            {task.error ? <p className="upload-error">{task.error}</p> : null}
            <div className="upload-actions">
              {task.status === 'uploading' || task.status === 'hashing' ? (
                <IconButton icon={Pause} label="暂停" onClick={() => pause(task.id)} />
              ) : null}
              {task.status === 'paused' || task.status === 'failed' ? (
                <IconButton icon={Play} label="继续" onClick={() => resume(task.id)} />
              ) : null}
              {task.status === 'waiting-file' ? (
                <label className="file-reattach">
                  <RotateCcw size={15} />
                  选择原文件
                  <input
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      if (file) void reattach(task.id, file)
                    }}
                    type="file"
                  />
                </label>
              ) : null}
              {task.status === 'completed' ? (
                <CircleCheck className="success-icon" size={18} />
              ) : null}
              {task.status === 'completing' ? <span>请稍候</span> : null}
              {task.status === 'completed' || task.status === 'cancelled' ? (
                <IconButton icon={Trash2} label="移除" onClick={() => dismiss(task.id)} />
              ) : task.status !== 'completing' ? (
                <IconButton
                  icon={Trash2}
                  label="取消上传"
                  onClick={() => void cancel(task.id)}
                  tone="danger"
                />
              ) : null}
            </div>
          </article>
        ))}
      </div>
    </aside>
  )
}
