import { useState, useEffect } from 'react'
import axios from 'axios'
import { useAuth } from '../hooks/useAuth'

export default function Emergencies() {
  const { isAdmin } = useAuth()
  const [emergencies, setEmergencies] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('PENDING')

  const fetchEmergencies = async () => {
    try {
      setLoading(true)
      const response = await axios.get(`/api/emergencies/list?status=${filter}`, { withCredentials: true })
      setEmergencies(response.data)
    } catch (error) {
      console.error('获取紧急情况列表失败:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (isAdmin) {
      fetchEmergencies()
    }
  }, [isAdmin, filter])

  const handleResolve = async (id) => {
    try {
      await axios.post(`/api/emergencies/${id}/resolve`, {}, { withCredentials: true })
      fetchEmergencies()
    } catch (error) {
      alert('操作失败: ' + (error.response?.data?.detail || error.message))
    }
  }

  if (!isAdmin) {
    return <div style={{ padding: '20px' }}>无权访问</div>
  }

  return (
    <div style={{ padding: '40px', maxWidth: '1200px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '30px' }}>
        <h2 style={{ margin: 0, color: '#333' }}>紧急通知管理</h2>
        <div style={{ display: 'flex', gap: '10px' }}>
          <button
            onClick={() => setFilter('PENDING')}
            style={{
              padding: '8px 16px',
              backgroundColor: filter === 'PENDING' ? '#d32f2f' : '#f8f9fa',
              color: filter === 'PENDING' ? 'white' : '#333',
              border: '1px solid #ddd',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
          >
            待处理
          </button>
          <button
            onClick={() => setFilter('RESOLVED')}
            style={{
              padding: '8px 16px',
              backgroundColor: filter === 'RESOLVED' ? '#28a745' : '#f8f9fa',
              color: filter === 'RESOLVED' ? 'white' : '#333',
              border: '1px solid #ddd',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
          >
            已解决
          </button>
          <button
            onClick={() => { setFilter(''); fetchEmergencies(); }}
            style={{
              padding: '8px 16px',
              backgroundColor: filter === '' ? '#6c757d' : '#f8f9fa',
              color: filter === '' ? 'white' : '#333',
              border: '1px solid #ddd',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
          >
            全部
          </button>
        </div>
      </div>

      {loading ? (
        <div>加载中...</div>
      ) : emergencies.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '100px', backgroundColor: '#f8f9fa', borderRadius: '8px', color: '#666' }}>
          暂无紧急情况记录
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {emergencies.map((emg) => (
            <div
              key={emg.emergency_id}
              style={{
                backgroundColor: 'white',
                border: '1px solid #ddd',
                borderRadius: '8px',
                padding: '20px',
                boxShadow: '0 2px 4px rgba(0,0,0,0.05)',
                borderLeft: emg.status === 'PENDING' ? '5px solid #d32f2f' : '5px solid #28a745'
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '15px', marginBottom: '10px' }}>
                    <span style={{ 
                      fontSize: '14px', 
                      fontWeight: 'bold', 
                      color: emg.status === 'PENDING' ? '#d32f2f' : '#28a745',
                      padding: '2px 8px',
                      backgroundColor: emg.status === 'PENDING' ? '#ffebee' : '#e8f5e9',
                      borderRadius: '4px'
                    }}>
                      {emg.status === 'PENDING' ? '待处理' : '已解决'}
                    </span>
                    <span style={{ fontSize: '14px', color: '#666' }}>
                      ID: {emg.emergency_id}
                    </span>
                    <span style={{ fontSize: '14px', color: '#666' }}>
                      发现时间: {new Date(emg.created_at).toLocaleString()}
                    </span>
                  </div>
                  <h3 style={{ margin: '0 0 10px 0', color: '#333' }}>{emg.description}</h3>
                  <div style={{ fontSize: '14px', color: '#555' }}>
                    <p style={{ margin: '5px 0' }}><strong>视频时间:</strong> {new Date(emg.start_time).toLocaleTimeString()} - {new Date(emg.end_time).toLocaleTimeString()}</p>
                    <p style={{ margin: '5px 0' }}><strong>视频分段:</strong> {emg.segment_id}</p>
                    {emg.status === 'RESOLVED' && (
                      <p style={{ margin: '5px 0', color: '#28a745' }}><strong>解决时间:</strong> {new Date(emg.resolved_at).toLocaleString()}</p>
                    )}
                  </div>
                </div>
                {emg.status === 'PENDING' && (
                  <button
                    onClick={() => handleResolve(emg.emergency_id)}
                    style={{
                      padding: '10px 20px',
                      backgroundColor: '#28a745',
                      color: 'white',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      fontWeight: 'bold'
                    }}
                  >
                    标记为已解决
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
