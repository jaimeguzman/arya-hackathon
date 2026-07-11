import { useEffect, useState } from 'react'
import { fetchHealth } from './api/client'
import IntakePipeline from './components/IntakePipeline'
import LiveCallMonitor from './components/LiveCallMonitor'
import ReferralDetail from './components/ReferralDetail'

const TWILIO_PHONE = import.meta.env.VITE_TWILIO_PHONE || ''

export default function App() {
  const [currentView, setCurrentView] = useState('pipeline')
  const [selectedRecordId, setSelectedRecordId] = useState(null)
  const [healthy, setHealthy] = useState(null)

  useEffect(() => {
    let alive = true
    const ping = async () => {
      try {
        await fetchHealth()
        if (alive) setHealthy(true)
      } catch {
        if (alive) setHealthy(false)
      }
    }
    ping()
    const id = setInterval(ping, 5000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])

  useEffect(() => {
    window.scrollTo(0, 0)
  }, [currentView, selectedRecordId])

  const goDetail = (id) => {
    setSelectedRecordId(id)
    setCurrentView('detail')
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-4">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">IntakeAI</h1>
            <p className="text-xs text-gray-500">Demo dashboard — read only</p>
          </div>
          <div className="text-center">
            <div className="text-xs uppercase tracking-wide text-gray-500">Call the intake line</div>
            <div className="text-lg font-semibold text-gray-900">
              {TWILIO_PHONE || 'Set VITE_TWILIO_PHONE'}
            </div>
          </div>
          <div className="flex items-center gap-4">
            <nav className="flex gap-2 text-sm">
              <button
                type="button"
                className={`rounded px-3 py-1 ${currentView === 'pipeline' ? 'bg-gray-900 text-white' : 'text-gray-700 hover:bg-gray-100'}`}
                onClick={() => setCurrentView('pipeline')}
              >
                Pipeline
              </button>
              <button
                type="button"
                className={`rounded px-3 py-1 ${currentView === 'monitor' ? 'bg-gray-900 text-white' : 'text-gray-700 hover:bg-gray-100'}`}
                onClick={() => setCurrentView('monitor')}
              >
                Live calls
              </button>
            </nav>
            <div className="flex items-center gap-2 text-xs text-gray-600">
              <span
                className={`h-2.5 w-2.5 rounded-full ${healthy ? 'bg-green-500' : healthy === false ? 'bg-red-500' : 'bg-gray-300'}`}
              />
              API
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8">
        {currentView === 'pipeline' && (
          <IntakePipeline twilioPhone={TWILIO_PHONE} onSelect={goDetail} />
        )}
        {currentView === 'detail' && selectedRecordId && (
          <ReferralDetail
            intakeId={selectedRecordId}
            onBack={() => setCurrentView('pipeline')}
          />
        )}
        {currentView === 'monitor' && (
          <LiveCallMonitor twilioPhone={TWILIO_PHONE} />
        )}
      </main>
    </div>
  )
}
