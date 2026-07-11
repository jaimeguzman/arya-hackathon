export function confidenceColor(score) {
  if (score == null || Number.isNaN(score)) return 'bg-gray-300'
  if (score >= 0.7) return 'bg-green-500'
  if (score >= 0.5) return 'bg-yellow-400'
  return 'bg-red-500'
}

export function confidenceBg(score) {
  if (score == null || Number.isNaN(score)) return ''
  if (score >= 0.7) return ''
  if (score >= 0.5) return 'bg-yellow-50'
  return 'bg-red-50'
}

export default function ConfidenceIndicator({ score }) {
  const s = score == null ? null : Number(score)
  const title = s == null ? 'n/a' : s.toFixed(2)
  return (
    <span
      title={`confidence: ${title}`}
      className={`inline-block h-2.5 w-2.5 rounded-full ${confidenceColor(s)}`}
    />
  )
}
