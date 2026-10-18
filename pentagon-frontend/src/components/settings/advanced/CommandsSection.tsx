/**
 * The Advanced tab's Commands section: the tool toggle plus the explanatory
 * sections about desktop control, location and injection defence.
 */
import { useState } from 'react'
import { AlertTriangle, LockKeyhole, MapPin } from 'lucide-react'
import { apiRequest } from '../../../api'
import type { CommandSettings } from '../../../types'
import { Section } from '../shared'

export function CommandsSection({
  userId,
  commandSettings,
  onCommandSettingsChange,
}: {
  userId: string
  commandSettings: CommandSettings
  onCommandSettingsChange: (enabled: boolean) => void
}) {
  const [commandBusy, setCommandBusy] = useState(false)
  const [commandError, setCommandError] = useState('')

  async function setCommandsEnabled(enabled: boolean) {
    if (commandBusy) return
    setCommandBusy(true)
    setCommandError('')
    try {
      const result = await apiRequest<CommandSettings>(
        `/api/commands/settings?user_id=${encodeURIComponent(userId)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled }),
        },
      )
      onCommandSettingsChange(result.enabled)
    } catch (cause) {
      setCommandError(cause instanceof Error ? cause.message : 'Could not change that setting.')
    } finally {
      setCommandBusy(false)
    }
  }

  return (
    <>
      <Section
        title="Command tool"
        hint="Lets Pentagon run CLI commands on this machine so it can build, test and inspect your project instead of only describing what to do."
      >
        {!commandSettings.available ? (
          <p className="rounded-lg border border-white/[0.07] bg-white/[0.02] px-3.5 py-3 text-small leading-6 text-zinc-500">
            This server does not offer the command tool. Set{' '}
            <code className="font-mono text-zinc-400">COMMAND_TOOL_ENABLED=true</code> in the
            backend environment and restart it to make it available.
          </p>
        ) : (
          <>
            <button
              type="button"
              role="switch"
              aria-checked={commandSettings.enabled}
              disabled={commandBusy}
              onClick={() => void setCommandsEnabled(!commandSettings.enabled)}
              className="flex w-full items-start gap-3 rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-3 text-left transition hover:border-white/15 disabled:opacity-50"
            >
              <span
                aria-hidden="true"
                className={`mt-0.5 flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition ${
                  commandSettings.enabled ? 'bg-emerald-300' : 'bg-white/[0.12]'
                }`}
              >
                <span
                  className={`size-4 rounded-full bg-black transition-transform ${
                    commandSettings.enabled ? 'translate-x-4' : ''
                  }`}
                />
              </span>
              <span className="min-w-0">
                <span className="block text-body font-medium text-zinc-100">
                  Let Pentagon run commands
                </span>
                <span className="mt-0.5 block text-micro-sm leading-[1.55] text-zinc-600">
                  {commandSettings.enabled
                    ? 'On. Read-only commands run immediately; anything else asks you first.'
                    : 'Off. The model is not offered a command tool at all.'}
                </span>
              </span>
            </button>
            {commandError && (
              <p className="mt-2 text-small text-amber-300/90">{commandError}</p>
            )}
          </>
        )}
      </Section>

      <Section title="How a command is treated" hint="The rule is that nothing runs unless you would be comfortable typing it yourself.">
        <p className="text-small leading-6 text-zinc-500">
          Read-only commands run by themselves; anything that changes your machine or
          reaches outside it asks you first. Commands that need{' '}
          <code className="font-mono text-[0.92em]">sudo</code> or another user account are
          refused outright, approved or not.
        </p>
      </Section>

      <Section
        title="Your desktop"
        hint="Alongside the command line, it can drive the desktop: open and close applications, focus windows, take screenshots, change the volume, control playback, send notifications, lock the screen, switch dark mode and manage power."
      >
        {commandSettings.desktop_available ? (
          <>
            <ul className="space-y-2.5 text-small leading-6 text-zinc-500">
              <li className="flex gap-2.5">
                <span className="mt-1 shrink-0 text-zinc-500">·</span>
                <span>
                  <span className="text-zinc-300">Listing windows runs by itself.</span> Seeing
                  which windows are open changes nothing, so it does not interrupt you.
                </span>
              </li>
              <li className="flex gap-2.5">
                <LockKeyhole size={13} className="mt-1 shrink-0 text-zinc-500" />
                <span>
                  <span className="text-zinc-300">Everything else asks first.</span> Closing an
                  app, locking the screen or shutting the machine down are shown to you as a
                  plain description, not a command line, and do nothing if you decline.
                </span>
              </li>
              <li className="flex gap-2.5">
                <AlertTriangle size={13} className="mt-1 shrink-0 text-zinc-500" />
                <span>
                  <span className="text-zinc-300">A fixed set, no shell.</span> These are named
                  actions, not commands you can talk into. There is no way to phrase an
                  instruction that turns into a shell command line.
                </span>
              </li>
            </ul>
            <p className="mt-3 text-micro leading-5 text-zinc-600">
              It closes a window by matching part of its title, so check what it picked before
              saying yes.
            </p>
          </>
        ) : (
          <p className="text-small leading-6 text-zinc-500">
            Desktop control is switched off on the server, so the model cannot open or close
            anything on this machine. Command line access is unaffected.
          </p>
        )}
      </Section>

      <Section
        title="Where it thinks you are"
        hint="For questions that depend on it — what is near me, what time is it there — it can look up your approximate position. It does this only when an answer actually needs it, never in the background."
      >
        {commandSettings.location_available ? (
          <>
            <ul className="space-y-2.5 text-small leading-6 text-zinc-500">
              <li className="flex gap-2.5">
                <MapPin size={13} className="mt-1 shrink-0 text-zinc-500" />
                <span>
                  <span className="text-zinc-300">Your browser is asked first.</span> The app
                  window shows you the usual permission prompt. If you decline, it falls back
                  to a coarse estimate from your network connection.
                </span>
              </li>
              <li className="flex gap-2.5">
                <AlertTriangle size={13} className="mt-1 shrink-0 text-zinc-500" />
                <span>
                  <span className="text-zinc-300">It is rarely precise.</span> This computer has
                  no GPS, so a fallback is town-level at best. The answer always says which
                  source produced it.
                </span>
              </li>
            </ul>
            <p className="mt-3 text-micro leading-5 text-zinc-600">
              Declining costs nothing: the model is told there is no location and is told to
              ask you rather than guess.
            </p>
          </>
        ) : (
          <p className="text-small leading-6 text-zinc-500">
            Location is switched off on the server, so it cannot work out where you are. Every
            other capability is unaffected.
          </p>
        )}
      </Section>

      <Section
        title="Uploaded documents and web pages"
        hint="The model reads whatever you attach and whatever it finds while searching, and text in either can try to instruct it. That is the main reason a command has to be shown to you before it runs."
      >
        <p className="text-small leading-6 text-zinc-500">
          Whether a command runs on its own or asks you first is set in the Permissions tab,
          the one you reached this panel from.
        </p>
      </Section>
    </>
  )
}
