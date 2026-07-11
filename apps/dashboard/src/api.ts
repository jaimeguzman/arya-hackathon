// Typed client for the IntakeAI dashboard API (proxied at /api -> backend :8010).

export type Decision = 'ACCEPT' | 'DECLINE' | 'NEEDS_MORE_INFO' | 'pending'
export type Status =
  | 'new'
  | 'processing'
  | 'pending_documents'
  | 'eligible'
  | 'accepted'
  | 'declined'
  | 'escalated'

export interface ReferralSummary {
  id: string
  external_ref: string | null
  source: string
  status: Status
  decision: Decision
  human_review_required: boolean
  gap_count: number
  created_at: string
}

export interface Gap {
  item: string
  status: string
  action: string
}

export interface FollowUp {
  type?: string
  intent?: string
  message?: string
  scheduled_at?: string | null
  attempt_number?: number
  terminal?: boolean
  target?: Record<string, unknown>
}

export interface ReferralDetail {
  id: string
  source: string
  status: Status
  urgency: string
  patient_data: Record<string, unknown>
  clinical_data: Record<string, unknown>
  insurance_data: Record<string, unknown>
  care_request: Record<string, unknown>
  referral_source: Record<string, unknown>
  extraction_confidence: Record<string, unknown>
  gaps: Gap[]
  eligibility_decision: Decision
  eligibility_reasons: string[]
  matched_caregivers: unknown[]
  escalated: boolean
  human_review_required: boolean
  followup: FollowUp | null
  trace: string[]
  created_at: string
  updated_at: string
}

export interface Health {
  status: string
  database: { ok: boolean; detail: string }
}

export interface NewReferral {
  referral_id: string
  source: string
  zip_code: string | null
  payer: string | null
  plan: string | null
  service_type: string | null
  provided_documents: string[]
  contact: Record<string, unknown>
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

export async function getHealth(): Promise<Health> {
  return jsonOrThrow<Health>(await fetch('/api/health'))
}

export async function listReferrals(): Promise<ReferralSummary[]> {
  return jsonOrThrow<ReferralSummary[]>(await fetch('/api/referrals'))
}

export async function getReferral(id: string): Promise<ReferralDetail> {
  return jsonOrThrow<ReferralDetail>(await fetch(`/api/referrals/${id}`))
}

export async function createReferral(payload: NewReferral): Promise<{ id: string }> {
  return jsonOrThrow<{ id: string }>(
    await fetch('/api/referrals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  )
}
