/**
 * The Advanced tab's Audit log and About sections. The audit list loads when
 * its section becomes visible, filtered by category and decision, exactly as
 * the dialog's own effect did.
 */
import { useEffect, useState } from 'react'
import { fetchAuditLog } from '../../../api'
import type { AuditLogEntry, AutonomySettings } from '../../../types'
import { Section } from '../shared'

const SHORTCUTS: [string, string][] = [
  ['⌘ K', 'Command palette'],
  ['/', 'Focus the composer'],
  ['⌘ ⇧ O', 'New thread'],
  ['Alt ↑ / ↓', 'Jump between answers'],
  ['Esc', 'Close a dialog'],
]

export function AuditLogSection({
  userId,
  autonomySettings,
}: {
  userId: string
  autonomySettings: AutonomySettings | null
}) {
  const [auditRows, setAuditRows] = useState<AuditLogEntry[]>([])
  const [auditLoading, setAuditLoading] = useState(false)
  const [auditCategory, setAuditCategory] = useState('')
  const [auditDecision, setAuditDecision] = useState('')

  useEffect(() => {
    let active = true
    async function load() {
      setAuditLoading(true)
      try {
        const { rows } = await fetchAuditLog(
          userId,
          80,
          undefined,
          auditCategory || undefined,
          auditDecision || undefined,
        )
        if (active) setAuditRows(rows)
      } catch {
        if (active) setAuditRows([])
      } finally {
        if (active) setAuditLoading(false)
      }
    }
    void load()
    return () => { active = false }
  }, [userId, auditCategory, auditDecision])

  return (
    <Section
      title="Audit log"
      hint="Every tool call the permission system handled, newest first. Filter by category or by decision."
    >
      <div className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <label className="flex items-center gap-2 text-micro text-zinc-500">
            Category
            <select
              value={auditCategory}
              onChange={(event) => setAuditCategory(event.target.value)}
              className="h-7 rounded border border-white/[0.1] bg-black px-2 text-micro text-zinc-200 outline-none focus:border-white/30"
            >
              <option value="">All</option>
              {autonomySettings?.categories && Object.entries(autonomySettings.categories).map(([cat, meta]) => (
                <option key={cat} value={cat}>{(meta as { label: string }).label}</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-micro text-zinc-500">
            Decision
            <select
              value={auditDecision}
              onChange={(event) => setAuditDecision(event.target.value)}
              className="h-7 rounded border border-white/[0.1] bg-black px-2 text-micro text-zinc-200 outline-none focus:border-white/30"
            >
              <option value="">All</option>
              <option value="auto_approved">Auto-approved</option>
              <option value="user_approved">User-approved</option>
              <option value="user_denied">User-denied</option>
              <option value="blocked_never_allow">Blocked</option>
            </select>
          </label>
        </div>
        {auditLoading ? (
          <p className="text-small text-zinc-600">Loading…</p>
        ) : auditRows.length === 0 ? (
          <p className="text-small text-zinc-600">Nothing logged yet.</p>
        ) : (
          <ul className="space-y-1.5">
            {auditRows.map((row) => (
              <li key={row.id} className="flex items-start gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
                <span className="min-w-0 flex-1">
                  <span className="text-small text-zinc-200">{row.tool_name}</span>
                  <span className="ml-2 rounded border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 text-micro text-zinc-500">
                    {row.decision}
                  </span>
                  <span className="ml-1.5 rounded border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 text-micro text-zinc-500">
                    {row.category}
                  </span>
                  <span className="mt-0.5 block text-micro leading-5 text-zinc-600">
                    {row.arguments_summary ||
                      (row.tool_name && `No details recorded.`)}
                  </span>
                  <span className="mt-1 block text-micro text-zinc-700">
                    {new Date(row.timestamp).toLocaleString()}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Section>
  )
}

export function AboutSection() {
  return (
    <>
      <Section title="Pentagon">
        <p className="text-small-lg leading-[1.7] text-zinc-500">
          A personal AI workspace. FastAPI and LangGraph on the server, React and Vite in the
          browser, models served by NVIDIA NIM. Your key, documents and threads stay on your own
          machine and server.
        </p>
      </Section>

      <Section title="Keyboard" hint="The composer keeps focus while you work.">
        <dl className="grid gap-2 sm:grid-cols-2">
          {SHORTCUTS.map(([keys, description]) => (
            <div key={keys} className="flex items-center gap-2.5">
              <dt className="shrink-0 rounded-md border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 font-mono text-micro text-zinc-400">
                {keys}
              </dt>
              <dd className="min-w-0 truncate text-small text-zinc-600">{description}</dd>
            </div>
          ))}
        </dl>
      </Section>
    </>
  )
}
