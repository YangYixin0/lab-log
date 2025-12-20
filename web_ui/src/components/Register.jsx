/** 注册组件 */

import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export default function Register() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [publicKeyPem, setPublicKeyPem] = useState('')
  const [privateKeyPem, setPrivateKeyPem] = useState('')
  const [showPrivateKey, setShowPrivateKey] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [generatingKey, setGeneratingKey] = useState(true) // 初始为 true，表示正在生成
  const { register } = useAuth()
  const navigate = useNavigate()

  // 生成密钥对（使用 WebCrypto API）
  const generateKeyPair = async () => {
    setGeneratingKey(true)
    try {
      const keyPair = await window.crypto.subtle.generateKey(
        {
          name: 'RSA-OAEP',
          modulusLength: 2048,
          publicExponent: new Uint8Array([1, 0, 1]),
          hash: 'SHA-256'
        },
        true,
        ['encrypt', 'decrypt']
      )

      // 导出公钥为 PEM 格式
      const publicKey = await window.crypto.subtle.exportKey(
        'spki',
        keyPair.publicKey
      )
      const publicKeyArray = Array.from(new Uint8Array(publicKey))
      const publicKeyBase64 = btoa(String.fromCharCode(...publicKeyArray))
      const publicKeyPem = `-----BEGIN PUBLIC KEY-----\n${publicKeyBase64.match(/.{1,64}/g).join('\n')}\n-----END PUBLIC KEY-----`
      
      // 导出私钥为 PEM 格式（PKCS#8）
      const privateKey = await window.crypto.subtle.exportKey(
        'pkcs8',
        keyPair.privateKey
      )
      const privateKeyArray = Array.from(new Uint8Array(privateKey))
      const privateKeyBase64 = btoa(String.fromCharCode(...privateKeyArray))
      const privateKeyPem = `-----BEGIN PRIVATE KEY-----\n${privateKeyBase64.match(/.{1,64}/g).join('\n')}\n-----END PRIVATE KEY-----`
      
      setPublicKeyPem(publicKeyPem)
      setPrivateKeyPem(privateKeyPem)
      setShowPrivateKey(true)
    } catch (err) {
      console.error('生成密钥对失败:', err)
      setError('生成密钥对失败，请刷新页面重试')
    } finally {
      setGeneratingKey(false)
    }
  }

  // 自动生成密钥对（组件加载时）
  useEffect(() => {
    generateKeyPair()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 下载私钥文件
  const downloadPrivateKey = () => {
    if (!privateKeyPem) return
    
    const blob = new Blob([privateKeyPem], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `private_key_${username || 'user'}_${Date.now()}.pem`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')

    if (!password) {
      setError('密码是必填项')
      return
    }

    if (!publicKeyPem) {
      setError('密钥对生成中，请稍候...')
      return
    }

    setLoading(true)

    try {
      await register(username, password, publicKeyPem)
      navigate('/dashboard')
    } catch (err) {
      setError(err.response?.data?.detail || '注册失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: '500px', margin: '50px auto', padding: '20px' }}>
      <h2>注册</h2>
      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: '15px' }}>
          <label>
            用户名:
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              style={{ width: '100%', padding: '8px', marginTop: '5px' }}
            />
          </label>
        </div>
        
        <div style={{ marginBottom: '15px' }}>
          <label>
            密码:
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              style={{ width: '100%', padding: '8px', marginTop: '5px' }}
            />
          </label>
        </div>
        
        {generatingKey && (
          <div style={{ marginBottom: '15px', padding: '10px', backgroundColor: '#e7f3ff', borderRadius: '4px' }}>
            🔄 正在自动生成密钥对...
          </div>
        )}
        
        {!generatingKey && publicKeyPem && (
          <div style={{ marginBottom: '15px' }}>
            <div style={{ padding: '10px', backgroundColor: '#d4edda', borderRadius: '4px', fontSize: '14px', marginBottom: '10px' }}>
              ✅ 密钥对已自动生成，公钥将自动上传到服务器
            </div>
            
            <div style={{ padding: '10px', backgroundColor: '#f8f9fa', border: '1px solid #dee2e6', borderRadius: '4px', marginBottom: '10px' }}>
              <div style={{ marginBottom: '8px', fontWeight: 'bold', fontSize: '14px' }}>
                📋 公钥（将上传到服务器）：
              </div>
              <textarea
                value={publicKeyPem}
                readOnly
                rows="6"
                style={{ 
                  width: '100%', 
                  padding: '8px', 
                  fontFamily: 'monospace',
                  fontSize: '11px',
                  backgroundColor: '#fff',
                  border: '1px solid #ddd',
                  borderRadius: '4px',
                  resize: 'none'
                }}
              />
            </div>
            
            <div style={{ padding: '10px', backgroundColor: '#e7f3ff', border: '1px solid #b3d9ff', borderRadius: '4px', fontSize: '12px', color: '#004085' }}>
              <div style={{ marginBottom: '5px', fontWeight: 'bold' }}>
                🔐 密钥对生成方法：
              </div>
              <ul style={{ margin: '5px 0', paddingLeft: '20px' }}>
                <li>使用 <strong>WebCrypto API</strong> 在浏览器本地生成</li>
                <li>算法：<strong>RSA-OAEP</strong>（RSA 最优非对称加密填充）</li>
                <li>密钥长度：<strong>2048 位</strong></li>
                <li>哈希函数：<strong>SHA-256</strong></li>
                <li>格式：<strong>PEM</strong>（Privacy-Enhanced Mail）</li>
                <li>私钥格式：<strong>PKCS#8</strong></li>
              </ul>
              <div style={{ marginTop: '8px', fontSize: '11px', fontStyle: 'italic' }}>
                密钥对在您的浏览器中生成，私钥不会发送到服务器，请务必妥善保管。
              </div>
            </div>
          </div>
        )}
        
        {showPrivateKey && privateKeyPem && (
          <div style={{ 
            marginBottom: '15px', 
            padding: '15px', 
            backgroundColor: '#fff3cd', 
            border: '1px solid #ffc107',
            borderRadius: '4px'
          }}>
            <div style={{ marginBottom: '10px', fontWeight: 'bold', color: '#856404' }}>
              ⚠️ 重要：请立即保存私钥！
            </div>
            <div style={{ marginBottom: '10px', fontSize: '12px', color: '#856404' }}>
              私钥仅显示一次，关闭页面后将无法再次查看。请妥善保管，不要泄露给他人。公钥已自动上传到服务器。
            </div>
            <textarea
              value={privateKeyPem}
              readOnly
              rows="8"
              style={{ 
                width: '100%', 
                padding: '8px', 
                fontFamily: 'monospace',
                fontSize: '11px',
                backgroundColor: '#fff',
                border: '1px solid #ddd',
                borderRadius: '4px',
                marginBottom: '10px'
              }}
            />
            <div style={{ display: 'flex', gap: '10px' }}>
              <button
                type="button"
                onClick={downloadPrivateKey}
                style={{
                  padding: '8px 16px',
                  backgroundColor: '#007bff',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: 'pointer'
                }}
              >
                📥 下载私钥文件
              </button>
              <button
                type="button"
                onClick={() => {
                  navigator.clipboard.writeText(privateKeyPem)
                  alert('私钥已复制到剪贴板')
                }}
                style={{
                  padding: '8px 16px',
                  backgroundColor: '#6c757d',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: 'pointer'
                }}
              >
                📋 复制私钥
              </button>
            </div>
          </div>
        )}
        
        {error && (
          <div style={{ color: 'red', marginBottom: '15px' }}>{error}</div>
        )}
        
        <button
          type="submit"
          disabled={loading || generatingKey || !publicKeyPem}
          style={{
            width: '100%',
            padding: '10px',
            backgroundColor: loading || generatingKey || !publicKeyPem ? '#6c757d' : '#007bff',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: loading || generatingKey || !publicKeyPem ? 'not-allowed' : 'pointer'
          }}
        >
          {generatingKey ? '等待密钥生成...' : loading ? '注册中...' : '注册'}
        </button>
      </form>
      <div style={{ marginTop: '15px', textAlign: 'center' }}>
        <a href="/login">已有账号？登录</a>
      </div>
    </div>
  )
}
