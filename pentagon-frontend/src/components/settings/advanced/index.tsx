import { useState } from 'react'
import {
  Cpu,
  Database,
  Info,
  Palette,
  Server,
  ShieldCheck,
  Sparkles,
  Terminal,
} from 'lucide-react'
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

const ADVANCED_SECTIONS = [
  { id: 'Skills', label: 'Skills', icon: Sparkles },
  { id: 'MCP Servers', label: 'MCP Servers', icon: Server },
  { id: 'Commands', label: 'Commands', icon: Terminal },
  { id: 'Data', label: 'Data', icon: Database },
  { id: 'Appearance', label: 'Appearance', icon: Palette },
  { id: 'Model', label: 'Model', icon: Cpu },
  { id: 'Audit log', label: 'Audit Log', icon: ShieldCheck },
  { id: 'About', label: 'About', icon: Info },
] as const
export type AdvancedSection = (typeof ADVANCED_SECTIONS)[number]['id']

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
      {/* Horizontally scrollable section picker on mobile/tablet */}
      <div
        className="flex gap-1 overflow-x-auto rounded-xl border border-white/[0.09] bg-white/[0.02] p-1 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden"
        role="tablist"
        aria-label="Advanced sections"
      >
        {ADVANCED_SECTIONS.map((item) => {
          const Icon = item.icon
          const isSelected = advancedSection === item.id
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={isSelected}
              onClick={() => setAdvancedSection(item.id)}
              className={`flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-small font-medium transition ${
                isSelected
                  ? 'bg-emerald-400/15 text-emerald-300 shadow-sm'
                  : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              <Icon size={13} className={isSelected ? 'text-emerald-400' : 'text-zinc-500'} />
              <span>{item.label}</span>
            </button>
          )
        })}
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
