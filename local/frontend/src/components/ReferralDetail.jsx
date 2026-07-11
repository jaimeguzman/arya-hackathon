import { useEffect, useRef, useState } from 'react'
import {
  fetchActiveCalls,
  fetchCallsByIntake,
  fetchDocumentExtraction,
  fetchDocumentFileUrl,
  fetchDocumentStatus,
  fetchDocumentsByIntake,
  fetchFollowUps,
  fetchIntakeRecord,
} from '../api/client'
import ConfidenceIndicator, { confidenceBg } from './ConfidenceIndicator'
import GapList from './GapList'
import StatusBadge from './StatusBadge'

const BUCKETS = [
  { key: 'patient_data', title: 'Patient Information' },
  { key: 'clinical_data', title: 'Clinical Data' },
  { key: 'physician_data', title: 'Physician Information' },
  { key: 'insurance_data', title: 'Insurance' },
  { key: 'care_request', title: 'Care Request' },
  { key: 'referral_source', title: 'Referral Source' },
]

function parseTranscript(text) {
  if (!text) return []
  return text.split('\n').filter(Boolean).map((line) => {
    const m = line.match(/^(user|model|caller|agent|assistant)\s*:\s*(.*)$/i)
    if (m) {
      const role = m[1].toLowerCase()
      const side = ['user', 'caller'].includes(role) ? 'caller' : 'agent'
      return { side, text: m[2] }
    }
    return { side: 'agent', text: line }
  })
}

function synthTimeline(record, followUps) {
  const events = []
  if (record?.created_at) {
    events.push({
      label: 'Referral received',
      at: record.created_at,
      detail: record.source,
    })
  }
  if (record?.status) {
    events.push({
      label: `Status: ${record.status}`,
      at: record.updated_at || record.created_at,
      detail: 'current',
      active: true,
    })
  }
  ;(followUps || []).forEach((f) => {
    events.push({
      label: f.type,
      at: f.executed_at || f.scheduled_at || f.created_at,
      detail: f.status,
    })
  })
  return events.sort((a, b) => new Date(a.at) - new Date(b.at))
}

function FieldRow({ label, value, score }) {
  return (
    <div className={`flex items-start justify-between gap-3 rounded px-2 py-1.5 ${confidenceBg(score)}`}>
      <div>
        <div className="text-xs text-gray-500">{label}</div>
        <div className="text-sm text-gray-900">
          {value == null || value === ''
            ? '—'
            : Array.isArray(value)
              ? value.join(', ')
              : String(value)}
        </div>
      </div>
      <ConfidenceIndicator score={score} />
    </div>
  )
}

export default function ReferralDetail({ intakeId, onBack }) {
  const [record, setRecord] = useState(null)
  const [followUps, setFollowUps] = useState([])
  const [calls, setCalls] = useState([])
  const [docs, setDocs] = useState([])
  const [docExtra, setDocExtra] = useState({})
  const [activeLive, setActiveLive] = useState(null)
  const [updatedAt, setUpdatedAt] = useState(Date.now())
  const [tick, setTick] = useState(0)
  const prev = useRef('')

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const [r, f, c, d, active] = await Promise.all([
          fetchIntakeRecord(intakeId),
          fetchFollowUps(intakeId).catch(() => []),
          fetchCallsByIntake(intakeId).catch(() => []),
          fetchDocumentsByIntake(intakeId).catch(() => []),
          fetchActiveCalls().catch(() => []),
        ])
        const live = (active || []).find((a) => String(a.intake_record_id) === String(intakeId))
        const raw = JSON.stringify({ r, f, c, d, live })
        if (raw !== prev.current) {
          prev.current = raw
          if (alive) {
            setRecord(r)
            setFollowUps(f || [])
            setCalls(c || [])
            setDocs(d || [])
            setActiveLive(live || null)
            setUpdatedAt(Date.now())
          }
        }
        for (const doc of d || []) {
          if (doc.processing_status && doc.processing_status !== 'complete') {
            const st = await fetchDocumentStatus(doc.id).catch(() => null)
            if (alive && st) {
              setDocExtra((prevX) => ({ ...prevX, [doc.id]: { status: st } }))
            }
          } else if (doc.processing_status === 'complete') {
            const ex = await fetchDocumentExtraction(doc.id).catch(() => null)
            if (alive && ex) {
              setDocExtra((prevX) => ({ ...prevX, [doc.id]: { extraction: ex } }))
            }
          }
        }
      } catch (e) {
        console.error(e)
      }
    }
    load()
    const id = setInterval(load, 3000)
    const fu = setInterval(() => {
      fetchFollowUps(intakeId).then((f) => setFollowUps(f || [])).catch(() => {})
    }, 5000)
    const t = setInterval(() => setTick((x) => x + 1), 1000)
    return () => {
      alive = false
      clearInterval(id)
      clearInterval(fu)
      clearInterval(t)
    }
  }, [intakeId])

  if (!record) {
    return <p className="text-sm text-gray-500">Loading referral…</p>
  }

  const conf = record.extraction_confidence || {}
  const docConf = {}
  Object.values(docExtra).forEach((x) => {
    const scores =
      x?.extraction?.confidence_scores ||
      x?.extraction?.extraction_result?.confidence_scores ||
      x?.status?.confidence_scores
    Object.assign(docConf, scores || {})
  })
  const scoreFor = (field) =>
    conf[field] != null ? Number(conf[field]) : docConf[field] != null ? Number(docConf[field]) : null
  const missingDocs = Array.isArray(record.missing_documents)
    ? record.missing_documents
    : []

  const timeline = synthTimeline(record, followUps)
  const pd = record.patient_data || {}
  const name = pd.patient_name || 'Pending...'
  const ago = Math.floor((Date.now() - updatedAt) / 1000)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <button type="button" onClick={onBack} className="text-sm text-blue-700 hover:underline">
          ← Back to pipeline
        </button>
        <p className="text-xs text-gray-500">Last updated: {ago}s ago</p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-semibold text-gray-900">{name}</h2>
        <StatusBadge status={record.status} />
      </div>

      <section className="rounded-lg bg-white p-4 shadow-sm">
        <h3 className="mb-3 text-sm font-semibold text-gray-800">Status timeline</h3>
        <ol className="space-y-2 border-l-2 border-gray-200 pl-4">
          {timeline.map((e, i) => (
            <li key={i} className={e.active ? 'text-gray-900' : 'text-gray-500'}>
              <div className="text-sm font-medium">{e.label}</div>
              <div className="text-xs">
                {e.at ? new Date(e.at).toLocaleString() : ''} {e.detail ? `· ${e.detail}` : ''}
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm">
        <h3 className="mb-3 text-sm font-semibold text-gray-800">Extracted data</h3>
        <div className="space-y-4">
          {BUCKETS.map((b) => {
            const data = record[b.key] || {}
            const entries = Object.entries(data)
            return (
              <div key={b.key}>
                <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
                  {b.title}
                </h4>
                {entries.length === 0 ? (
                  <p className="text-xs text-gray-400">No fields yet</p>
                ) : (
                  <div className="grid gap-1 sm:grid-cols-2">
                    {entries.map(([k, v]) => (
                      <FieldRow key={k} label={k} value={v} score={scoreFor(k)} />
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm">
        <h3 className="mb-3 text-sm font-semibold text-gray-800">Gaps</h3>
        <GapList gaps={record.gaps || []} />
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm">
        <h3 className="mb-3 text-sm font-semibold text-gray-800">Call transcripts</h3>
        {activeLive && (
          <div className="mb-4 rounded border border-green-200 bg-green-50 p-3">
            <div className="mb-2 flex items-center gap-2 text-sm font-medium text-green-800">
              <span className="h-2 w-2 animate-pulse rounded-full bg-green-500" />
              Active call · {activeLive.mode} · {activeLive.caller_number}
            </div>
            <pre className="whitespace-pre-wrap text-xs text-gray-700">
              {JSON.stringify(activeLive.accumulated_data || {}, null, 2)}
            </pre>
          </div>
        )}
        {!calls.length && !activeLive && (
          <p className="text-sm text-gray-500">No calls yet</p>
        )}
        {calls.map((c) => (
          <div key={c.id} className="mb-4 border-b border-gray-100 pb-4 last:border-0">
            <div className="mb-2 text-xs text-gray-500">
              {c.direction} · {c.mode} · {c.caller_number || '—'} · {c.status} ·{' '}
              {c.duration_seconds != null ? `${c.duration_seconds}s` : ''}
            </div>
            <div className="space-y-1">
              {parseTranscript(c.transcript).map((line, i) => (
                <div
                  key={i}
                  className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                    line.side === 'caller'
                      ? 'bg-gray-100 text-gray-900'
                      : 'ml-auto bg-blue-50 text-blue-900'
                  }`}
                >
                  {line.text}
                </div>
              ))}
            </div>
          </div>
        ))}
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm">
        <h3 className="mb-3 text-sm font-semibold text-gray-800">Eligibility</h3>
        {!record.eligibility_decision ? (
          <div className="text-sm text-gray-600">
            Eligibility check pending — awaiting sufficient data
            <ul className="mt-2 list-disc pl-5 text-xs">
              {!pd.zip_code && <li>zip_code</li>}
              {!(record.insurance_data || {}).payer_name && <li>insurance payer</li>}
              {!(record.clinical_data || {}).icd_codes &&
                !(record.clinical_data || {}).primary_diagnosis && <li>diagnosis / ICD</li>}
            </ul>
          </div>
        ) : (
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <StatusBadge
                status={
                  {
                    accept: 'accepted',
                    accepted: 'accepted',
                    decline: 'declined',
                    declined: 'declined',
                    eligible: 'eligible',
                    escalate: 'escalated',
                    escalated: 'escalated',
                  }[String(record.eligibility_decision).toLowerCase()] ||
                  String(record.eligibility_decision).toLowerCase()
                }
              />
              <span className="text-lg font-semibold">{record.eligibility_decision}</span>
            </div>
            <ul className="mb-3 list-disc pl-5 text-sm text-gray-700">
              {(record.eligibility_reasons || []).map((r, i) => (
                <li key={i}>{typeof r === 'string' ? r : r.message || JSON.stringify(r)}</li>
              ))}
            </ul>
            {missingDocs.length > 0 && (
              <div className="mb-3 rounded bg-amber-50 px-3 py-2 text-sm text-amber-900">
                <div className="font-medium">Missing documents / prior auth</div>
                <ul className="mt-1 list-disc pl-5 text-xs">
                  {missingDocs.map((d, i) => (
                    <li key={i}>{typeof d === 'string' ? d : JSON.stringify(d)}</li>
                  ))}
                </ul>
              </div>
            )}
            <h4 className="text-xs font-semibold uppercase text-gray-500">Matched caregivers</h4>
            <ul className="mt-1 space-y-1 text-sm">
              {(record.matched_caregivers || []).map((cg, i) => (
                <li key={i}>
                  {cg.name || cg.caregiver_name || 'Caregiver'} · {cg.type || cg.caregiver_type || ''}{' '}
                  {cg.score != null ? `· score ${cg.score}` : ''}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="rounded-lg bg-white p-4 shadow-sm">
        <h3 className="mb-3 text-sm font-semibold text-gray-800">Documents</h3>
        {!docs.length ? (
          <p className="text-sm text-gray-500">No linked documents</p>
        ) : (
          <ul className="space-y-3">
            {docs.map((d) => {
              const extra = docExtra[d.id] || {}
              const st = extra.status
              const pages = extra.extraction?.pages || []
              return (
                <li key={d.id} className="border-b border-gray-100 pb-3 text-sm">
                  <div className="font-medium">{d.file_name}</div>
                  <div className="text-xs text-gray-500">
                    {d.processing_status}
                    {st?.current_layer != null ? ` · layer ${st.current_layer}` : ''}
                  </div>
                  <a
                    className="text-xs text-blue-700 hover:underline"
                    href={fetchDocumentFileUrl(d.id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Download PDF
                  </a>
                  {pages.length > 0 && (
                    <ul className="mt-1 text-xs text-gray-600">
                      {pages.map((p) => (
                        <li key={p.page_number}>
                          Page {p.page_number}: {p.classification || '—'} ·{' '}
                          {p.extraction_path || '—'}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>
      <span className="hidden">{tick}</span>
    </div>
  )
}
