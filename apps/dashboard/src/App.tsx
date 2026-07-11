import { useCallback, useEffect, useState } from 'react'
import './App.css'
import {
  createReferral,
  getHealth,
  getReferral,
  listReferrals,
  type Health,
  type NewReferral,
  type ReferralDetail,
  type ReferralSummary,
} from './api'

const POLL_MS = 4000

const SOURCES = [
  'inbound_call_provider',
  'inbound_call_family',
  'inbound_call_patient',
  'fax',
  'physician_referral',
  'snf_referral',
]

type Preset = 'accept' | 'pending' | 'decline' | 'needs'

const PRESETS: Record<Preset, Partial<NewReferral>> = {
  accept: {
    zip_code: '11201', payer: 'Medicare', plan: 'Medicare Part A',
    service_type: 'skilled_nursing', source: 'inbound_call_provider',
    provided_documents: ['physician_orders', 'face_to_face_encounter', 'homebound_certification'],
  },
  pending: {
    zip_code: '11201', payer: 'Medicare', plan: 'Medicare Part A',
    service_type: 'skilled_nursing', source: 'fax', provided_documents: ['physician_orders'],
  },
  decline: {
    zip_code: '90210', payer: 'Medicare', plan: 'Medicare Part A',
    service_type: 'skilled_nursing', source: 'inbound_call_provider', provided_documents: [],
  },
  needs: {
    zip_code: '11201', payer: 'Medicare', plan: '', service_type: '',
    source: 'inbound_call_family', provided_documents: [],
  },
}

function labelize(v: string): string {
  return v.replace(/_/g, ' ')
}

function Badge({ kind, value }: { kind: 'decision' | 'status'; value: string }) {
  return <span className={`badge badge-${kind}-${value}`}>{labelize(value)}</span>
}

function TimeAgo({ iso }: { iso: string }) {
  const d = new Date(iso)
  return <span title={d.toLocaleString()}>{d.toLocaleTimeString()}</span>
}

function NewReferralForm({ onCreated, onClose }: { onCreated: () => void; onClose: () => void }) {
  const [form, setForm] = useState<NewReferral>({
    referral_id: 'REF-NEW', source: 'inbound_call_provider', zip_code: '11201',
    payer: 'Medicare', plan: 'Medicare Part A', service_type: 'skilled_nursing',
    provided_documents: ['physician_orders', 'face_to_face_encounter', 'homebound_certification'],
    contact: { phone: '+15551110000', role: 'provider' },
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const set = (k: keyof NewReferral, v: unknown) => setForm((f) => ({ ...f, [k]: v }))
  const applyPreset = (p: Preset) => setForm((f) => ({ ...f, ...PRESETS[p] }))

  const submit = async () => {
    setBusy(true)
    setErr(null)
    try {
      await createReferral(form)
      onCreated()
      onClose()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>New referral</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="presets">
          <span>Presets:</span>
          {(['accept', 'pending', 'decline', 'needs'] as Preset[]).map((p) => (
            <button key={p} className="chip-btn" onClick={() => applyPreset(p)}>{p}</button>
          ))}
        </div>
        <div className="form-grid">
          <label>Referral ID<input value={form.referral_id}
            onChange={(e) => set('referral_id', e.target.value)} /></label>
          <label>Source
            <select value={form.source} onChange={(e) => set('source', e.target.value)}>
              {SOURCES.map((s) => <option key={s} value={s}>{labelize(s)}</option>)}
            </select>
          </label>
          <label>Zip code<input value={form.zip_code ?? ''}
            onChange={(e) => set('zip_code', e.target.value)} /></label>
          <label>Payer<input value={form.payer ?? ''}
            onChange={(e) => set('payer', e.target.value)} /></label>
          <label>Plan<input value={form.plan ?? ''}
            onChange={(e) => set('plan', e.target.value)} /></label>
          <label>Service type<input value={form.service_type ?? ''}
            onChange={(e) => set('service_type', e.target.value)} /></label>
          <label className="wide">Provided documents (comma-separated)
            <input value={(form.provided_documents ?? []).join(', ')}
              onChange={(e) => set('provided_documents',
                e.target.value.split(',').map((s) => s.trim()).filter(Boolean))} />
          </label>
          <label className="wide">Contact phone
            <input value={(form.contact.phone as string) ?? ''}
              onChange={(e) => set('contact', { ...form.contact, phone: e.target.value })} />
          </label>
        </div>
        {err && <div className="error-inline">{err}</div>}
        <div className="modal-foot">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={submit} disabled={busy}>
            {busy ? 'Running…' : 'Run through orchestrator'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="detail-section">
      <h3>{title}{note && <span className="section-note">{note}</span>}</h3>
      {children}
    </section>
  )
}

function Detail({ id }: { id: string }) {
  const [detail, setDetail] = useState<ReferralDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setDetail(null)
    setErr(null)
    getReferral(id)
      .then((d) => alive && setDetail(d))
      .catch((e) => alive && setErr(e instanceof Error ? e.message : String(e)))
    return () => { alive = false }
  }, [id])

  if (err) return <div className="error-inline">{err}</div>
  if (!detail) return <div className="muted pad">Loading referral…</div>

  const ins = detail.insurance_data as { payer?: string; plan?: string }
  const clin = detail.clinical_data as { diagnosis_code?: string; service_type?: string }
  const pat = detail.patient_data as { zip_code?: string; contact?: { phone?: string; role?: string } }
  const src = detail.referral_source as { external_ref?: string }
  const fu = detail.followup

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-ref">{src.external_ref ?? detail.id.slice(0, 8)}</div>
          <div className="detail-sub">{labelize(detail.source)} · <TimeAgo iso={detail.created_at} /></div>
        </div>
        <div className="detail-badges">
          <Badge kind="decision" value={detail.eligibility_decision} />
          <Badge kind="status" value={detail.status} />
          {detail.human_review_required && <span className="chip-review">human review</span>}
        </div>
      </div>

      <Section title="Eligibility">
        {detail.eligibility_reasons.length
          ? <ul className="reasons">{detail.eligibility_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
          : <div className="muted">No reasons recorded.</div>}
      </Section>

      <Section title="Gaps / missing documents">
        {detail.gaps.length
          ? <ul className="gaps">{detail.gaps.map((g, i) =>
              <li key={i}><code>{g.item}</code> <span className="muted">— {labelize(g.action)}</span></li>)}</ul>
          : <div className="muted">None — nothing outstanding.</div>}
      </Section>

      <Section title="Follow-up action">
        {fu
          ? <div className="fu">
              <span className="badge badge-fu">{labelize(fu.type ?? 'none')}</span>
              <span className="muted"> {labelize(fu.intent ?? '')}</span>
              {fu.scheduled_at && <div className="muted">scheduled: {new Date(fu.scheduled_at).toLocaleString()}</div>}
              {fu.message && <div className="fu-msg">{fu.message}</div>}
            </div>
          : <div className="muted">No follow-up yet.</div>}
      </Section>

      <Section title="Pipeline trace">
        <div className="trace">{detail.trace.map((n, i) =>
          <span key={i} className="trace-node">{labelize(n)}</span>)}</div>
      </Section>

      <Section title="Referral facts">
        <dl className="facts">
          <dt>Insurance</dt><dd>{ins.payer ?? '—'} / {ins.plan ?? '—'}</dd>
          <dt>Clinical</dt><dd>{clin.diagnosis_code ?? '—'} · {clin.service_type ? labelize(clin.service_type) : '—'}</dd>
          <dt>Zip</dt><dd>{pat.zip_code ?? '—'}</dd>
          <dt>Contact</dt><dd>{pat.contact?.phone ?? '—'} {pat.contact?.role ? `(${pat.contact.role})` : ''}</dd>
        </dl>
      </Section>

      <Section title="Extraction confidence" note="pending — Document Pipeline (Task 2)">
        <div className="placeholder">Per-field OCR/vision confidence scores will appear here once the document pipeline lands.</div>
      </Section>

      <Section title="Call transcript" note="pending — Voice Agent (Task 1)">
        <div className="placeholder">Twilio call transcripts will appear here once the voice agent lands.</div>
      </Section>

      <Section title="Caregiver matches">
        {detail.matched_caregivers.length
          ? <pre>{JSON.stringify(detail.matched_caregivers, null, 2)}</pre>
          : <div className="placeholder">Eligibility confirms availability; the specific matched-caregiver list is not populated yet.</div>}
      </Section>
    </div>
  )
}

export default function App() {
  const [referrals, setReferrals] = useState<ReferralSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [list, h] = await Promise.all([listReferrals(), getHealth().catch(() => null)])
      setReferrals(list)
      setHealth(h)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, POLL_MS)
    return () => clearInterval(t)
  }, [refresh])

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">IntakeAI</span>
          <span className="brand-sub">Intake Dashboard</span>
        </div>
        <div className="topbar-right">
          {health && (
            <span className={`health ${health.database.ok ? 'health-ok' : 'health-bad'}`}>
              {health.database.ok ? 'DB connected' : 'DB unreachable'}
            </span>
          )}
          <button className="btn-primary" onClick={() => setShowForm(true)}>+ New referral</button>
        </div>
      </header>

      {error && (
        <div className="error-banner">
          Backend/API unreachable: {error}
          <div className="error-hint">Start Docker, run <code>scripts/seed_databases.sh</code>, then
            <code> uvicorn backend.api.app:app --port 8010</code>.</div>
        </div>
      )}

      <main className="layout">
        <div className="list-pane">
          <div className="list-head">
            <span>Referrals</span>
            {referrals && <span className="count">{referrals.length}</span>}
          </div>
          {referrals === null && !error && <div className="muted pad">Loading…</div>}
          {referrals?.length === 0 && (
            <div className="empty">
              <p>No referrals yet.</p>
              <p className="muted">Click “New referral”, or run
                <code> python -m backend.api.seed_referrals</code>.</p>
            </div>
          )}
          {referrals?.map((r) => (
            <button
              key={r.id}
              className={`ref-row ${selectedId === r.id ? 'selected' : ''}`}
              onClick={() => setSelectedId(r.id)}
            >
              <div className="ref-row-top">
                <span className="ref-name">{r.external_ref ?? r.id.slice(0, 8)}</span>
                <TimeAgo iso={r.created_at} />
              </div>
              <div className="ref-row-mid">
                <Badge kind="decision" value={r.decision} />
                <Badge kind="status" value={r.status} />
                {r.human_review_required && <span className="chip-review">review</span>}
              </div>
              <div className="ref-row-bot muted">
                {labelize(r.source)}{r.gap_count > 0 ? ` · ${r.gap_count} gap${r.gap_count > 1 ? 's' : ''}` : ''}
              </div>
            </button>
          ))}
        </div>

        <div className="detail-pane">
          {selectedId
            ? <Detail id={selectedId} />
            : <div className="muted pad">Select a referral to see its details.</div>}
        </div>
      </main>

      {showForm && <NewReferralForm onCreated={refresh} onClose={() => setShowForm(false)} />}
    </div>
  )
}
