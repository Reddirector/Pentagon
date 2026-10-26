export interface McpHubServer {
  id: string
  name: string
  description: string
  status: 'connected' | 'idle' | 'error'
  transport: 'stdio' | 'sse' | 'embedded'
  latencyMs: number
  tools: Array<{
    name: string
    description: string
    parameters?: string[]
  }>
}

export const DEFAULT_MCP_SERVERS: McpHubServer[] = [
  {
    id: 'filesystem',
    name: 'Local Filesystem & Workspace',
    description: 'Direct workspace access: reading, editing, diffing files, and directory navigation.',
    status: 'connected',
    transport: 'stdio',
    latencyMs: 1,
    tools: [
      { name: 'read_file', description: 'Read full or partial contents of text, code, or binary files', parameters: ['Path', 'StartLine', 'EndLine'] },
      { name: 'write_file', description: 'Write or append content directly to workspace files', parameters: ['Path', 'Content', 'Overwrite'] },
      { name: 'edit_file', description: 'Apply atomic single-block surgical edits with exact target matching', parameters: ['Path', 'Target', 'Replacement'] },
      { name: 'run_command', description: 'Execute bash commands and subprocesses with output capture', parameters: ['CommandLine', 'WaitMsBeforeAsync'] },
    ],
  },
  {
    id: 'chrome-devtools',
    name: 'Chrome DevTools MCP',
    description: 'Headless browser automation, accessibility audit, DOM inspection, and console logging.',
    status: 'connected',
    transport: 'stdio',
    latencyMs: 14,
    tools: [
      { name: 'navigate_page', description: 'Navigate active page to URL', parameters: ['url'] },
      { name: 'take_screenshot', description: 'Capture screenshot of viewport or full page element', parameters: ['selector'] },
      { name: 'evaluate_script', description: 'Execute JavaScript expression in page context', parameters: ['expression'] },
      { name: 'lighthouse_audit', description: 'Run full Core Web Vitals and accessibility audit', parameters: ['url'] },
    ],
  },
  {
    id: 'gemini-docs',
    name: 'Gemini & Developer Knowledge',
    description: 'Upstream Google Gemini API, GenAI SDK, and multi-cloud documentation search and retrieval.',
    status: 'connected',
    transport: 'stdio',
    latencyMs: 42,
    tools: [
      { name: 'gemini_search_docs', description: 'Search upstream Gemini SDK guides and API schemas', parameters: ['query', 'language'] },
      { name: 'gemini_get_doc', description: 'Retrieve documentation chunk by chunk_id', parameters: ['chunk_id'] },
    ],
  },
  {
    id: 'dart-flutter',
    name: 'Dart & Flutter MCP',
    description: 'Language server protocol (LSP), widget inspector, hot reload, and static analysis.',
    status: 'connected',
    transport: 'stdio',
    latencyMs: 4,
    tools: [
      { name: 'analyze_files', description: 'Run static analysis across Dart codebase', parameters: ['roots'] },
      { name: 'hot_reload', description: 'Trigger state-preserving hot reload on running Flutter app', parameters: [] },
      { name: 'widget_inspector', description: 'Inspect render tree hierarchy and layout boundaries', parameters: [] },
    ],
  },
  {
    id: 'biomolecular-molstar',
    name: 'Biomolecular Structure Viewer',
    description: 'Mol* 3D molecular structure renderer, residue highlight annotations, and PDB parsing.',
    status: 'connected',
    transport: 'embedded',
    latencyMs: 2,
    tools: [
      { name: 'load_structure', description: 'Load PDB/mmCIF structural file into 3D Mol* canvas', parameters: ['path'] },
      { name: 'highlight_region', description: 'Highlight active site residues or ligand binding pockets', parameters: ['residues'] },
    ],
  },
  {
    id: 'postgresql',
    name: 'PostgreSQL Relational DB',
    description: 'High-throughput connection pooler for schema inspection, migrations, and query execution.',
    status: 'connected',
    transport: 'stdio',
    latencyMs: 8,
    tools: [
      { name: 'execute_query', description: 'Run parameterized SQL query against database', parameters: ['query'] },
      { name: 'inspect_schema', description: 'Introspect tables, indexes, and foreign keys', parameters: ['table_name'] },
    ],
  },
]
