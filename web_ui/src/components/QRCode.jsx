/** 二维码展示组件 */

import { useState, useEffect } from 'react'
import client from '../api/client'
import { generateQRCodeSVG } from '../utils/qrcode'

export default function QRCode() {
  const [qrData, setQrData] = useState(null)
  const [qrSvg, setQrSvg] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const fetchQRCode = async () => {
      try {
        const response = await client.get('/users/me/qrcode')
        const data = response.data
        setQrData(data)
        
        // 生成二维码 SVG
        const svg = await generateQRCodeSVG(data.qrcode_data)
        setQrSvg(svg)
      } catch (err) {
        setError(err.response?.data?.detail || '获取二维码失败')
      } finally {
        setLoading(false)
      }
    }

    fetchQRCode()
  }, [])

  if (loading) {
    return <div>加载中...</div>
  }

  if (error) {
    return <div style={{ color: 'red' }}>{error}</div>
  }

  return (
    <div style={{ textAlign: 'center', padding: '20px' }}>
      <h3>我的二维码</h3>
      <div
        dangerouslySetInnerHTML={{ __html: qrSvg }}
        style={{ margin: '20px 0' }}
      />
      <div style={{ 
        marginTop: '20px', 
        padding: '15px', 
        backgroundColor: '#f8f9fa', 
        borderRadius: '4px',
        textAlign: 'left',
        maxWidth: '500px',
        margin: '20px auto'
      }}>
        <h4 style={{ marginTop: '0', marginBottom: '10px' }}>二维码说明</h4>
        <p style={{ marginBottom: '8px', fontSize: '14px' }}>
          此二维码包含以下信息：
        </p>
        <ul style={{ marginBottom: '8px', fontSize: '14px', paddingLeft: '20px' }}>
          <li><strong>用户 ID</strong>：您的唯一身份标识</li>
          <li><strong>公钥指纹</strong>：用于验证您的身份</li>
        </ul>
        <p style={{ marginBottom: '0', fontSize: '13px', color: '#666', fontStyle: 'italic' }}>
          视频采集端扫描此二维码后，可以验证您的身份并确认您有权访问相关数据。
        </p>
      </div>
    </div>
  )
}

