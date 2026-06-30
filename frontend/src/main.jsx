import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import './index.css'
import './App.css'
import Layout from './components/Layout.jsx'
import ProgramsPage from './pages/ProgramsPage.jsx'
import ProgramDetailPage from './pages/ProgramDetailPage.jsx'
import ScopeDetailPage from './pages/ScopeDetailPage.jsx'
import ScopeSubdomainsPage from './pages/ScopeSubdomainsPage.jsx'
import ScopeContentPage from './pages/ScopeContentPage.jsx'
import ScopeScansPage from './pages/ScopeScansPage.jsx'

const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <ProgramsPage /> },
      { path: 'programs/:programId', element: <ProgramDetailPage /> },
      { path: 'scopes/:scopeId', element: <ScopeDetailPage /> },
      { path: 'scopes/:scopeId/subdomains', element: <ScopeSubdomainsPage /> },
      { path: 'scopes/:scopeId/content', element: <ScopeContentPage /> },
      { path: 'scopes/:scopeId/scans', element: <ScopeScansPage /> },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
])

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)
