import { useCallback, useEffect, useState } from 'react'
import {
  AlertCircle,
  Brain,
  Check,
  ChevronDown,
  ChevronRight,
  Clock,
  Database,
  Folder,
  Globe,
  LoaderCircle,
  Play,
  Plus,
  RefreshCw,
  Server,
  Terminal,
  Trash2,
  X,
  Zap,
} from 'lucide-react'
import { apiRequest } from '../../../api'
import type { McpPreset, McpServerInfo, McpToolInfo } from '../../../types'
import { Section, inputClass, selectClass } from '../shared'

const PRESET_ICONS: Record<string, typeof Database> = {
  sqlite: Database,
  time: Clock,
  filesystem: Folder,
  fetch: Globe,
  memory: Brain,
  github: Server,
}

export function McpSection({ userId: _userId }: { userId: string }) {
  const [servers, setServers] = useState<McpServerInfo[] | null>(null)
  const [presets, setPresets] = useState<McpPreset[]>([])
  const [problems, setProblems] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  
  // Expanded server tools viewer
  const [expandedServer, setExpandedServer] = useState<string | null>(null)

  // Test state
  const [testingServer, setTestingServer] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; latency_ms: number; tools_count: number; error?: string }>>({})

  // Add / Edit Form modal state
  const [showAddForm, setShowAddForm] = useState(false)
  const [savingServer, setSavingServer] = useState(false)
  const [formName, setFormName] = useState('')
  const [formCommand, setFormCommand] = useState('')
  const [formTier, setFormTier] = useState('write')
  const [formEnv, setFormEnv] = useState<Array<{ key: string; value: string }>>([])
  const [testingDraft, setTestingDraft] = useState(false)
  const [draftTestResult, setDraftTestResult] = useState<{ success: boolean; latency_ms: number; tools_count: number; error?: string } | null>(null)

  const loadData = useCallback(async (showSpinner = false) => {
    try {
      if (showSpinner) setLoading(true)
      const data = await apiRequest<{ servers: McpServerInfo[]; presets: McpPreset[]; problems: string[] }>('/api/mcp')
      setServers(data.servers)
      setPresets(data.presets || [])
      setProblems(data.problems || [])
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load MCP servers.')
      setServers([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    apiRequest<{ servers: McpServerInfo[]; presets: McpPreset[]; problems: string[] }>('/api/mcp')
      .then(data => {
        if (cancelled) return
        setServers(data.servers)
        setPresets(data.presets || [])
        setProblems(data.problems || [])
        setError('')
      })
      .catch(cause => {
        if (cancelled) return
        setError(cause instanceof Error ? cause.message : 'Could not load MCP servers.')
        setServers([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleToggle = async (server: McpServerInfo, nextEnabled: boolean) => {
    try {
      await apiRequest(`/api/mcp/${encodeURIComponent(server.name)}/toggle`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: nextEnabled }),
      })
      setServers((current) =>
        (current || []).map((s) => (s.name === server.name ? { ...s, enabled: nextEnabled, status: nextEnabled ? 'connected' : 'disabled' } : s)),
      )
      setNotice(`MCP server ${server.name} ${nextEnabled ? 'enabled' : 'disabled'}.`)
      void loadData()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not toggle server.')
    }
  }

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete MCP server "${name}"? Remote tools will be removed from Pentagon.`)) return
    try {
      await apiRequest(`/api/mcp/${encodeURIComponent(name)}`, { method: 'DELETE' })
      setServers((current) => (current || []).filter((s) => s.name !== name))
      setNotice(`Server "${name}" removed.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not delete server.')
    }
  }

  const handleTestExisting = async (name: string) => {
    setTestingServer(name)
    try {
      const res = await apiRequest<{ success: boolean; latency_ms: number; tools_count: number; error?: string }>(
        `/api/mcp/${encodeURIComponent(name)}/test`,
        { method: 'POST' },
      )
      setTestResults((prev) => ({ ...prev, [name]: res }))
      if (res.success) {
        setNotice(`Handshake successful: ${res.tools_count} tool(s) in ${res.latency_ms}ms.`)
      } else {
        setError(`Handshake failed: ${res.error}`)
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Test failed.')
    } finally {
      setTestingServer(null)
    }
  }

  const handleReloadAll = async () => {
    try {
      setLoading(true)
      const res = await apiRequest<{ ok: boolean; active_connected: number }>('/api/mcp/reload', { method: 'POST' })
      setNotice(`Reloaded all MCP servers: ${res.active_connected} active session(s).`)
      await loadData()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not reload MCP servers.')
    } finally {
      setLoading(false)
    }
  }

  const parseCommandInput = (raw: string): string[] => {
    const trimmed = raw.trim()
    if (!trimmed) return []
    // If it looks like JSON array, try parsing
    if (trimmed.startsWith('[')) {
      try {
        const parsed = JSON.parse(trimmed)
        if (Array.isArray(parsed)) return parsed.map(String)
      } catch {
        // Fall back to space splitting
      }
    }
    // Handle space-separated tokens with quoted strings
    const regex = /[^\s"']+|"([^"]*)"|'([^']*)'/g
    const matches: string[] = []
    let match
    while ((match = regex.exec(trimmed)) !== null) {
      matches.push(match[1] || match[2] || match[0])
    }
    return matches
  }

  const applyPreset = (preset: McpPreset) => {
    setFormName(preset.name)
    setFormCommand(preset.command.join(' '))
    setFormTier(preset.tier)
    const envEntries = Object.entries(preset.env || {}).map(([key, value]) => ({ key, value }))
    // Ensure required envs are present
    for (const req of preset.required_env || []) {
      if (!envEntries.some((e) => e.key === req)) {
        envEntries.push({ key: req, value: '' })
      }
    }
    setFormEnv(envEntries)
    setDraftTestResult(null)
    setShowAddForm(true)
  }

  const handleTestDraft = async () => {
    const parts = parseCommandInput(formCommand)
    if (!parts.length) {
      setError('Enter a command to test.')
      return
    }
    setTestingDraft(true)
    setDraftTestResult(null)
    setError('')
    try {
      const envObj: Record<string, string> = {}
      for (const entry of formEnv) {
        if (entry.key.trim()) envObj[entry.key.trim()] = entry.value.trim()
      }
      const res = await apiRequest<{ success: boolean; latency_ms: number; tools_count: number; error?: string }>('/api/mcp/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          command: parts,
          tier: formTier,
          env: envObj,
        }),
      })
      setDraftTestResult(res)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Draft test failed.')
    } finally {
      setTestingDraft(false)
    }
  }

  const handleSaveForm = async (event: React.FormEvent) => {
    event.preventDefault()
    const name = formName.trim().toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '')
    if (!name) {
      setError('Please provide a valid server name.')
      return
    }
    const commandParts = parseCommandInput(formCommand)
    if (!commandParts.length) {
      setError('Please provide a command (e.g. uvx mcp-server-sqlite --db-path ./pentagon.db).')
      return
    }
    const envObj: Record<string, string> = {}
    for (const entry of formEnv) {
      if (entry.key.trim()) envObj[entry.key.trim()] = entry.value.trim()
    }
    setSavingServer(true)
    setError('')
    try {
      await apiRequest('/api/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          command: commandParts,
          tier: formTier,
          env: envObj,
          enabled: true,
        }),
      })
      setNotice(`MCP server "${name}" configured and connected!`)
      setShowAddForm(false)
      setFormName('')
      setFormCommand('')
      setFormEnv([])
      setDraftTestResult(null)
      await loadData()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save MCP server.')
    } finally {
      setSavingServer(false)
    }
  }

  const tierBadge = (tier: string) => {
    switch (tier) {
      case 'read':
        return <span className="rounded-md border border-emerald-400/20 bg-emerald-400/10 px-1.5 py-0.5 text-micro font-medium text-emerald-300">read</span>
      case 'destructive':
        return <span className="rounded-md border border-rose-400/20 bg-rose-400/10 px-1.5 py-0.5 text-micro font-medium text-rose-300">destructive</span>
      default:
        return <span className="rounded-md border border-amber-400/20 bg-amber-400/10 px-1.5 py-0.5 text-micro font-medium text-amber-300">write</span>
    }
  }

  const statusDot = (status: string) => {
    switch (status) {
      case 'connected':
        return (
          <span className="flex items-center gap-1.5 text-micro text-emerald-400">
            <span className="relative flex size-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex size-2 rounded-full bg-emerald-400" />
            </span>
            Active
          </span>
        )
      case 'error':
        return (
          <span className="flex items-center gap-1.5 text-micro text-rose-400">
            <span className="size-2 rounded-full bg-rose-400" />
            Error
          </span>
        )
      case 'disabled':
        return (
          <span className="flex items-center gap-1.5 text-micro text-zinc-500">
            <span className="size-2 rounded-full bg-zinc-600" />
            Disabled
          </span>
        )
      default:
        return (
          <span className="flex items-center gap-1.5 text-micro text-zinc-400">
            <span className="size-2 rounded-full bg-zinc-500" />
            Disconnected
          </span>
        )
    }
  }

  return (
    <>
      <Section
        title="Model Context Protocol (MCP)"
        hint="Connect external stdio MCP servers to supply custom tools, databases, and capabilities into Pentagon's autonomous reasoning loop."
      >
        {notice && (
          <div className="mb-3 flex items-center justify-between rounded-lg border border-emerald-400/20 bg-emerald-400/[0.05] px-3 py-2 text-small text-emerald-200">
            <span>{notice}</span>
            <button type="button" onClick={() => setNotice('')} aria-label="Dismiss notice">
              <X size={13} />
            </button>
          </div>
        )}

        {error && (
          <div className="mb-3 flex items-start justify-between rounded-lg border border-rose-400/20 bg-rose-400/[0.06] px-3 py-2 text-small text-rose-200">
            <span>{error}</span>
            <button type="button" onClick={() => setError('')} aria-label="Dismiss error">
              <X size={13} />
            </button>
          </div>
        )}

        {problems.length > 0 && (
          <div className="mb-3 rounded-lg border border-amber-400/20 bg-amber-400/[0.05] p-3 text-micro text-amber-200/90">
            <div className="flex items-center gap-1.5 font-semibold text-amber-300">
              <AlertCircle size={13} />
              <span>Bridge Notices</span>
            </div>
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-amber-200/80">
              {problems.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Top Control Bar */}
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <div className="text-small font-medium text-zinc-200">
            Active Servers ({servers ? servers.length : 0})
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleReloadAll}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-lg border border-white/[0.09] bg-white/[0.03] px-2.5 py-1.5 text-micro font-medium text-zinc-300 transition hover:bg-white/[0.07] hover:text-white disabled:opacity-50"
              title="Reload and reconnect all MCP servers"
            >
              <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
              <span>Reload</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setFormName('')
                setFormCommand('')
                setFormTier('write')
                setFormEnv([])
                setDraftTestResult(null)
                setShowAddForm(true)
              }}
              className="flex items-center gap-1.5 rounded-lg bg-emerald-400 px-3 py-1.5 text-micro font-semibold text-black transition hover:bg-emerald-300"
            >
              <Plus size={13} />
              <span>Add MCP Server</span>
            </button>
          </div>
        </div>

        {/* Server List */}
        {loading && !servers ? (
          <div className="flex items-center gap-2 py-6 text-small text-zinc-500">
            <LoaderCircle size={14} className="animate-spin text-emerald-400" />
            <span>Loading MCP server status…</span>
          </div>
        ) : servers && servers.length === 0 ? (
          <div className="rounded-xl border border-dashed border-white/[0.1] bg-white/[0.015] p-6 text-center">
            <Server size={28} className="mx-auto mb-2 text-zinc-600" />
            <p className="text-small font-medium text-zinc-300">No MCP servers connected yet</p>
            <p className="mt-1 text-micro text-zinc-500">
              Select one of the quick presets below or add a custom stdio server command.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {servers?.map((server) => {
              const isExpanded = expandedServer === server.name
              const isTesting = testingServer === server.name
              const lastTest = testResults[server.name]

              return (
                <div
                  key={server.name}
                  className="rounded-xl border border-white/[0.08] bg-white/[0.025] transition hover:border-white/[0.14]"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3 p-3.5 sm:px-4">
                    <div className="flex min-w-0 flex-1 items-center gap-3">
                      <button
                        type="button"
                        onClick={() => setExpandedServer(isExpanded ? null : server.name)}
                        className="text-zinc-500 transition hover:text-zinc-200"
                        title={isExpanded ? 'Collapse tools' : 'Inspect tools'}
                      >
                        {isExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                      </button>

                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-small-lg font-semibold text-zinc-100">
                            {server.name}
                          </span>
                          {tierBadge(server.tier)}
                          <span className="rounded border border-white/[0.08] px-1.5 py-0.5 font-mono text-[10px] text-zinc-400">
                            {server.source === 'database' ? 'custom' : 'env'}
                          </span>
                          {statusDot(server.status)}
                        </div>

                        <div className="mt-1.5 flex flex-wrap items-center gap-2">
                          <code className="max-w-full sm:max-w-xs md:max-w-md truncate rounded bg-white/[0.04] px-2 py-0.5 font-mono text-[11px] text-zinc-400">
                            {server.command.join(' ')}
                          </code>
                          <span className="text-micro text-zinc-500">
                            {server.tools_count} {server.tools_count === 1 ? 'tool' : 'tools'}
                          </span>
                          {lastTest && (
                            <span
                              className={`rounded px-1.5 py-0.5 text-[10px] font-mono ${
                                lastTest.success ? 'bg-emerald-400/10 text-emerald-300' : 'bg-rose-400/10 text-rose-300'
                              }`}
                            >
                              {lastTest.success ? `${lastTest.latency_ms}ms` : 'failed'}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="flex shrink-0 items-center gap-2">
                      <button
                        type="button"
                        onClick={() => void handleTestExisting(server.name)}
                        disabled={isTesting}
                        className="flex items-center gap-1 rounded-lg border border-white/[0.09] bg-white/[0.03] px-2.5 py-1 text-micro font-medium text-zinc-300 transition hover:bg-white/[0.08] hover:text-white disabled:opacity-50"
                        title="Test server handshake and list tools"
                      >
                        <Play size={10} className={isTesting ? 'animate-spin' : ''} />
                        <span>{isTesting ? 'Testing…' : 'Test'}</span>
                      </button>

                      {server.source === 'database' && (
                        <button
                          type="button"
                          onClick={() => void handleDelete(server.name)}
                          className="grid size-7 place-items-center rounded-lg text-zinc-500 transition hover:bg-rose-400/10 hover:text-rose-300"
                          title="Delete server"
                        >
                          <Trash2 size={13} />
                        </button>
                      )}

                      <button
                        type="button"
                        role="switch"
                        aria-checked={server.enabled}
                        aria-label={`Toggle ${server.name}`}
                        onClick={() => void handleToggle(server, !server.enabled)}
                        className="flex items-center gap-1.5 text-micro text-zinc-500"
                      >
                        <span className="flex h-5 w-9 items-center rounded-full p-0.5 transition">
                          <span
                            className={`size-4 rounded-full transition-transform ${
                              server.enabled ? 'translate-x-4 bg-emerald-400' : 'bg-white/[0.2]'
                            }`}
                          />
                        </span>
                      </button>
                    </div>
                  </div>

                  {/* Expanded Tools Drawer */}
                  {isExpanded && (
                    <div className="border-t border-white/[0.06] bg-black/40 p-3.5">
                      {server.last_error && (
                        <div className="mb-3 rounded-lg border border-rose-400/20 bg-rose-400/[0.05] p-2.5 text-micro text-rose-200">
                          <span className="font-semibold">Last Error: </span>
                          <span>{server.last_error}</span>
                        </div>
                      )}

                      <div className="mb-2 text-micro font-semibold uppercase tracking-[.15em] text-zinc-500">
                        Provided Tools ({server.tools.length})
                      </div>

                      {server.tools.length === 0 ? (
                        <p className="text-micro text-zinc-500">
                          No tools registered. Click &quot;Test&quot; to probe the server.
                        </p>
                      ) : (
                        <div className="grid gap-2 sm:grid-cols-2">
                          {server.tools.map((tool: McpToolInfo) => (
                            <div
                              key={tool.name}
                              className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-2.5"
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span className="font-mono text-micro font-semibold text-emerald-300">
                                  {tool.name}
                                </span>
                                {tierBadge(tool.tier)}
                              </div>
                              <p className="mt-1 line-clamp-2 text-caption text-zinc-400">
                                {tool.description}
                              </p>
                              {tool.remote_name && tool.remote_name !== tool.name && (
                                <span className="mt-1 block font-mono text-[10px] text-zinc-600">
                                  Remote: {tool.remote_name}
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </Section>

      {/* Quick Install Presets */}
      <Section
        title="Quick Install Presets"
        hint="One-click templates to extend Pentagon's tool library."
      >
        <div className="grid gap-2.5 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
          {presets.map((preset) => {
            const Icon = PRESET_ICONS[preset.id] || Server
            const isInstalled = servers?.some((s) => s.name === preset.name)

            return (
              <button
                key={preset.id}
                type="button"
                onClick={() => applyPreset(preset)}
                className="group flex flex-col items-start rounded-xl border border-white/[0.07] bg-white/[0.02] p-3 text-left transition hover:border-emerald-400/30 hover:bg-emerald-400/[0.02]"
              >
                <div className="mb-2 flex w-full items-center justify-between">
                  <div className="grid size-7 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-emerald-400 group-hover:border-emerald-400/30 group-hover:bg-emerald-400/10">
                    <Icon size={14} />
                  </div>
                  {isInstalled ? (
                    <span className="flex items-center gap-1 text-[10px] font-medium text-emerald-400">
                      <Check size={10} /> Installed
                    </span>
                  ) : (
                    <span className="rounded border border-white/[0.08] px-1.5 py-0.5 font-mono text-[10px] text-zinc-500">
                      {preset.category}
                    </span>
                  )}
                </div>
                <div className="text-small font-semibold text-zinc-200 group-hover:text-white">
                  {preset.title}
                </div>
                <div className="mt-2 flex w-full items-center gap-1.5 rounded bg-white/[0.03] px-2 py-1 text-[11px] font-mono text-zinc-400">
                  <Terminal size={11} className="shrink-0 text-emerald-400" />
                  <span className="truncate">{preset.command.slice(0, 2).join(' ')}</span>
                </div>
              </button>
            )
          })}
        </div>
      </Section>

      {/* Add / Edit Server Modal */}
      {showAddForm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-3 sm:p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-label="Add MCP Server"
        >
          <div className="panel-enter w-full max-w-[620px] max-h-[90vh] overflow-y-auto rounded-2xl border border-white/[0.12] bg-[var(--surface-panel)] p-4 sm:p-6 shadow-2xl">
            <div className="mb-4 flex items-center justify-between border-b border-white/[0.07] pb-3">
              <div className="flex items-center gap-2">
                <Zap size={16} className="text-emerald-400" />
                <h3 className="text-body-lg font-semibold text-zinc-100">Add MCP Server</h3>
              </div>
              <button
                type="button"
                onClick={() => setShowAddForm(false)}
                className="rounded-lg p-1 text-zinc-500 hover:bg-white/[0.06] hover:text-zinc-200"
              >
                <X size={15} />
              </button>
            </div>

            <form onSubmit={handleSaveForm} className="space-y-4">
              <div>
                <label className="mb-1 block text-micro font-medium uppercase tracking-[.1em] text-zinc-400">
                  Server Name
                </label>
                <input
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  placeholder="e.g. sqlite_db, github, filesystem"
                  className={inputClass}
                  required
                />
              </div>

              <div>
                <label className="mb-1 block text-micro font-medium uppercase tracking-[.1em] text-zinc-400">
                  Executable Command
                </label>
                <input
                  value={formCommand}
                  onChange={(e) => setFormCommand(e.target.value)}
                  placeholder="e.g. uvx mcp-server-sqlite --db-path ./pentagon.db"
                  className={inputClass}
                  required
                />
                <p className="mt-1 text-micro text-zinc-500">
                  Supports <code>uvx</code>, <code>npx -y</code>, or direct binary executables over stdio JSON-RPC.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-micro font-medium uppercase tracking-[.1em] text-zinc-400">
                    Default Approval Tier
                  </label>
                  <select
                    value={formTier}
                    onChange={(e) => setFormTier(e.target.value)}
                    className={selectClass}
                  >
                    <option value="write">Write (Approval gated at Balanced)</option>
                    <option value="read">Read (Auto-run at Balanced)</option>
                    <option value="destructive">Destructive (Always asks user)</option>
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-micro font-medium uppercase tracking-[.1em] text-zinc-400">
                    Environment Variables
                  </label>
                  <button
                    type="button"
                    onClick={() => setFormEnv([...formEnv, { key: '', value: '' }])}
                    className="flex h-9 w-full items-center justify-center gap-1.5 rounded-lg border border-white/[0.09] bg-white/[0.03] text-micro font-medium text-zinc-300 hover:bg-white/[0.06]"
                  >
                    <Plus size={13} />
                    <span>Add Variable</span>
                  </button>
                </div>
              </div>

              {formEnv.length > 0 && (
                <div className="space-y-2 rounded-xl border border-white/[0.06] bg-black/40 p-3">
                  <div className="text-micro font-semibold text-zinc-400">Environment Variables</div>
                  {formEnv.map((entry, index) => (
                    <div key={index} className="flex items-center gap-2">
                      <input
                        value={entry.key}
                        onChange={(e) => {
                          const updated = [...formEnv]
                          updated[index].key = e.target.value
                          setFormEnv(updated)
                        }}
                        placeholder="KEY (e.g. GITHUB_TOKEN)"
                        className="h-8 flex-1 rounded border border-white/[0.08] bg-white/[0.02] px-2.5 font-mono text-micro text-zinc-200 outline-none focus:border-white/20"
                      />
                      <input
                        value={entry.value}
                        type="password"
                        onChange={(e) => {
                          const updated = [...formEnv]
                          updated[index].value = e.target.value
                          setFormEnv(updated)
                        }}
                        placeholder="VALUE"
                        className="h-8 flex-1 rounded border border-white/[0.08] bg-white/[0.02] px-2.5 font-mono text-micro text-zinc-200 outline-none focus:border-white/20"
                      />
                      <button
                        type="button"
                        onClick={() => setFormEnv(formEnv.filter((_, i) => i !== index))}
                        className="grid size-8 place-items-center rounded text-zinc-500 hover:text-rose-400"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {draftTestResult && (
                <div
                  className={`rounded-xl border p-3 text-micro ${
                    draftTestResult.success
                      ? 'border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-200'
                      : 'border-rose-400/20 bg-rose-400/[0.05] text-rose-200'
                  }`}
                >
                  {draftTestResult.success ? (
                    <div>
                      <span className="font-semibold text-emerald-300">Handshake Successful! </span>
                      Discovered {draftTestResult.tools_count} tool(s) in {draftTestResult.latency_ms}ms.
                    </div>
                  ) : (
                    <div>
                      <span className="font-semibold text-rose-300">Test Failed: </span>
                      {draftTestResult.error}
                    </div>
                  )}
                </div>
              )}

              <div className="flex items-center justify-end gap-2 border-t border-white/[0.07] pt-4">
                <button
                  type="button"
                  onClick={handleTestDraft}
                  disabled={testingDraft || !formCommand.trim()}
                  className="flex h-9 items-center gap-1.5 rounded-lg border border-white/[0.1] bg-white/[0.04] px-3 text-small font-medium text-zinc-300 hover:bg-white/[0.08] disabled:opacity-50"
                >
                  <Play size={12} className={testingDraft ? 'animate-spin' : ''} />
                  <span>{testingDraft ? 'Probing…' : 'Test Handshake'}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setShowAddForm(false)}
                  className="h-9 rounded-lg border border-white/[0.08] px-3.5 text-small text-zinc-400 hover:bg-white/[0.05]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingServer}
                  className="flex h-9 items-center gap-1.5 rounded-lg bg-emerald-400 px-4 text-small font-semibold text-black hover:bg-emerald-300 disabled:opacity-50"
                >
                  <Check size={14} />
                  <span>{savingServer ? 'Connecting…' : 'Save & Connect'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  )
}
