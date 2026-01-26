/** 主应用组件 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import Login from './components/Login'
import Register from './components/Register'
import UserDashboard from './components/UserDashboard'
import AdminDashboard from './components/AdminDashboard'
import VectorSearch from './components/VectorSearch'
import Emergencies from './components/Emergencies'
import Navbar from './components/Navbar'

function PrivateRoute({ children, requireAdmin = false }) {
  const { user, loading } = useAuth()

  if (loading) {
    return <div>加载中...</div>
  }

  if (!user) {
    return <Navigate to="/login" />
  }

  if (requireAdmin && user.role !== 'admin') {
    return <Navigate to="/dashboard" />
  }

  return children
}

function App() {
  return (
    <BrowserRouter>
      <div style={{ minHeight: '100vh', backgroundColor: '#f5f5f5' }}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route
            path="/dashboard"
            element={
              <PrivateRoute>
                <>
                  <Navbar />
                  <UserDashboard />
                </>
              </PrivateRoute>
            }
          />
          <Route
            path="/database"
            element={
              <PrivateRoute requireAdmin>
                <>
                  <Navbar />
                  <AdminDashboard />
                </>
              </PrivateRoute>
            }
          />
          <Route
            path="/vector-search"
            element={
              <PrivateRoute requireAdmin>
                <>
                  <Navbar />
                  <VectorSearch />
                </>
              </PrivateRoute>
            }
          />
          <Route
            path="/emergencies"
            element={
              <PrivateRoute requireAdmin>
                <>
                  <Navbar />
                  <Emergencies />
                </>
              </PrivateRoute>
            }
          />
          <Route path="/" element={<Navigate to="/dashboard" />} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}

export default App

