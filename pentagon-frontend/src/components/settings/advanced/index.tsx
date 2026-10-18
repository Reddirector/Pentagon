/**
 * The Advanced top tab: a thin container that owns only the section-picker
 * state and renders the matching section component. All data and handlers
 * flow in as props so each section stays self-contained.
 */
import { useState } from 'react'
import type {
  AutonomySettings,
  CommandSettings,
  Conversation,
  DocumentInfo,
  ModelInfo,
} from '../../../types'
import { SkillsSection } from './SkillsSection'
import { McpSection } from './McpSection'
import { CommandsSection } from './CommandsSection'
import { DataSection } from './DataSection'
import { AppearanceSection, DefaultModelSection } from './AppearanceSection'
import { AuditLogSection, AboutSection } from './AuditLogSection'

const ADVANCED_SECTIONS = ['Skills', 'MCP Servers', 'Commands', 'Data', 'Appearance', 'Model', 'Audit log', 'About'] as const
export type AdvancedSection = (typeof ADVANCED_SECTIONS)[number]

export interface AdvancedTabProps {
  userId: string
  models: ModelInfo[]
  serverDefaultModel: string
  documents: DocumentInfo[]
  threads: Conversation[]
  threadCount: number
  onDocumentDeleted: (documentId: string) => void
  onRenameThread: (id: string, title: string) => void
  onDeleteThread: (id: string) => void
  commandSettings: CommandSettings
  onCommandSettingsChange: (enabled: boolean) => void
  autonomySettings: AutonomySettings | null
  onAutonomySettingChange?: (category: string, level: string) => void | Promise<void>
  onAutonomyPresetChange?: (preset: string) => void | Promise<void>
  initialSection?: AdvancedSection
}

export function AdvancedTab(props: AdvancedTabProps) {
  const [advancedSection, setAdvancedSection] = useState<AdvancedSection>(props.initialSection ?? 'Skills')

  return (
    <div className="min-h-[240px]">
      {/* Section picker: one extra click before anything inside Advanced is shown. */}
      <div className="flex gap-1 rounded-xl border border-white/[0.09] bg-white/[0.02] p-1" role="tablist" aria-label="Advanced sections">
        {ADVANCED_SECTIONS.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={advancedSection === name}
            onClick={() => setAdvancedSection(name)}
            className={`rounded-lg px-3 py-1.5 text-small font-medium transition ${
              advancedSection === name
                ? 'bg-white/[0.06] text-zinc-100'
                : 'text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {name}
          </button>
        ))}
      </div>

      <div className="mt-4 space-y-4">
        {advancedSection === 'Skills' && <SkillsSection userId={props.userId} />}
        {advancedSection === 'MCP Servers' && <McpSection userId={props.userId} />}
        {advancedSection === 'Commands' && (
          <CommandsSection
            userId={props.userId}
            commandSettings={props.commandSettings}
            onCommandSettingsChange={props.onCommandSettingsChange}
          />
        )}
        {advancedSection === 'Data' && (
          <DataSection
            userId={props.userId}
            documents={props.documents}
            documentCount={props.documents.length}
            threads={props.threads}
            threadCount={props.threadCount}
            onDocumentDeleted={props.onDocumentDeleted}
            onRenameThread={props.onRenameThread}
            onDeleteThread={props.onDeleteThread}
            onJumpToAppearance={() => setAdvancedSection('Appearance')}
          />
        )}
        {advancedSection === 'Appearance' && <AppearanceSection />}
        {advancedSection === 'Model' && (
          <DefaultModelSection models={props.models} serverDefaultModel={props.serverDefaultModel} />
        )}
        {advancedSection === 'Audit log' && (
          <AuditLogSection userId={props.userId} autonomySettings={props.autonomySettings} />
        )}
        {advancedSection === 'About' && <AboutSection />}
      </div>
    </div>
  )
}
