/**
 * The Advanced tab's Skills section: the loaded list plus the add-a-skill
 * form. State and handlers moved here verbatim from SettingsDialog.tsx.
 */
import { useEffect, useState } from 'react'
import { apiRequest } from '../../../api'
import type { SkillInfo } from '../../../types'
import { Section, inputClass } from '../shared'

export function SkillsSection({ userId }: { userId: string }) {
  const [skills, setSkills] = useState<SkillInfo[] | null>(null)
  const [skillError, setSkillError] = useState('')
  const [skillNotice, setSkillNotice] = useState('')
  const [skillBusy, setSkillBusy] = useState(false)
  const [skillDraft, setSkillDraft] = useState({
    name: '',
    description: '',
    triggers: '',
    body: '',
    risk: 'read',
  })

  useEffect(() => {
    let active = true
    void apiRequest<SkillInfo[]>(`/api/skills?user_id=${encodeURIComponent(userId)}`)
      .then((rows) => {
        if (active) setSkills(rows)
      })
      .catch((cause) => {
        if (!active) return
        setSkillError(cause instanceof Error ? cause.message : 'Could not load skills.')
        setSkills([])
      })
    return () => {
      active = false
    }
  }, [userId])

  async function toggleSkill(skill: SkillInfo, enabled: boolean) {
    setSkillError('')
    setSkillNotice('')
    try {
      await apiRequest(`/api/skills/${encodeURIComponent(skill.id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, enabled }),
      })
      setSkills((rows) =>
        (rows ?? []).map((row) => (row.id === skill.id ? { ...row, enabled } : row)),
      )
    } catch (cause) {
      setSkillError(
        cause instanceof Error ? cause.message : 'Could not update that skill.',
      )
    }
  }

  async function addSkill(event: React.FormEvent) {
    event.preventDefault()
    if (skillBusy) return
    setSkillError('')
    setSkillNotice('')
    const triggers = skillDraft.triggers
      .split(',')
      .map((trigger) => trigger.trim())
      .filter(Boolean)
    if (!skillDraft.name.trim() || !skillDraft.description.trim() || triggers.length === 0 || !skillDraft.body.trim()) {
      setSkillError('Name, description, at least one trigger and an instruction body are required.')
      return
    }
    if (skillDraft.description.trim().length > 200) {
      setSkillError('The description is capped at 200 characters — it is the only text the model sees before loading a skill.')
      return
    }
    setSkillBusy(true)
    try {
      const created = await apiRequest<SkillInfo>('/api/skills', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          name: skillDraft.name.trim(),
          description: skillDraft.description.trim(),
          triggers,
          risk_category: skillDraft.risk,
          body: skillDraft.body.trim(),
        }),
      })
      setSkills((rows) => [created, ...(rows ?? [])])
      setSkillDraft({ name: '', description: '', triggers: '', body: '', risk: 'read' })
      setSkillNotice(`Added ${created.name}. It applies from your next message — no restart.`)
    } catch (cause) {
      setSkillError(cause instanceof Error ? cause.message : 'Could not save the skill.')
    } finally {
      setSkillBusy(false)
    }
  }

  return (
    <>
      <Section
        title="Skills"
        hint="Capability packs the model can draw on. Every skill's one-line description is always visible; the full instructions load only for a request that matches, for that turn only — never into saved history."
      >
        {skillError && <p className="mb-2 text-small text-amber-300/90">{skillError}</p>}
        {skills === null ? (
          <p className="text-small text-zinc-600">Loading…</p>
        ) : skills.length === 0 ? (
          <p className="text-small text-zinc-600">Nothing here yet.</p>
        ) : (
          <ul className="space-y-1.5">
            {skills.map((skill) => (
              <li
                key={skill.id}
                className="flex items-start gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2"
              >
                <span className="min-w-0 flex-1">
                  <span className="text-small-lg text-zinc-300">{skill.name}</span>
                  <span className="ml-2 rounded border border-white/[0.1] px-1.5 py-0.5 text-micro text-zinc-500">
                    {skill.source === 'public' ? 'shipped' : 'yours'}
                  </span>
                  <span className="mt-0.5 block text-micro leading-[1.55] text-zinc-600">
                    {skill.description}
                  </span>
                  <span className="mt-1 block text-micro text-zinc-700">
                    Triggers: {skill.triggers.join(', ') || '—'}
                  </span>
                </span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={skill.enabled}
                  aria-label={`${skill.enabled ? 'Disable' : 'Enable'} ${skill.name}`}
                  onClick={() => void toggleSkill(skill, !skill.enabled)}
                  className="flex shrink-0 items-center gap-2 text-micro text-zinc-600"
                >
                  <span aria-hidden="true" className="flex h-5 w-9 items-center rounded-full p-0.5 transition">
                    <span
                      className={`size-4 rounded-full transition-transform ${
                        skill.enabled ? 'translate-x-4 bg-emerald-300' : 'bg-white/[0.18]'
                      }`}
                    />
                  </span>
                  {skill.enabled ? 'On' : 'Off'}
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="Add a skill"
        hint="Writes skills/user/<name>/SKILL.md on the server. It is live from your next message — no restart."
      >
        <form onSubmit={(event) => void addSkill(event)} className="space-y-3">
          <input
            value={skillDraft.name}
            onChange={(event) => setSkillDraft({ ...skillDraft, name: event.target.value })}
            placeholder="Name, e.g. Meeting notes"
            maxLength={80}
            className={inputClass}
            aria-label="Skill name"
          />
          <input
            value={skillDraft.description}
            onChange={(event) => setSkillDraft({ ...skillDraft, description: event.target.value })}
            placeholder="What it covers and exactly when to use it (under 200 characters)"
            maxLength={200}
            className={inputClass}
            aria-label="Skill description"
          />
          <input
            value={skillDraft.triggers}
            onChange={(event) => setSkillDraft({ ...skillDraft, triggers: event.target.value })}
            placeholder="Trigger keywords, comma separated — e.g. standup, action items"
            className={inputClass}
            aria-label="Trigger keywords"
          />
          <textarea
            value={skillDraft.body}
            onChange={(event) => setSkillDraft({ ...skillDraft, body: event.target.value })}
            placeholder={'Instructions, step by step. Written like a briefing for a competent colleague:\n\n1. …\n2. …'}
            rows={7}
            className="w-full rounded-lg border border-white/[0.09] bg-white/[0.03] px-3 py-2 text-body leading-6 text-zinc-100 outline-none transition placeholder:text-zinc-700 focus:border-white/30"
            aria-label="Skill instructions"
          />
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="submit"
              disabled={skillBusy}
              className="h-9 rounded-lg bg-white/[0.12] px-3.5 text-small font-medium text-zinc-100 transition hover:bg-white/[0.18] disabled:opacity-50"
            >
              {skillBusy ? 'Adding…' : 'Add skill'}
            </button>
            {skillNotice && (
              <p className="text-small text-emerald-300/90">{skillNotice}</p>
            )}
          </div>
          {skillError && <p className="text-small text-amber-300/90">{skillError}</p>}
        </form>
      </Section>
    </>
  )
}
