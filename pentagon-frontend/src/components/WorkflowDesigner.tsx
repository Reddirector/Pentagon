import { useEffect, useState } from 'react'
import {
  AlertCircle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Clock,
  Download,
  Eye,
  FileCheck,
  FileSpreadsheet,
  FileText,
  Globe,
  ImageIcon,
  LayoutTemplate,
  Loader2,
  Play,
  Plus,
  Save,
  Settings2,
  Sparkles,
  Trash2,
  Workflow as WorkflowIcon,
  X,
  Zap,
} from 'lucide-react'
import {
  createWorkflow,
  deleteWorkflow,
  downloadGeneratedFile,
  fetchWorkflowRun,
  fetchWorkflows,
  runWorkflow,
  updateWorkflow,
} from '../api'
import type { Workflow, WorkflowDeliverable, WorkflowNode, WorkflowNodeType, WorkflowRun, WorkflowStepResult } from '../types'

const NODE_TYPES: Array<{
  type: WorkflowNodeType
  label: string
  description: string
  icon: typeof Zap
  color: string
}> = [
  {
    type: 'trigger',
    label: 'Trigger & Inputs',
    description: 'Initial parameters and user inputs to kick off the pipeline',
    icon: Zap,
    color: 'emerald',
  },
  {
    type: 'web_search',
    label: 'Web Intelligence',
    description: 'Searches the live web and scrapes grounded source content',
    icon: Globe,
    color: 'sky',
  },
  {
    type: 'llm_transform',
    label: 'LLM Reasoning & Synthesis',
    description: 'Deep multi-step reasoning, outline drafting, and analysis',
    icon: Sparkles,
    color: 'purple',
  },
  {
    type: 'image_generation',
    label: 'Visual & Infographic Gen',
    description: 'FLUX.1 diffusion and vector architecture diagrams',
    icon: ImageIcon,
    color: 'amber',
  },
  {
    type: 'document_generation',
    label: 'Document Deliverable',
    description: 'Compiles Word (.docx), PDF, Excel (.xlsx), Slides (.pptx) or HTML',
    icon: FileText,
    color: 'rose',
  },
]

export function WorkflowDesigner({
  userId,
  onClose,
  initialWorkflowId,
}: {
  userId: string
  onClose: () => void
  initialWorkflowId?: string
}) {
  const [loading, setLoading] = useState(true)
  const [templates, setTemplates] = useState<Workflow[]>([])
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [activeWorkflow, setActiveWorkflow] = useState<Workflow | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [showGallery, setShowGallery] = useState(false)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  // Execution modal state
  const [runModalOpen, setRunModalOpen] = useState(false)
  const [runInputs, setRunInputs] = useState<Record<string, any>>({})
  const [activeRun, setActiveRun] = useState<WorkflowRun | null>(null)
  const [executing, setExecuting] = useState(false)

  // Deliverable preview modal state
  const [previewFile, setPreviewFile] = useState<WorkflowDeliverable | null>(null)

  // Load workflows & templates
  async function reloadWorkflows(preferredId?: string) {
    try {
      setLoading(true)
      const data = await fetchWorkflows(userId)
      setTemplates(data.templates || [])
      setWorkflows(data.workflows || [])

      const all = [...(data.templates || []), ...(data.workflows || [])]
      const toSelect = preferredId
        ? all.find((w) => w.id === preferredId)
        : activeWorkflow
          ? all.find((w) => w.id === activeWorkflow.id)
          : all[0]

      if (toSelect) {
        setActiveWorkflow(JSON.parse(JSON.stringify(toSelect)))
        if (toSelect.nodes && toSelect.nodes.length > 0) {
          setSelectedNodeId(toSelect.nodes[0].id)
        }
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load workflows.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    const timer = window.setTimeout(async () => {
      try {
        setLoading(true)
        const data = await fetchWorkflows(userId)
        if (cancelled) return
        setTemplates(data.templates || [])
        setWorkflows(data.workflows || [])

        const all = [...(data.templates || []), ...(data.workflows || [])]
        const toSelect = initialWorkflowId
          ? all.find((w) => w.id === initialWorkflowId)
          : all[0]

        if (toSelect) {
          setActiveWorkflow(JSON.parse(JSON.stringify(toSelect)))
          if (toSelect.nodes && toSelect.nodes.length > 0) {
            setSelectedNodeId(toSelect.nodes[0].id)
          }
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message || 'Failed to load workflows.')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }, 0)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [userId, initialWorkflowId])

  // Poll active run
  const activeRunId = activeRun?.id
  const activeRunStatus = activeRun?.status

  useEffect(() => {
    if (!activeRunId || activeRunStatus === 'success' || activeRunStatus === 'failed' || activeRunStatus === 'cancelled') {
      return
    }

    const timer = window.setInterval(async () => {
      try {
        const updated = await fetchWorkflowRun(activeRunId, userId)
        setActiveRun(updated)
        if (updated.status === 'success') {
          setExecuting(false)
          setNotice('Workflow completed successfully!')
        } else if (updated.status === 'failed') {
          setExecuting(false)
          setError(updated.error_message || 'Workflow execution failed.')
        }
      } catch (err) {
        console.error('Run polling error', err)
      }
    }, 1200)

    return () => clearInterval(timer)
  }, [activeRunId, activeRunStatus, userId])

  // Select a template
  function loadTemplate(tpl: Workflow) {
    const cloned = JSON.parse(JSON.stringify(tpl))
    setActiveWorkflow(cloned)
    if (cloned.nodes && cloned.nodes.length > 0) {
      setSelectedNodeId(cloned.nodes[0].id)
    }
    setShowGallery(false)
    setNotice(`Loaded template "${tpl.name}". You can now customize or execute it.`)
  }

  // Create new blank workflow
  function handleNewWorkflow() {
    const newWf: Workflow = {
      id: `custom-${crypto.randomUUID()}`,
      name: 'Untitled Workflow Pipeline',
      description: 'Custom multi-step AI orchestration pipeline',
      icon: 'zap',
      category: 'general',
      is_template: false,
      nodes: [
        {
          id: 'step_1_trigger',
          type: 'trigger',
          title: 'Initial Parameters',
          description: 'Define input variables for the pipeline',
          config: { topic: 'New Project Initiative' },
          position: { x: 80, y: 100 },
        },
        {
          id: 'step_2_synthesis',
          type: 'llm_transform',
          title: 'Executive Analysis',
          description: 'Synthesize research and recommendations',
          config: {
            prompt: 'Produce an executive strategic overview regarding: {{inputs.topic}}',
            model: 'meta/llama-3.3-70b-instruct',
          },
          position: { x: 360, y: 100 },
        },
        {
          id: 'step_3_export',
          type: 'document_generation',
          title: 'Compile Deliverable',
          description: 'Export as professional PDF or Word document',
          config: {
            format: 'docx',
            title: '{{inputs.topic}} Deliverable',
            content: '{{steps.step_2_synthesis.output}}',
          },
          position: { x: 640, y: 100 },
        },
      ],
      edges: [
        { source: 'step_1_trigger', target: 'step_2_synthesis' },
        { source: 'step_2_synthesis', target: 'step_3_export' },
      ],
    }
    setActiveWorkflow(newWf)
    setSelectedNodeId('step_1_trigger')
    setShowGallery(false)
  }

  // Save changes to backend
  async function handleSaveWorkflow() {
    if (!activeWorkflow) return
    try {
      setSaving(true)
      setError('')
      const isExistingUserWf = workflows.some((w) => w.id === activeWorkflow.id)

      if (isExistingUserWf) {
        const updated = await updateWorkflow(activeWorkflow.id, {
          user_id: userId,
          name: activeWorkflow.name,
          description: activeWorkflow.description,
          icon: activeWorkflow.icon,
          category: activeWorkflow.category,
          nodes: activeWorkflow.nodes,
          edges: activeWorkflow.edges,
        })
        setActiveWorkflow(updated)
        setNotice('Workflow saved successfully!')
      } else {
        const created = await createWorkflow({
          user_id: userId,
          name: activeWorkflow.name,
          description: activeWorkflow.description,
          icon: activeWorkflow.icon,
          category: activeWorkflow.category,
          nodes: activeWorkflow.nodes,
          edges: activeWorkflow.edges,
        })
        setActiveWorkflow(created)
        setWorkflows((prev) => [created, ...prev])
        setNotice('Workflow created and saved successfully!')
      }
      await reloadWorkflows(activeWorkflow.id)
    } catch (err: any) {
      setError(err?.message || 'Could not save workflow.')
    } finally {
      setSaving(false)
    }
  }

  // Delete current workflow
  async function handleDeleteWorkflow() {
    if (!activeWorkflow) return
    if (activeWorkflow.is_template) {
      setError('Built-in executive templates cannot be deleted.')
      return
    }
    if (!window.confirm(`Delete workflow "${activeWorkflow.name}"? This action cannot be undone.`)) {
      return
    }

    try {
      await deleteWorkflow(activeWorkflow.id, userId)
      setNotice(`Workflow "${activeWorkflow.name}" deleted.`)
      await reloadWorkflows()
    } catch (err: any) {
      setError(err?.message || 'Could not delete workflow.')
    }
  }

  // Node editing handlers
  function updateNode(nodeId: string, updates: Partial<WorkflowNode>) {
    if (!activeWorkflow) return
    const updatedNodes = activeWorkflow.nodes.map((n) => (n.id === nodeId ? { ...n, ...updates } : n))
    setActiveWorkflow({ ...activeWorkflow, nodes: updatedNodes })
  }

  function updateNodeConfig(nodeId: string, configKey: string, value: any) {
    if (!activeWorkflow) return
    const updatedNodes = activeWorkflow.nodes.map((n) => {
      if (n.id === nodeId) {
        return {
          ...n,
          config: {
            ...n.config,
            [configKey]: value,
          },
        }
      }
      return n
    })
    setActiveWorkflow({ ...activeWorkflow, nodes: updatedNodes })
  }

  function addNode(type: WorkflowNodeType) {
    if (!activeWorkflow) return
    const count = activeWorkflow.nodes.length + 1
    const id = `step_${count}_${type.replace(/[^a-z0-9]/g, '_')}`
    const meta = NODE_TYPES.find((t) => t.type === type) || NODE_TYPES[0]

    let defaultConfig: Record<string, any> = {}
    if (type === 'trigger') {
      defaultConfig = { topic: 'Autonomous Intelligence' }
    } else if (type === 'web_search') {
      defaultConfig = { query: '{{inputs.topic}} market dynamics 2026', max_sources: 4 }
    } else if (type === 'llm_transform') {
      defaultConfig = {
        prompt: 'Synthesize insights for: {{inputs.topic}}',
        model: 'meta/llama-3.3-70b-instruct',
      }
    } else if (type === 'image_generation') {
      defaultConfig = {
        title: 'Infographic Graphic',
        prompt: '{{inputs.topic}} clean technical architecture diagram, corporate infographic style',
        style: 'diagram',
        aspect_ratio: '16:9',
      }
    } else if (type === 'document_generation') {
      defaultConfig = {
        format: 'pdf',
        title: 'Executive Deliverable',
        content: '# Executive Report\n\nContent compiled by Pentagon Engine.',
      }
    }

    const newNode: WorkflowNode = {
      id,
      type,
      title: `${meta.label} Step`,
      description: meta.description,
      config: defaultConfig,
    }

    const lastNode = activeWorkflow.nodes[activeWorkflow.nodes.length - 1]
    const updatedEdges = [...activeWorkflow.edges]
    if (lastNode) {
      updatedEdges.push({ source: lastNode.id, target: id })
    }

    setActiveWorkflow({
      ...activeWorkflow,
      nodes: [...activeWorkflow.nodes, newNode],
      edges: updatedEdges,
    })
    setSelectedNodeId(id)
  }

  function removeNode(nodeId: string) {
    if (!activeWorkflow) return
    const updatedNodes = activeWorkflow.nodes.filter((n) => n.id !== nodeId)
    const updatedEdges = activeWorkflow.edges.filter((e) => e.source !== nodeId && e.target !== nodeId)
    setActiveWorkflow({
      ...activeWorkflow,
      nodes: updatedNodes,
      edges: updatedEdges,
    })
    if (selectedNodeId === nodeId) {
      setSelectedNodeId(updatedNodes[0]?.id || null)
    }
  }

  // Launch Run Modal
  function handleOpenRunModal() {
    if (!activeWorkflow) return
    const triggerNode = activeWorkflow.nodes.find((n) => n.type === 'trigger')
    const initialInputs = triggerNode?.config ? { ...triggerNode.config } : { topic: 'AI Enterprise Architecture' }
    setRunInputs(initialInputs)
    setRunModalOpen(true)
  }

  // Execute Workflow Run
  async function handleStartRun() {
    if (!activeWorkflow) return
    try {
      setExecuting(true)
      setError('')
      const run = await runWorkflow(activeWorkflow.id, userId, runInputs)
      setActiveRun(run)
    } catch (err: any) {
      setExecuting(false)
      setError(err?.message || 'Could not start workflow execution.')
    }
  }

  const selectedNode = activeWorkflow?.nodes.find((n) => n.id === selectedNodeId)

  if (loading && !activeWorkflow) {
    return (
      <div className="flex h-full min-h-0 flex-1 items-center justify-center bg-[#090a0f] text-xs text-zinc-500">
        <Loader2 size={18} className="mr-2 animate-spin text-emerald-400" />
        <span>Loading Pentagon Workflow Studio...</span>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col bg-[#090a0f] text-zinc-100">
      {/* Studio Header Bar */}
      <header className="flex h-16 shrink-0 items-center justify-between border-b border-white/[0.08] bg-black/60 px-4 backdrop-blur-xl sm:px-6">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-xl border border-emerald-400/30 bg-emerald-400/10 text-emerald-400 shadow-sm">
            <WorkflowIcon size={18} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-semibold tracking-wide text-white">
                {activeWorkflow?.name || 'Workflow Orchestration Studio'}
              </h1>
              {activeWorkflow?.is_template && (
                <span className="rounded-full border border-sky-400/30 bg-sky-400/10 px-2 py-0.5 text-[10px] font-medium text-sky-300">
                  Built-in Template
                </span>
              )}
            </div>
            <p className="hidden text-xs text-zinc-400 sm:block">
              {activeWorkflow?.description || 'Build, connect, and execute multi-step DAG agent pipelines'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Gallery button */}
          <button
            type="button"
            onClick={() => setShowGallery(!showGallery)}
            className={`flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-medium transition ${
              showGallery
                ? 'border-emerald-400/40 bg-emerald-400/15 text-emerald-300'
                : 'border-white/[0.08] bg-white/[0.04] text-zinc-300 hover:bg-white/[0.08] hover:text-white'
            }`}
          >
            <LayoutTemplate size={14} />
            <span>Templates</span>
          </button>

          {/* New Workflow button */}
          <button
            type="button"
            onClick={handleNewWorkflow}
            className="flex items-center gap-1.5 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-zinc-300 transition hover:bg-white/[0.08] hover:text-white"
          >
            <Plus size={14} />
            <span className="hidden sm:inline">New Pipeline</span>
          </button>

          {/* Save Workflow button */}
          <button
            type="button"
            onClick={handleSaveWorkflow}
            disabled={saving || !activeWorkflow}
            className="flex items-center gap-1.5 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-zinc-300 transition hover:bg-white/[0.08] hover:text-white disabled:opacity-50"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            <span className="hidden sm:inline">Save</span>
          </button>

          {/* Delete custom workflow */}
          {activeWorkflow && !activeWorkflow.is_template && (
            <button
              type="button"
              onClick={handleDeleteWorkflow}
              aria-label="Delete this workflow"
              title="Delete this workflow"
              className="grid size-8 place-items-center rounded-xl border border-white/[0.08] text-zinc-400 transition hover:border-rose-400/30 hover:bg-rose-500/10 hover:text-rose-300"
            >
              <Trash2 size={14} />
            </button>
          )}

          {/* Run button */}
          <button
            type="button"
            onClick={handleOpenRunModal}
            disabled={!activeWorkflow || !activeWorkflow.nodes.length}
            className="flex items-center gap-1.5 rounded-xl border border-emerald-400/40 bg-emerald-500/20 px-3.5 py-1.5 text-xs font-semibold text-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.15)] transition hover:bg-emerald-500/30 active:scale-95 disabled:opacity-50"
          >
            <Play size={14} className="fill-emerald-400" />
            <span>Run Pipeline</span>
          </button>

          {/* Close Studio */}
          <button
            type="button"
            onClick={onClose}
            aria-label="Back to Chat"
            className="grid size-8 place-items-center rounded-xl border border-white/[0.08] text-zinc-400 transition hover:bg-white/[0.08] hover:text-white"
          >
            <X size={16} />
          </button>
        </div>
      </header>

      {/* Notifications / Alerts banner */}
      {notice && (
        <div className="flex items-center justify-between border-b border-emerald-500/20 bg-emerald-500/10 px-4 py-2 text-xs text-emerald-300">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={14} />
            <span>{notice}</span>
          </div>
          <button onClick={() => setNotice('')} className="text-emerald-400 hover:text-emerald-200">
            <X size={13} />
          </button>
        </div>
      )}
      {error && (
        <div className="flex items-center justify-between border-b border-rose-500/20 bg-rose-500/10 px-4 py-2 text-xs text-rose-300">
          <div className="flex items-center gap-2">
            <AlertCircle size={14} />
            <span>{error}</span>
          </div>
          <button onClick={() => setError('')} className="text-rose-400 hover:text-rose-200">
            <X size={13} />
          </button>
        </div>
      )}

      {/* Main Studio Viewport */}
      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        {/* Template Gallery Drawer / Modal */}
        {showGallery && (
          <div
            className="absolute inset-0 z-30 flex flex-col bg-[#07080c]/95 p-6 backdrop-blur-2xl"
            style={{ overscrollBehavior: 'contain' }}
          >
            <div className="mb-6 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-white">Executive Pipeline Templates</h2>
                <p className="text-xs text-zinc-400">Pre-architected multi-step workflows designed for immediate production execution.</p>
              </div>
              <button
                type="button"
                onClick={() => setShowGallery(false)}
                className="grid size-8 place-items-center rounded-lg border border-white/[0.08] text-zinc-400 hover:bg-white/[0.08] hover:text-white"
              >
                <X size={16} />
              </button>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              {templates.map((tpl) => (
                <div
                  key={tpl.id}
                  className="flex flex-col justify-between rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5 transition hover:border-emerald-500/40 hover:bg-white/[0.04]"
                >
                  <div>
                    <div className="mb-3 flex items-center gap-2.5">
                      <div className="grid size-8 place-items-center rounded-lg border border-emerald-400/20 bg-emerald-400/10 text-emerald-400">
                        {tpl.icon === 'book-open' ? <BookOpen size={16} /> : tpl.icon === 'presentation' ? <FileSpreadsheet size={16} /> : <Sparkles size={16} />}
                      </div>
                      <span className="rounded-md border border-white/[0.08] bg-white/[0.04] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-zinc-400">
                        {tpl.category}
                      </span>
                    </div>
                    <h3 className="text-sm font-semibold text-white">{tpl.name}</h3>
                    <p className="mt-1.5 text-xs leading-relaxed text-zinc-400">{tpl.description}</p>
                    <div className="mt-4 flex flex-wrap gap-1.5">
                      {tpl.nodes.map((node, i) => (
                        <span key={node.id} className="rounded-md bg-white/[0.05] px-2 py-0.5 text-[10px] text-zinc-300">
                          {i + 1}. {node.title}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="mt-6 flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => loadTemplate(tpl)}
                      className="flex-1 rounded-xl border border-emerald-400/40 bg-emerald-500/15 py-2 text-center text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/25"
                    >
                      Use Template
                    </button>
                  </div>
                </div>
              ))}
            </div>

            {/* Custom Workflows list */}
            {workflows.length > 0 && (
              <div className="mt-8">
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-400">My Custom Pipelines</h3>
                <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
                  {workflows.map((wf) => (
                    <button
                      key={wf.id}
                      type="button"
                      onClick={() => {
                        setActiveWorkflow(JSON.parse(JSON.stringify(wf)))
                        setShowGallery(false)
                      }}
                      className="flex items-center justify-between rounded-xl border border-white/[0.08] bg-white/[0.02] p-3 text-left transition hover:border-emerald-500/30 hover:bg-white/[0.05]"
                    >
                      <div className="min-w-0 flex-1">
                        <h4 className="truncate text-xs font-medium text-white">{wf.name}</h4>
                        <p className="text-[11px] text-zinc-500">{wf.nodes?.length || 0} steps</p>
                      </div>
                      <ArrowRight size={14} className="text-zinc-500" />
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Workflow DAG Flow Canvas */}
        <div className="flex flex-1 flex-col overflow-y-auto p-6 md:p-8">
          <div className="mx-auto flex w-full max-w-4xl flex-col items-center">
            {/* Pipeline Step Nodes */}
            <div className="flex w-full flex-col items-center space-y-4">
              {activeWorkflow?.nodes.map((node, index) => {
                const isSelected = selectedNodeId === node.id
                const meta = NODE_TYPES.find((t) => t.type === node.type) || NODE_TYPES[0]
                const NodeIcon = meta.icon
                const runStatus = activeRun?.step_results[node.id]?.status

                return (
                  <div key={node.id} className="flex w-full flex-col items-center">
                    {/* Node Card */}
                    <div
                      onClick={() => setSelectedNodeId(node.id)}
                      className={`group relative flex w-full cursor-pointer items-center justify-between rounded-2xl border p-4 transition-all duration-200 ${
                        isSelected
                          ? 'border-emerald-400/60 bg-emerald-400/[0.06] shadow-[0_0_25px_rgba(16,185,129,0.12)]'
                          : 'border-white/[0.08] bg-white/[0.02] hover:border-white/[0.2] hover:bg-white/[0.04]'
                      }`}
                    >
                      <div className="flex items-center gap-3.5">
                        {/* Step index badge */}
                        <div className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-white/[0.1] bg-white/[0.04] text-xs font-semibold text-zinc-300">
                          {index + 1}
                        </div>

                        {/* Node Icon */}
                        <div
                          className={`grid size-10 shrink-0 place-items-center rounded-xl border border-${meta.color}-400/30 bg-${meta.color}-400/10 text-${meta.color}-400`}
                        >
                          <NodeIcon size={20} />
                        </div>

                        {/* Node Title & Details */}
                        <div>
                          <div className="flex items-center gap-2">
                            <h3 className="text-sm font-semibold text-white">{node.title}</h3>
                            <span className="rounded-md border border-white/[0.08] bg-white/[0.04] px-2 py-0.5 text-[10px] uppercase tracking-wider text-zinc-400">
                              {meta.label}
                            </span>
                          </div>
                          <p className="mt-0.5 text-xs text-zinc-400">
                            {node.description || 'Configurable pipeline step'}
                          </p>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        {/* Run Status Badge */}
                        {runStatus && (
                          <div
                            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium ${
                              runStatus === 'running'
                                ? 'animate-pulse border border-amber-400/30 bg-amber-400/10 text-amber-300'
                                : runStatus === 'success'
                                  ? 'border border-emerald-400/30 bg-emerald-400/10 text-emerald-300'
                                  : runStatus === 'failed'
                                    ? 'border border-rose-400/30 bg-rose-400/10 text-rose-300'
                                    : 'border border-white/[0.08] bg-white/[0.04] text-zinc-400'
                            }`}
                          >
                            {runStatus === 'running' ? (
                              <Loader2 size={12} className="animate-spin" />
                            ) : runStatus === 'success' ? (
                              <CheckCircle2 size={12} />
                            ) : runStatus === 'failed' ? (
                              <AlertCircle size={12} />
                            ) : (
                              <Clock size={12} />
                            )}
                            <span className="capitalize">{runStatus}</span>
                            {activeRun?.step_results[node.id]?.duration_ms ? (
                              <span className="opacity-70">
                                ({((activeRun.step_results[node.id].duration_ms || 0) / 1000).toFixed(1)}s)
                              </span>
                            ) : null}
                          </div>
                        )}

                        {/* Node actions */}
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            removeNode(node.id)
                          }}
                          aria-label={`Remove step ${node.title}`}
                          className="grid size-7 place-items-center rounded-lg text-zinc-500 opacity-0 transition group-hover:opacity-100 hover:bg-rose-500/10 hover:text-rose-400"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </div>

                    {/* Connecting Link Arrow */}
                    {index < (activeWorkflow?.nodes.length || 0) - 1 && (
                      <div className="my-1.5 flex flex-col items-center">
                        <div className="h-4 w-px bg-gradient-to-b from-white/20 to-emerald-400/40" />
                        <div className="grid size-5 place-items-center rounded-full border border-emerald-400/30 bg-black text-emerald-400">
                          <ArrowRight size={10} className="rotate-90" />
                        </div>
                        <div className="h-4 w-px bg-gradient-to-b from-emerald-400/40 to-white/20" />
                      </div>
                    )}
                  </div>
                )
              })}

              {/* Add Step Button */}
              <div className="pt-4">
                <div className="flex flex-wrap items-center justify-center gap-2">
                  <span className="text-xs font-medium text-zinc-500">Add Step:</span>
                  {NODE_TYPES.map((t) => (
                    <button
                      key={t.type}
                      type="button"
                      onClick={() => addNode(t.type)}
                      className="flex items-center gap-1.5 rounded-xl border border-white/[0.08] bg-white/[0.03] px-2.5 py-1 text-xs text-zinc-300 transition hover:border-emerald-400/30 hover:bg-white/[0.06] hover:text-white"
                    >
                      <Plus size={12} className="text-emerald-400" />
                      <span>{t.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Node Inspector Drawer */}
        {selectedNode && (
          <aside className="w-80 shrink-0 border-l border-white/[0.08] bg-black/40 p-5 backdrop-blur-xl md:w-96 overflow-y-auto">
            <div className="flex items-center justify-between border-b border-white/[0.08] pb-4">
              <div className="flex items-center gap-2">
                <Settings2 size={16} className="text-emerald-400" />
                <h3 className="text-sm font-semibold text-white">Configure Step</h3>
              </div>
              <button
                type="button"
                onClick={() => setSelectedNodeId(null)}
                className="text-zinc-400 hover:text-white"
              >
                <X size={15} />
              </button>
            </div>

            <div className="mt-4 space-y-4">
              {/* Step Title */}
              <div>
                <label className="mb-1 block text-xs font-medium text-zinc-300">Step Title</label>
                <input
                  type="text"
                  value={selectedNode.title}
                  onChange={(e) => updateNode(selectedNode.id, { title: e.target.value })}
                  className="w-full rounded-xl border border-white/[0.1] bg-white/[0.04] px-3 py-2 text-xs text-white outline-none focus:border-emerald-400/50"
                />
              </div>

              {/* Step Description */}
              <div>
                <label className="mb-1 block text-xs font-medium text-zinc-300">Description</label>
                <input
                  type="text"
                  value={selectedNode.description || ''}
                  onChange={(e) => updateNode(selectedNode.id, { description: e.target.value })}
                  className="w-full rounded-xl border border-white/[0.1] bg-white/[0.04] px-3 py-2 text-xs text-white outline-none focus:border-emerald-400/50"
                />
              </div>

              {/* Node-specific configuration fields */}
              {selectedNode.type === 'trigger' && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-semibold text-emerald-400">Trigger Inputs</label>
                  </div>
                  {Object.entries(selectedNode.config || {}).map(([key, val]) => (
                    <div key={key}>
                      <label className="mb-1 block text-[11px] font-mono text-zinc-400">{key}</label>
                      <input
                        type="text"
                        value={String(val)}
                        onChange={(e) => updateNodeConfig(selectedNode.id, key, e.target.value)}
                        className="w-full rounded-xl border border-white/[0.1] bg-white/[0.04] px-3 py-2 text-xs text-white outline-none focus:border-emerald-400/50"
                      />
                    </div>
                  ))}
                  <p className="text-[11px] text-zinc-500">
                    Accessible across pipeline steps via <code className="text-emerald-300">{'{{inputs.<key>}}'}</code>
                  </p>
                </div>
              )}

              {selectedNode.type === 'web_search' && (
                <div className="space-y-3">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-zinc-300">Search Query Template</label>
                    <textarea
                      rows={2}
                      value={selectedNode.config.query || ''}
                      onChange={(e) => updateNodeConfig(selectedNode.id, 'query', e.target.value)}
                      className="w-full rounded-xl border border-white/[0.1] bg-white/[0.04] p-3 text-xs text-white outline-none focus:border-emerald-400/50"
                    />
                    <p className="mt-1 text-[11px] text-zinc-500">
                      Use <code className="text-emerald-300">{'{{inputs.topic}}'}</code> to inject parameters dynamically.
                    </p>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-zinc-300">Max Grounded Sources</label>
                    <input
                      type="number"
                      min={1}
                      max={10}
                      value={selectedNode.config.max_sources || 4}
                      onChange={(e) => updateNodeConfig(selectedNode.id, 'max_sources', Number(e.target.value))}
                      className="w-full rounded-xl border border-white/[0.1] bg-white/[0.04] px-3 py-2 text-xs text-white outline-none focus:border-emerald-400/50"
                    />
                  </div>
                </div>
              )}

              {selectedNode.type === 'llm_transform' && (
                <div className="space-y-3">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-zinc-300">Reasoning Model</label>
                    <select
                      value={selectedNode.config.model || 'meta/llama-3.3-70b-instruct'}
                      onChange={(e) => updateNodeConfig(selectedNode.id, 'model', e.target.value)}
                      className="w-full rounded-xl border border-white/[0.1] bg-zinc-900 px-3 py-2 text-xs text-white outline-none focus:border-emerald-400/50"
                    >
                      <option value="meta/llama-3.3-70b-instruct">meta/llama-3.3-70b-instruct</option>
                      <option value="mistralai/mixtral-8x22b-instruct-v0.1">mistralai/mixtral-8x22b-instruct</option>
                      <option value="meta/llama-3.1-405b-instruct">meta/llama-3.1-405b-instruct</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-zinc-300">Synthesis Prompt Template</label>
                    <textarea
                      rows={6}
                      value={selectedNode.config.prompt || ''}
                      onChange={(e) => updateNodeConfig(selectedNode.id, 'prompt', e.target.value)}
                      className="w-full rounded-xl border border-white/[0.1] bg-white/[0.04] p-3 text-xs text-white outline-none focus:border-emerald-400/50"
                    />
                    <div className="mt-1 flex flex-wrap gap-1">
                      <span className="text-[10px] text-zinc-500">Hints:</span>
                      <button
                        type="button"
                        onClick={() => updateNodeConfig(selectedNode.id, 'prompt', (selectedNode.config.prompt || '') + ' {{inputs.topic}}')}
                        className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-emerald-300 hover:bg-white/[0.1]"
                      >
                        + {'{{inputs.topic}}'}
                      </button>
                      <button
                        type="button"
                        onClick={() => updateNodeConfig(selectedNode.id, 'prompt', (selectedNode.config.prompt || '') + ' {{steps.step_2_web_search.output}}')}
                        className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-sky-300 hover:bg-white/[0.1]"
                      >
                        + {'{{steps.<id>.output}}'}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {selectedNode.type === 'image_generation' && (
                <div className="space-y-3">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-zinc-300">Visual Prompt</label>
                    <textarea
                      rows={3}
                      value={selectedNode.config.prompt || ''}
                      onChange={(e) => updateNodeConfig(selectedNode.id, 'prompt', e.target.value)}
                      className="w-full rounded-xl border border-white/[0.1] bg-white/[0.04] p-3 text-xs text-white outline-none focus:border-emerald-400/50"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-zinc-300">Style</label>
                    <select
                      value={selectedNode.config.style || 'diagram'}
                      onChange={(e) => updateNodeConfig(selectedNode.id, 'style', e.target.value)}
                      className="w-full rounded-xl border border-white/[0.1] bg-zinc-900 px-3 py-2 text-xs text-white outline-none"
                    >
                      <option value="diagram">Modern Architecture Diagram</option>
                      <option value="photorealistic">Photorealistic (8k)</option>
                      <option value="cinematic">Cinematic 35mm</option>
                      <option value="digital-art">Digital Concept Art</option>
                      <option value="minimalist">Minimalist Modern</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-zinc-300">Aspect Ratio</label>
                    <select
                      value={selectedNode.config.aspect_ratio || '16:9'}
                      onChange={(e) => updateNodeConfig(selectedNode.id, 'aspect_ratio', e.target.value)}
                      className="w-full rounded-xl border border-white/[0.1] bg-zinc-900 px-3 py-2 text-xs text-white outline-none"
                    >
                      <option value="16:9">16:9 (Widescreen)</option>
                      <option value="1:1">1:1 (Square)</option>
                      <option value="4:3">4:3 (Presentation)</option>
                    </select>
                  </div>
                </div>
              )}

              {selectedNode.type === 'document_generation' && (
                <div className="space-y-3">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-zinc-300">Deliverable Format</label>
                    <select
                      value={selectedNode.config.format || 'docx'}
                      onChange={(e) => updateNodeConfig(selectedNode.id, 'format', e.target.value)}
                      className="w-full rounded-xl border border-white/[0.1] bg-zinc-900 px-3 py-2 text-xs text-white outline-none"
                    >
                      <option value="pdf">PDF Document (.pdf)</option>
                      <option value="docx">Microsoft Word (.docx)</option>
                      <option value="pptx">PowerPoint Slides (.pptx)</option>
                      <option value="xlsx">Excel Spreadsheet (.xlsx)</option>
                      <option value="html">Interactive Styled HTML (.html)</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-zinc-300">Document Title</label>
                    <input
                      type="text"
                      value={selectedNode.config.title || ''}
                      onChange={(e) => updateNodeConfig(selectedNode.id, 'title', e.target.value)}
                      className="w-full rounded-xl border border-white/[0.1] bg-white/[0.04] px-3 py-2 text-xs text-white outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-zinc-300">Document Body Content</label>
                    <textarea
                      rows={4}
                      value={typeof selectedNode.config.content === 'string' ? selectedNode.config.content : JSON.stringify(selectedNode.config.content, null, 2)}
                      onChange={(e) => updateNodeConfig(selectedNode.id, 'content', e.target.value)}
                      className="w-full rounded-xl border border-white/[0.1] bg-white/[0.04] p-3 text-xs text-white outline-none focus:border-emerald-400/50"
                    />
                  </div>
                </div>
              )}
            </div>
          </aside>
        )}
      </div>

      {/* Execution Runner Modal */}
      {runModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-md"
          style={{ overscrollBehavior: 'contain' }}
        >
          <div className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-3xl border border-white/[0.1] bg-[#0c0d12] shadow-2xl">
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-white/[0.08] px-6 py-4">
              <div className="flex items-center gap-2.5">
                <div className="grid size-8 place-items-center rounded-xl border border-emerald-400/30 bg-emerald-400/10 text-emerald-400">
                  <Play size={15} className="fill-emerald-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">Execute Workflow: {activeWorkflow?.name}</h3>
                  <p className="text-xs text-zinc-400">Configure parameters and launch topological execution.</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setRunModalOpen(false)}
                className="grid size-7 place-items-center rounded-lg text-zinc-400 hover:text-white"
              >
                <X size={16} />
              </button>
            </div>

            {/* Modal Content */}
            <div className="flex-1 space-y-4 overflow-y-auto p-6">
              {!activeRun || activeRun.status === 'pending' ? (
                <div className="space-y-4">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-emerald-400">Pipeline Parameters</h4>
                  {Object.entries(runInputs).map(([k, v]) => (
                    <div key={k}>
                      <label className="mb-1 block text-xs font-medium text-zinc-300">{k}</label>
                      <input
                        type="text"
                        value={String(v)}
                        onChange={(e) => setRunInputs({ ...runInputs, [k]: e.target.value })}
                        className="w-full rounded-xl border border-white/[0.1] bg-white/[0.04] px-3.5 py-2.5 text-xs text-white outline-none focus:border-emerald-400/50"
                      />
                    </div>
                  ))}
                  <div className="pt-2">
                    <button
                      type="button"
                      onClick={handleStartRun}
                      disabled={executing}
                      className="flex w-full items-center justify-center gap-2 rounded-xl border border-emerald-400/40 bg-emerald-500 py-3 text-xs font-semibold text-black transition hover:bg-emerald-400 active:scale-95 disabled:opacity-50"
                    >
                      {executing ? <Loader2 size={16} className="animate-spin text-black" /> : <Play size={16} className="fill-black" />}
                      <span>Launch Pipeline Execution</span>
                    </button>
                  </div>
                </div>
              ) : (
                /* Active Execution Tracker */
                <div className="space-y-5">
                  <div className="flex items-center justify-between rounded-xl border border-white/[0.08] bg-white/[0.02] p-3.5">
                    <div className="flex items-center gap-2.5">
                      {activeRun.status === 'running' ? (
                        <Loader2 size={18} className="animate-spin text-amber-400" />
                      ) : activeRun.status === 'success' ? (
                        <CheckCircle2 size={18} className="text-emerald-400" />
                      ) : (
                        <AlertCircle size={18} className="text-rose-400" />
                      )}
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold capitalize text-white">Status: {activeRun.status}</span>
                        </div>
                        <p className="text-[11px] text-zinc-400">Run ID: {activeRun.id.slice(0, 12)}</p>
                      </div>
                    </div>
                  </div>

                  {/* Step-by-Step Progress Checklist */}
                  <div className="space-y-2">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">Execution Steps</h4>
                    {Object.values(activeRun.step_results).map((step: WorkflowStepResult, idx) => (
                      <div
                        key={step.node_id}
                        className={`rounded-xl border p-3 text-xs ${
                          step.status === 'running'
                            ? 'border-amber-400/40 bg-amber-400/[0.05]'
                            : step.status === 'success'
                              ? 'border-emerald-400/30 bg-emerald-400/[0.04]'
                              : step.status === 'failed'
                                ? 'border-rose-400/30 bg-rose-400/[0.04]'
                                : 'border-white/[0.06] bg-white/[0.02] text-zinc-400'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            {step.status === 'running' ? (
                              <Loader2 size={13} className="animate-spin text-amber-400" />
                            ) : step.status === 'success' ? (
                              <CheckCircle2 size={13} className="text-emerald-400" />
                            ) : step.status === 'failed' ? (
                              <AlertCircle size={13} className="text-rose-400" />
                            ) : (
                              <Clock size={13} />
                            )}
                            <span className="font-semibold text-white">
                              {idx + 1}. {step.title}
                            </span>
                          </div>
                          {step.duration_ms ? (
                            <span className="text-[10px] text-zinc-400">
                              {(step.duration_ms / 1000).toFixed(1)}s
                            </span>
                          ) : null}
                        </div>

                        {/* Step Logs Stream */}
                        {step.logs && step.logs.length > 0 && (
                          <div className="mt-2 space-y-0.5 rounded-lg bg-black/40 p-2 font-mono text-[10px] text-zinc-300">
                            {step.logs.map((log, li) => (
                              <div key={li} className="truncate">
                                {log}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* Generated Deliverables Showcase */}
                  {activeRun.outputs?.files && activeRun.outputs.files.length > 0 && (
                    <div className="space-y-2 pt-2">
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-emerald-400">
                        Generated Deliverables ({activeRun.outputs.files.length})
                      </h4>
                      <div className="grid gap-2 sm:grid-cols-2">
                        {activeRun.outputs.files.map((file) => (
                          <div
                            key={file.id}
                            className="flex items-center justify-between rounded-xl border border-emerald-400/30 bg-emerald-400/[0.06] p-3"
                          >
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-1.5">
                                <FileCheck size={14} className="text-emerald-400" />
                                <span className="truncate text-xs font-medium text-white">{file.filename}</span>
                              </div>
                              <span className="text-[10px] text-emerald-300/70">
                                {file.format.toUpperCase()} • {(file.size_bytes / 1024).toFixed(1)} KB
                              </span>
                            </div>
                            <div className="ml-2 flex items-center gap-1">
                              <button
                                type="button"
                                onClick={() => setPreviewFile(file)}
                                className="grid size-7 place-items-center rounded-lg border border-emerald-400/30 text-emerald-300 transition hover:bg-emerald-400/20"
                                title="Preview deliverable"
                              >
                                <Eye size={13} />
                              </button>
                              <button
                                type="button"
                                onClick={() => void downloadGeneratedFile(file.id, file.filename)}
                                className="grid size-7 place-items-center rounded-lg border border-emerald-400/30 text-emerald-300 transition hover:bg-emerald-400/20"
                                title="Download deliverable"
                              >
                                <Download size={13} />
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Deliverable Preview Modal */}
      {previewFile && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-md"
          style={{ overscrollBehavior: 'contain' }}
        >
          <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-3xl border border-white/[0.1] bg-[#0c0d12] shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/[0.08] px-6 py-4">
              <div className="flex items-center gap-2">
                <FileCheck size={16} className="text-emerald-400" />
                <h3 className="text-sm font-semibold text-white">{previewFile.filename}</h3>
                <span className="text-xs text-zinc-400">({previewFile.format.toUpperCase()})</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void downloadGeneratedFile(previewFile.id, previewFile.filename)}
                  className="flex items-center gap-1.5 rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-300 transition hover:bg-emerald-500/20"
                >
                  <Download size={13} />
                  <span>Download</span>
                </button>
                <button
                  type="button"
                  onClick={() => setPreviewFile(null)}
                  className="grid size-7 place-items-center rounded-lg text-zinc-400 hover:text-white"
                >
                  <X size={16} />
                </button>
              </div>
            </div>
            <div className="flex flex-1 items-center justify-center overflow-y-auto p-6">
              {['jpg', 'jpeg', 'png'].includes(previewFile.format.toLowerCase()) ? (
                <img
                  src={`/api/files/${previewFile.id}/download?inline=true`}
                  alt={previewFile.filename}
                  className="max-h-[65vh] rounded-xl object-contain shadow-lg"
                />
              ) : ['html', 'pdf'].includes(previewFile.format.toLowerCase()) ? (
                <iframe
                  src={`/api/files/${previewFile.id}/download?inline=true`}
                  title={previewFile.filename}
                  className="h-[65vh] w-full rounded-xl border border-white/[0.08] bg-white"
                />
              ) : (
                <div className="py-12 text-center">
                  <FileText size={48} className="mx-auto mb-3 text-emerald-400/60" />
                  <p className="text-sm font-medium text-white">{previewFile.filename}</p>
                  <p className="mt-1 text-xs text-zinc-400">
                    File compiled and ready. Download to inspect full {previewFile.format.toUpperCase()} formatting.
                  </p>
                  <button
                    type="button"
                    onClick={() => void downloadGeneratedFile(previewFile.id, previewFile.filename)}
                    className="mt-4 inline-flex items-center gap-1.5 rounded-xl border border-emerald-400/40 bg-emerald-500/20 px-4 py-2 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/30"
                  >
                    <Download size={14} />
                    <span>Download File</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
