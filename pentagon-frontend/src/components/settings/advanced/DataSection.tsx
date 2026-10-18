/**
 * The Advanced tab's Data section: RAG documents, memories, threads and browser preferences.
 * Redesigned with less text and more graphics/metrics, fully responsive across viewports.
 */
import { useEffect, useState } from 'react'
import {
  Brain,
  FileSpreadsheet,
  FileText,
  Layers,
  MessageSquare,
  Trash2,
} from 'lucide-react'
import { apiRequest, getLocalUserId } from '../../../api'
import type { Conversation, DocumentInfo, MemoryInfo } from '../../../types'
import { Section, ThreadRow } from '../shared'
import { resetPreferences } from '../../../lib/preferences'

function getFileIcon(filename: string) {
  if (/\.xlsx?|\.csv/i.test(filename)) return FileSpreadsheet
  return FileText
}

export function DataSection({
  userId,
  documents,
  documentCount,
  threads,
  threadCount,
  onDocumentDeleted,
  onRenameThread,
  onDeleteThread,
  onJumpToAppearance,
}: {
  userId: string
  documents: DocumentInfo[]
  documentCount: number
  threads: Conversation[]
  threadCount: number
  onDocumentDeleted: (documentId: string) => void
  onRenameThread: (id: string, title: string) => void
  onDeleteThread: (id: string) => void
  onJumpToAppearance: () => void
}) {
  const [documentError, setDocumentError] = useState('')
  const [memories, setMemories] = useState<MemoryInfo[] | null>(null)
  const [memoryError, setMemoryError] = useState('')

  useEffect(() => {
    let active = true
    void apiRequest<MemoryInfo[]>(`/api/memories?user_id=${encodeURIComponent(userId)}`)
      .then((rows) => {
        if (active) setMemories(rows)
      })
      .catch((cause) => {
        if (!active) return
        setMemoryError(
          cause instanceof Error ? cause.message : 'Could not load memories.',
        )
        setMemories([])
      })
    return () => {
      active = false
    }
  }, [userId])

  async function removeMemory(memoryId: string) {
    setMemoryError('')
    try {
      await apiRequest(
        `/api/memories/${encodeURIComponent(memoryId)}?user_id=${encodeURIComponent(userId)}`,
        { method: 'DELETE' },
      )
      setMemories((rows) => (rows ?? []).filter((row) => row.id !== memoryId))
    } catch (cause) {
      setMemoryError(
        cause instanceof Error ? cause.message : 'Could not delete that memory.',
      )
    }
  }

  async function removeDocument(documentId: string) {
    setDocumentError('')
    try {
      await apiRequest(
        `/api/documents/${encodeURIComponent(documentId)}?user_id=${encodeURIComponent(getLocalUserId())}`,
        { method: 'DELETE' },
      )
      onDocumentDeleted(documentId)
    } catch (cause) {
      setDocumentError(
        cause instanceof Error ? cause.message : 'Could not delete that document.',
      )
    }
  }

  return (
    <div className="space-y-5">
      {/* Visual RAG & Memory Overview Metrics */}
      <div className="grid grid-cols-3 gap-2.5 max-sm:grid-cols-1">
        <div className="flex items-center gap-3 rounded-xl border border-white/[0.08] bg-white/[0.02] p-3">
          <div className="grid size-9 place-items-center rounded-lg border border-emerald-400/30 bg-emerald-400/10 text-emerald-400">
            <Layers size={16} />
          </div>
          <div>
            <div className="text-body font-semibold text-white">{documentCount}</div>
            <div className="text-[11px] text-zinc-500">RAG Documents</div>
          </div>
        </div>
        <div className="flex items-center gap-3 rounded-xl border border-white/[0.08] bg-white/[0.02] p-3">
          <div className="grid size-9 place-items-center rounded-lg border border-purple-400/30 bg-purple-400/10 text-purple-400">
            <Brain size={16} />
          </div>
          <div>
            <div className="text-body font-semibold text-white">{memories?.length ?? 0}</div>
            <div className="text-[11px] text-zinc-500">Learned Memories</div>
          </div>
        </div>
        <div className="flex items-center gap-3 rounded-xl border border-white/[0.08] bg-white/[0.02] p-3">
          <div className="grid size-9 place-items-center rounded-lg border border-sky-400/30 bg-sky-400/10 text-sky-400">
            <MessageSquare size={16} />
          </div>
          <div>
            <div className="text-body font-semibold text-white">{threadCount}</div>
            <div className="text-[11px] text-zinc-500">Workspace Threads</div>
          </div>
        </div>
      </div>

      <Section title="RAG Knowledge Base" hint="Source documents indexed for semantic vector retrieval.">
        {documents.length === 0 ? (
          <p className="text-small text-zinc-600">No documents indexed in this thread.</p>
        ) : (
          <ul className="space-y-2">
            {documents.map((document) => {
              const FileIcon = getFileIcon(document.filename)
              return (
                <li key={document.document_id} className="flex items-center justify-between gap-3 rounded-xl border border-white/[0.07] bg-white/[0.02] p-2.5 transition hover:border-white/[0.12]">
                  <div className="flex min-w-0 flex-1 items-center gap-2.5">
                    <div className="grid size-8 shrink-0 place-items-center rounded-lg bg-emerald-400/10 text-emerald-400">
                      <FileIcon size={14} />
                    </div>
                    <span className="min-w-0 flex-1 truncate text-small font-medium text-zinc-200">{document.filename}</span>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="rounded-md border border-white/[0.08] bg-white/[0.03] px-2 py-0.5 font-mono text-[10px] text-emerald-400">
                      {document.chunks_stored} chunks
                    </span>
                    <button
                      type="button"
                      onClick={() => removeDocument(document.document_id)}
                      aria-label={`Delete ${document.filename}`}
                      className="grid size-7 place-items-center rounded-lg text-zinc-500 transition hover:bg-rose-400/10 hover:text-rose-400"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
        {documentError && <p className="mt-2 text-small text-amber-300/90">{documentError}</p>}
      </Section>

      <Section
        title="Memories"
        hint="Semantic facts remembered across sessions."
      >
        {memoryError && <p className="mb-2 text-small text-amber-300/90">{memoryError}</p>}
        {memories === null ? (
          <p className="text-small text-zinc-600">Loading…</p>
        ) : memories.length === 0 ? (
          <p className="text-small text-zinc-600">No memories stored yet.</p>
        ) : (
          <ul className="space-y-2">
            {memories.map((memory) => (
              <li
                key={memory.id}
                className="flex items-start justify-between gap-3 rounded-xl border border-white/[0.07] bg-white/[0.02] p-3 transition hover:border-white/[0.12]"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {memory.label && (
                      <span className="rounded border border-purple-400/30 bg-purple-400/10 px-1.5 py-0.5 font-mono text-[10px] text-purple-300">
                        {memory.label}
                      </span>
                    )}
                    <span className="text-[10px] text-zinc-500">{memory.created_at.slice(0, 10)}</span>
                  </div>
                  <div className="mt-1 text-small text-zinc-300">{memory.text}</div>
                </div>
                <button
                  type="button"
                  onClick={() => void removeMemory(memory.id)}
                  aria-label={`Delete memory: ${memory.text.slice(0, 40)}`}
                  className="grid size-7 shrink-0 place-items-center rounded-lg text-zinc-500 transition hover:bg-rose-400/10 hover:text-rose-400"
                >
                  <Trash2 size={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="Threads"
        hint="Saved workspace conversations."
      >
        {threads.length === 0 ? (
          <p className="text-small text-zinc-600">No conversations recorded yet.</p>
        ) : (
          <ul className="space-y-1.5">
            {threads.map((thread) => (
              <ThreadRow
                key={thread.id}
                thread={thread}
                onRename={onRenameThread}
                onDelete={onDeleteThread}
              />
            ))}
          </ul>
        )}
      </Section>

      <Section title="This Browser" hint="Reset locally cached preferences and layout.">
        <button
          type="button"
          onClick={() => {
            resetPreferences()
            onJumpToAppearance()
          }}
          className="h-9 rounded-lg border border-white/[0.09] px-3.5 text-small text-zinc-300 transition hover:bg-white/[0.05]"
        >
          Reset appearance and defaults
        </button>
      </Section>
    </div>
  )
}
