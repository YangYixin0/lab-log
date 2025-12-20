/** 导航栏组件 */

import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useNavigate } from 'react-router-dom'

export default function Navbar() {
  const { user, logout, isAdmin } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  if (!user) {
    return null
  }

  return (
    <nav style={{
      backgroundColor: '#343a40',
      color: 'white',
      padding: '0 20px',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      minHeight: '60px',
      boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '30px' }}>
        <div style={{ fontSize: '20px', fontWeight: 'bold' }}>
          Lab Log System
        </div>
        <div style={{ display: 'flex', gap: '20px' }}>
          <Link
            to="/dashboard"
            style={{
              color: location.pathname === '/dashboard' ? '#ffc107' : 'white',
              textDecoration: 'none',
              padding: '10px 15px',
              borderRadius: '4px',
              backgroundColor: location.pathname === '/dashboard' ? 'rgba(255, 255, 255, 0.1)' : 'transparent',
              transition: 'all 0.3s'
            }}
          >
            用户中心
          </Link>
          {isAdmin && (
            <>
              <Link
                to="/database"
                style={{
                  color: location.pathname === '/database' ? '#ffc107' : 'white',
                  textDecoration: 'none',
                  padding: '10px 15px',
                  borderRadius: '4px',
                  backgroundColor: location.pathname === '/database' ? 'rgba(255, 255, 255, 0.1)' : 'transparent',
                  transition: 'all 0.3s'
                }}
              >
                查看数据库
              </Link>
              <Link
                to="/vector-search"
                style={{
                  color: location.pathname === '/vector-search' ? '#ffc107' : 'white',
                  textDecoration: 'none',
                  padding: '10px 15px',
                  borderRadius: '4px',
                  backgroundColor: location.pathname === '/vector-search' ? 'rgba(255, 255, 255, 0.1)' : 'transparent',
                  transition: 'all 0.3s'
                }}
              >
                向量搜索
              </Link>
            </>
          )}
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
        <div style={{ fontSize: '14px' }}>
          <span style={{ color: '#adb5bd' }}>用户：</span>
          <strong>{user.username}</strong>
          {isAdmin && (
            <span style={{ 
              marginLeft: '10px', 
              padding: '2px 8px', 
              backgroundColor: '#ffc107', 
              color: '#000',
              borderRadius: '3px',
              fontSize: '12px',
              fontWeight: 'bold'
            }}>
              ADMIN
            </span>
          )}
        </div>
        <button
          onClick={handleLogout}
          style={{
            padding: '8px 16px',
            backgroundColor: '#dc3545',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontSize: '14px',
            transition: 'background-color 0.3s'
          }}
          onMouseOver={(e) => e.target.style.backgroundColor = '#c82333'}
          onMouseOut={(e) => e.target.style.backgroundColor = '#dc3545'}
        >
          登出
        </button>
      </div>
    </nav>
  )
}

