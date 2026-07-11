import { useEffect, useRef, useState } from 'react'
import { fetchActiveCalls, fetchIntakeRecords } from '../api/client'
import ConfidenceIndicator from './ConfidenceIndicator'
import LiveCallMonitor from './LiveCallMonitor'
import StatusBadge from './StatusBadge'

function relativeTime(iso) {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000))
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`
  return `${Math.floor(sec / 3600)} hour ago`
}

function sourceLabel(source) {
  const s = source || ''
  if (s.includes('fax') || s.includes('physician') || s.includes('snf')) {
    return { icon: '📄', label: 'Fax / document', sub: s }
  }
  if (s.includes('family')) return { icon: '📞', label: 'Inbound call', sub: 'family' }
  if (s.includes('patient')) return { icon: '📞', label: 'Inbound call', sub: 'patient' }
  if (s.includes('provider') || s.includes('call')) {
    return { icon: '📞', label: 'Inbound call', sub: 'provider' }
  }
  return { icon: '•', label: s || 'unknown', sub: '' }
}

function avgConfidence(conf) {
  const vals = Object.values(conf || {}).map(Number).filter((n) => !Number.isNaN(n))
  if (!vals.length) return null
  return vals.reduce((a, b) => a + b, 0) / vals.length
}

export default function IntakePipeline({ twilioPhone, onSelect }) {
  const [records, setRecords] = useState([])
  const [activeCalls, setActiveCalls] = useState([])
  const [updatedAt, setUpdatedAt] = useState(Date.now())
  const [tick, setTick] = useState(0)
  const prev = useRef('')

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const [list, calls] = await Promise.all([
          fetchIntakeRecords({ limit: 50 }),
          fetchActiveCalls().catch(() => []),
        ])
        const raw = JSON.stringify({ list, calls })
        if (raw !== prev.current) {
          prev.current = raw
          if (alive) {
            setRecords(Array.isArray(list) ? list : list?.items || [])
            setActiveCalls(Array.isArray(calls) ? calls : [])
            setUpdatedAt(Date.now())
          }
        }
      } catch (e) {
        console.error(e)
      }
    }
    load()
    const id = setInterval(load, 3000)
    const t = setInterval(() => setTick((x) => x + 1), 1000)
    return () => {
      alive = false
      clearInterval(id)
      clearInterval(t)
    }
  }, [])

  const activeIds = new Set(
    activeCalls.map((c) => c.intake_record_id).filter(Boolean)
  )
  const ago = Math.floor((Date.now() - updatedAt) / 1000)

  return (
    <div className="space-y-6">
      {activeCalls.length > 0 && (
        <LiveCallMonitor embedded twilioPhone={twilioPhone} initialCalls={activeCalls} />
      )}

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Intake pipeline</h2>
        <p className="text-xs text-gray-500">Last updated: {ago}s ago</p>
      </div>

      {!records.length ? (
        <div className="rounded-lg bg-white p-8 text-center text-gray-600 shadow-sm">
          <p>
            No active referrals. Call the intake line or upload a referral document to get
            started.
          </p>
          {twilioPhone && (
            <p className="mt-2 font-semibold text-gray-900">{twilioPhone}</p>
          )}
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg bg-white shadow-sm">
          <ul className="divide-y divide-gray-100">
            {records.map((r) => {
              const pd = r.patient_data || {}
              const clin = r.clinical_data || {}
              const ins = r.insurance_data || {}
              const name = pd.patient_name || 'Pending...'
              const src = sourceLabel(r.source)
              const gaps = r.gaps || []
              const conf = avgConfidence(r.extraction_confidence)
              const active = activeIds.has(String(r.id))
              return (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(r.id)}
                    className="flex w-full items-start gap-4 px-4 py-4 text-left hover:bg-gray-50"
                  >
                    <div className="w-10 text-center text-xl">{src.icon}</div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`font-medium ${name === 'Pending...' ? 'text-gray-400' : 'text-gray-900'}`}
                        >
                          {name}
                        </span>
                        <StatusBadge status={r.status} />
                        {active && (
                          <span className="inline-flex items-center gap-1 text-xs text-green-700">
                            <span className="h-2 w-2 animate-pulse rounded-full bg-green-500" />
                            live call
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 text-xs text-gray-500">
                        {src.label}
                        {src.sub ? ` · ${src.sub}` : ''} · {relativeTime(r.created_at)}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-3 text-xs text-gray-600">
                        <span className={!clin.primary_diagnosis && !clin.icd_codes ? 'text-gray-300' : ''}>
                          Dx: {clin.primary_diagnosis || (Array.isArray(clin.icd_codes) ? clin.icd_codes[0] : clin.icd_codes) || '—'}
                        </span>
                        <span className={!ins.payer_name ? 'text-gray-300' : ''}>
                          Payer: {ins.payer_name || '—'}
                        </span>
                        <span className={!pd.zip_code ? 'text-gray-300' : ''}>
                          Zip: {pd.zip_code || '—'}
                        </span>
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-2">
                      <ConfidenceIndicator score={conf} />
                      <span
                        className={`text-xs font-medium ${gaps.length ? 'text-amber-700' : 'text-green-700'}`}
                      >
                        {gaps.length} gaps
                      </span>
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}
      <span className="hidden">{tick}</span>
    </div>
  )
}
