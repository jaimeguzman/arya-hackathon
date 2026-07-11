import { useEffect, useRef, useState } from 'react'
import { fetchActiveCalls } from '../api/client'

function durationLabel(startedAt, now) {
  if (!startedAt) return '0:00'
  const sec = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000))
  const m = Math.floor(sec / 60)
  const s = String(sec % 60).padStart(2, '0')
  return `${m}:${s}`
}

export default function LiveCallMonitor({ twilioPhone, embedded, initialCalls }) {
  const [calls, setCalls] = useState(initialCalls || [])
  const [now, setNow] = useState(Date.now())
  const prev = useRef('')

  useEffect(() => {
    if (initialCalls) setCalls(initialCalls)
  }, [initialCalls])

  useEffect(() => {
    let alive = true
    const pollMs = calls.length ? 2000 : 5000
    const load = async () => {
      try {
        const data = await fetchActiveCalls()
        const raw = JSON.stringify(data)
        if (raw !== prev.current) {
          prev.current = raw
          if (alive) setCalls(Array.isArray(data) ? data : [])
        }
      } catch (e) {
        console.error(e)
      }
    }
    load()
    const id = setInterval(load, pollMs)
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => {
      alive = false
      clearInterval(id)
      clearInterval(t)
    }
  }, [calls.length])

  if (!calls.length) {
    if (embedded) return null
    return (
      <div className="rounded-lg bg-white p-8 text-center text-gray-600 shadow-sm">
        No active calls. Call {twilioPhone || 'the intake line'} to start an intake conversation.
      </div>
    )
  }

  return (
    <div className={`space-y-4 ${embedded ? '' : ''}`}>
      {!embedded && (
        <h2 className="text-lg font-semibold text-gray-900">Live call monitor</h2>
      )}
      {calls.map((c) => {
        const data = c.accumulated_data || {}
        const elig = c.eligibility_result
        return (
          <div
            key={c.call_sid}
            className="rounded-lg border border-green-200 bg-white p-4 shadow-sm"
          >
            <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
              <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-green-500" />
              <span className="font-medium">{c.caller_number || 'Unknown caller'}</span>
              <span className="text-gray-500">{c.direction || 'inbound'}</span>
              <span className="rounded bg-gray-100 px-2 py-0.5 text-xs">{c.mode || '…'}</span>
              <span className="font-mono text-gray-700">
                {durationLabel(c.started_at, now)}
              </span>
            </div>

            <div className="mb-3">
              <h4 className="mb-1 text-xs font-semibold uppercase text-gray-500">
                Live extraction
              </h4>
              <div className="flex flex-wrap gap-2">
                {Object.keys(data).length === 0 && (
                  <span className="text-xs text-gray-400">Waiting for fields…</span>
                )}
                {Object.entries(data).map(([k, v]) => (
                  <div
                    key={k}
                    className="animate-[fadeIn_0.4s_ease] rounded bg-green-50 px-2 py-1 text-xs text-green-900"
                  >
                    <span className="font-semibold">{k}:</span> {String(v)}
                  </div>
                ))}
              </div>
            </div>

            <div className="mb-3 text-sm">
              {elig ? (
                <div className="rounded bg-teal-50 px-3 py-2 text-teal-900">
                  Eligibility: <strong>{elig.decision}</strong>
                  {elig.voice_guidance ? ` · ${elig.voice_guidance}` : ''}
                </div>
              ) : (
                <div className="text-xs text-gray-500">
                  {Object.keys(data).length >= 3
                    ? 'Checking eligibility when ready…'
                    : 'Eligibility pending'}
                </div>
              )}
            </div>

            {(c.last_turns || []).length > 0 && (
              <div>
                <h4 className="mb-1 text-xs font-semibold uppercase text-gray-500">
                  Recent turns
                </h4>
                <ul className="space-y-1 text-xs text-gray-700">
                  {c.last_turns.map((t, i) => (
                    <li key={i}>
                      <span className="font-medium">{t.role}:</span> {t.content}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )
      })}
      <style>{`@keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }`}</style>
    </div>
  )
}
