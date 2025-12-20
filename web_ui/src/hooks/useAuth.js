/** 认证状态管理 Hook */

import { useState, useEffect } from 'react'
import client from '../api/client'

export function useAuth() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  // 从 localStorage 恢复用户信息
  useEffect(() => {
    const savedUser = localStorage.getItem('user')
    if (savedUser) {
      try {
        setUser(JSON.parse(savedUser))
      } catch (e) {
        localStorage.removeItem('user')
      }
    }
    setLoading(false)
  }, [])

  // 登录
  const login = async (username, password, publicKeyPem) => {
    try {
      const response = await client.post('/auth/login', {
        username,
        password,
        public_key_pem: publicKeyPem
      })
      const userData = response.data
      setUser(userData)
      localStorage.setItem('user', JSON.stringify(userData))
      return userData
    } catch (error) {
      throw error
    }
  }

  // 注册
  const register = async (username, password, publicKeyPem) => {
    try {
      const response = await client.post('/auth/register', {
        username,
        password,
        public_key_pem: publicKeyPem
      })
      const userData = response.data
      setUser(userData)
      localStorage.setItem('user', JSON.stringify(userData))
      return userData
    } catch (error) {
      throw error
    }
  }

  // 登出
  const logout = async () => {
    try {
      await client.post('/auth/logout')
    } catch (error) {
      console.error('登出失败:', error)
    } finally {
      setUser(null)
      localStorage.removeItem('user')
    }
  }

  // 刷新用户信息
  const refreshUser = async () => {
    try {
      const response = await client.get('/users/me')
      const userData = response.data
      setUser(userData)
      localStorage.setItem('user', JSON.stringify(userData))
      return userData
    } catch (error) {
      setUser(null)
      localStorage.removeItem('user')
      throw error
    }
  }

  return {
    user,
    loading,
    login,
    register,
    logout,
    refreshUser,
    isAuthenticated: !!user,
    isAdmin: user?.role === 'admin'
  }
}

