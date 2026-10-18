import { useEffect, useRef, useState } from 'react'
import { apiRequest } from '../api'
import {
  approvePendingApproval,
  denyPendingApproval,
  fetchPendingApprovals,
} from '../api'
import type { PendingApproval, PendingCommand } from './types/app'

export interface UsePendingApprovals {
  pending: PendingApproval[]
  error: string
  dismiss: (approval: PendingApproval, approved: boolean) => void
}

/**
 * Live approval-queue banner. Unlike the older command-only prompt, this reads
 * the new /api/pending-approvals endpoint, which surfaces the autonomy gate's
 * interrupt card (the always_ask / ask_first_time branch) anywhere in the app.
 *
 * The autonomy gate drives decisions across the whole session, so the
 * poller does not depend on any single queued item being the current turn:
 * it polls at a fixed interval in the background whether or not the
 * conversation is streaming, which is what makes an interrupt card appear
 * reliably even after a dialog or focus change steals the turn.
 */
export function usePendingApprovals(
  userId: string,
  conversationId: string | null,
  onResolved?: (approval: PendingApproval, approved: boolean) => void,
): UsePendingApprovals {
  const [pending, setPending] = useState<PendingApproval[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    if (!conversationId) return
    let cancelled = false
    const poll = async () => {
      if (cancelled) return
      try {
        const response = await fetchPendingApprovals(userId, conversationId)
        if (cancelled) return
        setPending(response.pending)
        setError('')
      } catch (cause) {
        if (cancelled) return
        setPending([])
        setError(cause instanceof Error ? cause.message : 'Could not load pending approvals.')
      }
    }
    void poll()
    const timer = window.setInterval(poll, 2000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [conversationId, userId])

  const dismiss = (approval: PendingApproval, approved: boolean) => {
    // Optimistically remove the card, so it does not wait for the network to
    // disappear from sight. If the resolve itself fails, refetching puts the
    // card back rather than silently eating the user's choice.
    setPending((current) => {
      const next = current.filter((item) => item.id !== approval.id)
      void (approved
        ? approvePendingApproval(approval.id, userId)
        : denyPendingApproval(approval.id, userId))
        .then(() => {
          onResolved?.(approval, approved)
        })
        .catch(() => {
          void fetchPendingApprovals(userId, conversationId ?? '')
            .then((response) => setPending(response.pending))
            .catch(() => setPending([]))
        })
      return next
    })
  }

  return { pending, error, dismiss }
}

export interface UsePendingCommandsOptions {
  /** Called when the window should answer a location permission prompt. */
  onLocationRequest: (requestId: string) => void
  /** A non-location command prompt the UI should render inline. */
  onShowable: (showable: PendingCommand) => void
  /** Every batch, so an enclosing hook can also track raw rows if it wants to. */
  onProgress: (batch: PendingCommand[]) => void
}

/**
 * The command-tool prompt (the older, per-conversation poller, kept distinct
 * from usePendingApprovals on purpose). This polls rather than waiting for a
 * server-sent event, and that is deliberate. The server blocks inside the
 * tool node until the decision arrives, so it has no opportunity to push
 * anything down the same stream while the question is outstanding — there is
 * nothing to emit from until the answer comes back. Polling the pending list
 * is also what makes a reload mid-request recoverable rather than stranded.
 */
export function usePendingCommands(
  userId: string,
  conversationId: string | null,
  enabled: boolean,
  options: UsePendingCommandsOptions,
): void {
  const answered = useRef<Set<string>>(new Set())
  // The callbacks are read through a ref so the poller's identity stays tied
  // to (userId, conversationId, enabled) rather than to the caller's latest
  // closure each render, which would otherwise re-run the interval for free.
  const callbacks = useRef({ ...options })
  useEffect(() => {
    callbacks.current = options
  }, [options])

  useEffect(() => {
    if (!conversationId || !enabled) return
    let cancelled = false
    const poll = async () => {
      if (cancelled) return
      try {
        const rows = await apiRequest<PendingCommand[]>(
          `/api/commands/pending?user_id=${encodeURIComponent(userId)}`
          + `&conversation_id=${encodeURIComponent(conversationId)}`,
        )
        if (cancelled || !rows.length) return
        callbacks.current.onProgress(rows)
        const locationRequest = rows.find((row) => row.kind === 'location')
        if (locationRequest && !answered.current.has(locationRequest.request_id)) {
          answered.current.add(locationRequest.request_id)
          callbacks.current.onLocationRequest(locationRequest.request_id)
        }
        const showable = rows.find((row) => row.kind !== 'location')
        if (!showable) return
        callbacks.current.onShowable(showable)
      } catch {
        /* The prompt is re-checked on the next tick; a failed poll is not fatal. */
      }
    }
    void poll()
    const timer = window.setInterval(poll, 1500)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [userId, conversationId, enabled])
}
