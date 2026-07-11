const STATUS_CLASSES = {
  new: 'bg-gray-200 text-gray-800',
  processing: 'bg-blue-100 text-blue-800 animate-pulse',
  pending_documents: 'bg-amber-100 text-amber-900',
  eligible: 'bg-teal-100 text-teal-800',
  accepted: 'bg-green-100 text-green-800',
  declined: 'bg-red-100 text-red-800',
  escalated: 'bg-purple-100 text-purple-800',
}

export default function StatusBadge({ status }) {
  const cls = STATUS_CLASSES[status] || 'bg-gray-100 text-gray-700'
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${cls}`}>
      {status || 'unknown'}
    </span>
  )
}
