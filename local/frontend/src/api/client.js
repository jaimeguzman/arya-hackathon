async function apiFetch(url, options = {}) {
  const res = await fetch(url, options)
  if (!res.ok) {
    let body = ''
    try {
      body = await res.text()
    } catch {
      body = ''
    }
    throw new Error(`${res.status}: ${body}`)
  }
  if (res.status === 204) return null
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/json')) return res.json()
  return res.text()
}

export async function fetchIntakeRecords({ status, limit } = {}) {
  const q = new URLSearchParams()
  if (status) q.set('status', status)
  if (limit != null) q.set('limit', String(limit))
  const qs = q.toString()
  return apiFetch(`/api/intake${qs ? `?${qs}` : ''}`)
}

export async function fetchIntakeRecord(id) {
  return apiFetch(`/api/intake/${id}`)
}

export async function fetchDocumentStatus(id) {
  return apiFetch(`/api/documents/${id}/status`)
}

export async function fetchDocumentExtraction(id) {
  return apiFetch(`/api/documents/${id}/extraction`)
}

export async function fetchDocumentsByIntake(intakeId) {
  return apiFetch(`/api/documents/by-intake/${intakeId}`)
}

export function fetchDocumentFileUrl(id) {
  return `/api/documents/${id}/file`
}

export async function fetchFollowUps(intakeId) {
  return apiFetch(`/api/followup/by-intake/${intakeId}`)
}

export async function fetchCaregivers() {
  return apiFetch('/api/caregivers')
}

export async function fetchActiveCalls() {
  return apiFetch('/api/calls/active')
}

export async function fetchCallsByIntake(intakeId) {
  return apiFetch(`/api/calls/by-intake/${intakeId}`)
}

export async function fetchHealth() {
  // CORS open on backend; absolute URL in Vite dev (proxy skips page GET /)
  const origin = import.meta.env.DEV ? 'http://localhost:8000' : ''
  return apiFetch(`${origin}/`)
}
