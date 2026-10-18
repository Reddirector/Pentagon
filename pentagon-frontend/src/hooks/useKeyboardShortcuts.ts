import { useEffect } from 'react'
import { toggleSidebarCollapsed } from '../lib/preferences'

export interface UseKeyboardShortcutsOptions {
  active: boolean
  onTogglePalette: () => void
  onNewThread: () => void
  onJumpToMessage: (offset: number) => void
  onFocusComposer: () => void
}

/**
 * The global keyboard shortcuts.
 *
 * ⌘K / Ctrl+K toggles the command palette. Escape closes it. Alt+Arrow walks
 * assistant messages. `/` focuses the composer. ⌘⇧O opens a new thread.
 * ⌘B folds the sidebar away to an icon rail (ignored on a phone, where the
 * sidebar is already a full-width drawer).
 */
export function useKeyboardShortcuts(options: UseKeyboardShortcutsOptions): void {
  useEffect(() => {
    const { active, onTogglePalette, onNewThread, onJumpToMessage, onFocusComposer } = options
    function onKeyDown(event: globalThis.KeyboardEvent) {
      const meta = event.metaKey || event.ctrlKey
      if (meta && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        onTogglePalette()
        return
      }
      if (event.key === 'Escape') {
        // Escape also closes the palette from any other surface; the palette
        // is the listener that consumes it there, so a close attempt here is
        // safe (and a no-op when nothing was open).
        document.dispatchEvent(new CustomEvent('pentagon:close-palette'))
        return
      }
      const target = event.target as HTMLElement | null
      const typing = target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA'
      if (event.altKey && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
        event.preventDefault()
        onJumpToMessage(event.key === 'ArrowDown' ? 1 : -1)
        return
      }
      if (event.key === '/' && !typing && active) {
        event.preventDefault()
        onFocusComposer()
        return
      }
      if (meta && event.shiftKey && event.key.toLowerCase() === 'o') {
        event.preventDefault()
        onNewThread()
        return
      }
      // ⌘B / Ctrl+B folds the sidebar away to an icon rail.
      if (meta && !event.shiftKey && event.key.toLowerCase() === 'b') {
        if (window.matchMedia('(min-width: 768px)').matches) {
          event.preventDefault()
          toggleSidebarCollapsed()
        }
        return
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [options])
}
