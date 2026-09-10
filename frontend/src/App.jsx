import { useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { NavLink, Route, Routes, useLocation } from 'react-router-dom'

import { Alert } from './components/ui'
import {
  fetchAiHealth,
  fetchMetadata,
  selectAiHealth,
  selectOffline,
} from './features/meta/metaSlice'
import ComplaintDetailPage from './pages/ComplaintDetailPage'
import DashboardPage from './pages/DashboardPage'
import LogComplaintPage from './pages/LogComplaintPage'

const TITLES = {
  '/': ['Complaint Register', 'All customer complaints across API and FDF products'],
  '/log': ['Log Customer Complaint', 'AI-assisted intake, triage and risk assessment'],
}

function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">QA</div>
        <div className="brand-text">
          <strong>AIVOA QMS</strong>
          <span>Quality Management</span>
        </div>
      </div>

      <nav className="nav">
        <div className="nav-label">Complaints</div>
        <NavLink to="/" end>
          <span className="nav-icon">▤</span> Register
        </NavLink>
        <NavLink to="/log">
          <span className="nav-icon">＋</span> Log complaint
        </NavLink>

        <div className="nav-label">Other modules</div>
        <a
          href="#"
          onClick={(event) => event.preventDefault()}
          style={{ opacity: 0.45, cursor: 'default' }}
          title="Out of scope for this assignment"
        >
          <span className="nav-icon">◇</span> Deviations
        </a>
        <a
          href="#"
          onClick={(event) => event.preventDefault()}
          style={{ opacity: 0.45, cursor: 'default' }}
          title="Out of scope for this assignment"
        >
          <span className="nav-icon">◈</span> CAPA
        </a>
        <a
          href="#"
          onClick={(event) => event.preventDefault()}
          style={{ opacity: 0.45, cursor: 'default' }}
          title="Out of scope for this assignment"
        >
          <span className="nav-icon">◎</span> Change Control
        </a>
      </nav>

      <div className="sidebar-foot">
        Customer Complaint module
        <br />
        Demo build · not validated for GxP use
      </div>
    </aside>
  )
}

export default function App() {
  const dispatch = useDispatch()
  const location = useLocation()
  const aiHealth = useSelector(selectAiHealth)
  const offline = useSelector(selectOffline)

  useEffect(() => {
    dispatch(fetchMetadata())
    dispatch(fetchAiHealth())
  }, [dispatch])

  const [title, subtitle] = TITLES[location.pathname] ?? [
    'Complaint Record',
    'Customer complaint detail and AI assessment history',
  ]

  return (
    <div className="app">
      <Sidebar />

      <div className="main">
        <header className="topbar">
          <div className="topbar-title">
            <h1>{title}</h1>
            <span>{subtitle}</span>
          </div>
          <div className="topbar-actions">
            {aiHealth && (
              <span
                className={`badge badge-${aiHealth.llm_configured ? 'ai' : 'major'}`}
                title={aiHealth.message}
              >
                <span className="badge-dot" />
                {aiHealth.llm_configured ? 'Groq connected' : 'Rule-based mode'}
              </span>
            )}
          </div>
        </header>

        {offline && (
          <div style={{ padding: '14px 22px 0' }}>
            <Alert tone="danger" title="Backend unreachable">
              The API did not respond. Start it with{' '}
              <code>uvicorn app.main:app --reload</code> in the backend folder.
            </Alert>
          </div>
        )}

        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/log" element={<LogComplaintPage />} />
          <Route path="/complaints/:id" element={<ComplaintDetailPage />} />
        </Routes>
      </div>
    </div>
  )
}
