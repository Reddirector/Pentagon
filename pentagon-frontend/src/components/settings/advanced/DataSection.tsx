/**
 * The Advanced tab's Data section: documents, memories, threads and the
 * browser reset. Lists load when their effect mounts, exactly as they did
 * when these lived in the dialog body.
 */
import { useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { apiRequest, getLocalUserId } from '../../../api'
import type { Conversation, DocumentInfo, MemoryInfo } from '../../../types'
import { Section, ThreadRow } from '../shared'

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
  // Deleting a document used to fail silently, so a broken request looked
  // exactly like a click that did nothing.
  const [documentError, setDocumentError] = useState('')
  // Memories are loaded once when the dialog opens: null means "still
  // loading", an empty array means the store is genuinely empty.
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
      // remove_document is scoped by owner, so it needs the same user_id the
      // upload and list calls send. Without it the request is a 422 and the
      // document silently refuses to delete.
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
    <>
      <Section title="Documents" hint={`${documentCount} attached to this thread. Removing one deletes its stored chunks.`}>
        {documents.length === 0 ? (
          <p className="text-small text-zinc-600">Nothing here yet.</p>
        ) : (
          <ul className="space-y-1.5">
            {documents.map((document) => (
              <li key={document.document_id} className="flex items-center gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
                <span className="min-w-0 flex-1 truncate text-small-lg text-zinc-300">{document.filename}</span>
                <span className="shrink-0 text-micro text-zinc-600">{document.chunks_stored} chunks</span>
                <button
                  type="button"
                  onClick={() => removeDocument(document.document_id)}
                  aria-label={`Delete ${document.filename}`}
                  className="shrink-0 rounded-md p-1 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-200"
                >
                  <Trash2 size={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
        {documentError && <p className="mt-2 text-small text-amber-300/90">{documentError}</p>}
      </Section>

      <Section
        title="Memories"
        hint="Facts the model kept with remember. A memory enters a conversation only when the model asks for it with recall; nothing here loads on its own."
      >
        {memoryError && <p className="mb-2 text-small text-amber-300/90">{memoryError}</p>}
        {memories === null ? (
          <p className="text-small text-zinc-600">Loading…</p>
        ) : memories.length === 0 ? (
          <p className="text-small text-zinc-600">Nothing here yet.</p>
        ) : (
          <ul className="space-y-1.5">
            {memories.map((memory) => (
              <li
                key={memory.id}
                className="flex items-start gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2"
              >
                <span className="min-w-0 flex-1">
                  {memory.label && (
                    <span className="mr-2 rounded border border-white/[0.1] px-1.5 py-0.5 text-micro text-zinc-500">
                      {memory.label}
                    </span>
                  )}
                  <span className="text-small-lg text-zinc-300">{memory.text}</span>
                  <span className="mt-0.5 block text-micro text-zinc-600">
                    {memory.created_at.slice(0, 10)}
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => void removeMemory(memory.id)}
                  aria-label={`Delete memory: ${memory.text.slice(0, 40)}`}
                  className="shrink-0 rounded-md p-1 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-200"
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
        hint={`${threadCount} thread${threadCount === 1 ? '' : 's'} in this workspace. Renaming updates the sidebar; deleting removes the thread and its messages from the server.`}
      >
        {threads.length === 0 ? (
          <p className="text-small text-zinc-600">Nothing here yet.</p>
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

      <Section title="This browser" hint="Appearance, contrast, text size, density, sidebar layout, ambient mode and the default model.">
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
    </>
  )
}

// Imported here rather than at the top to keep the module's obvious dependency
// list in one place with its only use site.
import { resetPreferences } from '../../../lib/preferences'
