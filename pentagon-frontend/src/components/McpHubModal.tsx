import { useState, useMemo } from 'react'
import {
  Power,
  RefreshCw,
  Search,
  Server,
  Wrench,
  X,
} from 'lucide-react'
import { DEFAULT_MCP_SERVERS, type McpHubServer } from '../lib/mcpHubData'

interface McpHubModalProps {
  isOpen: boolean
  onClose: () => void
}

export function McpHubModal({ isOpen, onClose }: McpHubModalProps) {
  const [servers, setServers] = useState<McpHubServer[]>(DEFAULT_MCP_SERVERS)
  const [selectedServerId, setSelectedServerId] = useState<string>(DEFAULT_MCP_SERVERS[0].id)
  const [searchQuery, setSearchQuery] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  const selectedServer = useMemo(
    () => servers.find((s) => s.id === selectedServerId) || servers[0],
    [servers, selectedServerId]
  )

  const filteredTools = useMemo(() => {
    if (!selectedServer) return []
    if (!searchQuery.trim()) return selectedServer.tools
    const q = searchQuery.toLowerCase()
    return selectedServer.tools.filter(
      (t) => t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q)
    )
  }, [selectedServer, searchQuery])

  const totalTools = useMemo(
    () => servers.reduce((acc, s) => acc + (s.status === 'connected' ? s.tools.length : 0), 0),
    [servers]
  )

  const handleToggleServer = (id: string) => {
    setServers((prev) =>
      prev.map((s) => {
        if (s.id !== id) return s
        const nextStatus = s.status === 'connected' ? 'idle' : 'connected'
        return { ...s, status: nextStatus }
      })
    )
  }

  const handleRefresh = () => {
    setRefreshing(true)
    setTimeout(() => setRefreshing(false), 800)
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative flex h-[86vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-white/[0.1] bg-[#0c0c0f] shadow-[0_25px_80px_rgba(0,0,0,0.8)]">
        {/* Header */}
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-white/[0.08] bg-[#121216] px-5">
          <div className="flex items-center gap-2.5">
            <div className="grid size-8 place-items-center rounded-lg border border-emerald-500/25 bg-emerald-500/10 text-emerald-400">
              <Server size={16} />
            </div>
            <div>
              <h2 className="text-small font-semibold text-zinc-100 flex items-center gap-2">
                Model Context Protocol (MCP) Hub
                <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-mono text-emerald-300">
                  {totalTools} Tools Online
                </span>
              </h2>
              <p className="text-[11px] text-zinc-400">
                Connected external tool servers providing Claude with live tool calling capabilities.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleRefresh}
              title="Refresh MCP Connections"
              className="grid size-8 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-zinc-400 transition hover:bg-white/[0.08] hover:text-white"
            >
              <RefreshCw size={13} className={refreshing ? 'animate-spin text-emerald-400' : ''} />
            </button>
            <button
              type="button"
              onClick={onClose}
              className="grid size-8 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-zinc-400 transition hover:bg-white/[0.08] hover:text-white"
            >
              <X size={15} />
            </button>
          </div>
        </header>

        {/* Content split */}
        <div className="flex min-h-0 flex-1 flex-col md:flex-row">
          {/* Server List */}
          <div className="w-full md:w-80 lg:w-96 shrink-0 overflow-y-auto border-r border-white/[0.08] bg-[#0c0c0f] p-3 space-y-2">
            <div className="text-[10px] uppercase font-mono tracking-wider text-zinc-500 px-2 py-1">
              Active Servers ({servers.length})
            </div>
            {servers.map((s) => {
              const isSelected = selectedServer?.id === s.id
              const isConnected = s.status === 'connected'
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setSelectedServerId(s.id)}
                  className={`w-full rounded-xl border p-3 text-left transition-all ${
                    isSelected
                      ? 'border-emerald-500/40 bg-emerald-500/[0.08] shadow-sm'
                      : 'border-white/[0.06] bg-white/[0.02] hover:border-white/[0.12] hover:bg-white/[0.04]'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-micro font-semibold text-zinc-200 truncate">{s.name}</span>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-mono ${
                        isConnected
                          ? 'bg-emerald-500/15 text-emerald-300'
                          : 'bg-zinc-800 text-zinc-400'
                      }`}
                    >
                      <span
                        className={`size-1.5 rounded-full ${
                          isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-500'
                        }`}
                      />
                      {isConnected ? `${s.latencyMs}ms` : 'Idle'}
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-[11px] text-zinc-400">{s.description}</p>
                  <div className="mt-2 flex items-center justify-between text-[10px] text-zinc-500 font-mono">
                    <span>{s.tools.length} exposed tools</span>
                    <span className="uppercase text-zinc-400">{s.transport}</span>
                  </div>
                </button>
              )
            })}
          </div>

          {/* Server Tool Inspector */}
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-[#0a0a0d] p-5">
            {selectedServer && (
              <div className="space-y-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h3 className="text-base font-semibold text-zinc-100 flex items-center gap-2">
                      {selectedServer.name}
                      <span className="text-caption font-mono rounded bg-white/[0.06] px-2 py-0.5 text-zinc-400">
                        {selectedServer.transport}
                      </span>
                    </h3>
                    <p className="text-caption text-zinc-400 mt-1">{selectedServer.description}</p>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleToggleServer(selectedServer.id)}
                    className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-micro font-medium transition ${
                      selectedServer.status === 'connected'
                        ? 'border border-rose-500/30 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20'
                        : 'border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20'
                    }`}
                  >
                    <Power size={12} />
                    <span>
                      {selectedServer.status === 'connected' ? 'Disconnect' : 'Connect'}
                    </span>
                  </button>
                </div>

                {/* Tool Directory for Selected Server */}
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-micro font-semibold uppercase tracking-wider text-emerald-400 flex items-center gap-1.5">
                      <Wrench size={13} />
                      Exposed MCP Tools ({filteredTools.length})
                    </h4>
                    <div className="relative">
                      <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-500" />
                      <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Filter tools..."
                        className="rounded-lg border border-white/[0.08] bg-black/50 pl-7 pr-2.5 py-1 text-[11px] text-zinc-200 placeholder:text-zinc-500 outline-none focus:border-emerald-500/40"
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    {filteredTools.map((tool) => (
                      <div
                        key={tool.name}
                        className="rounded-xl border border-white/[0.08] bg-black/40 p-3.5 space-y-1.5"
                      >
                        <div className="flex items-center justify-between">
                          <code className="text-micro font-mono font-semibold text-emerald-300">
                            {tool.name}
                          </code>
                          <span className="text-[10px] font-mono text-zinc-500">MCP Callable</span>
                        </div>
                        <p className="text-[11px] text-zinc-300 leading-relaxed">
                          {tool.description}
                        </p>
                        {tool.parameters && tool.parameters.length > 0 && (
                          <div className="flex flex-wrap items-center gap-1 pt-1">
                            <span className="text-[10px] text-zinc-500 font-mono">args:</span>
                            {tool.parameters.map((param) => (
                              <span
                                key={param}
                                className="rounded bg-white/[0.05] px-1.5 py-0.5 text-[10px] font-mono text-zinc-400"
                              >
                                {param}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <footer className="flex h-12 shrink-0 items-center justify-between border-t border-white/[0.08] bg-[#121216] px-5 text-caption text-zinc-400 font-mono">
          <span>Protocol: JSON-RPC 2.0 / Model Context Protocol Spec 2024-11</span>
          <span className="text-emerald-400">All systems operational</span>
        </footer>
      </div>
    </div>
  )
}
