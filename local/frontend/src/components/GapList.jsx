const PRI = {
  high: 'border-red-300 text-red-800 bg-red-50',
  critical: 'border-red-400 text-red-900 bg-red-50',
  medium: 'border-amber-300 text-amber-900 bg-amber-50',
  low: 'border-gray-200 text-gray-700 bg-white',
}

export default function GapList({ gaps }) {
  const list = Array.isArray(gaps) ? gaps : []
  if (!list.length) {
    return <p className="text-sm text-green-700">0 gaps</p>
  }
  return (
    <ul className="space-y-2">
      {list.map((g, i) => {
        const resolved = g.resolved || g.status === 'resolved'
        const pri = String(g.priority || 'medium').toLowerCase()
        return (
          <li
            key={`${g.field_name}-${i}`}
            className={`rounded border px-3 py-2 text-sm ${PRI[pri] || PRI.medium} ${resolved ? 'line-through opacity-60' : ''}`}
          >
            <div className="font-medium">
              {resolved ? '✓ ' : ''}
              {g.field_name || 'gap'}
            </div>
            <div className="text-xs mt-0.5">{g.reason || ''}</div>
            {(g.suggested_action || g.action) && (
              <div className="text-xs mt-1 opacity-80">{g.suggested_action || g.action}</div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
