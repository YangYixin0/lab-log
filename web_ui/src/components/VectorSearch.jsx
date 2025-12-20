/** 向量搜索组件 */

import { useState } from 'react'
import client from '../api/client'

export default function VectorSearch() {
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(10)
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSearch = async (e) => {
    e.preventDefault()
    if (!query.trim()) {
      setError('请输入搜索查询')
      return
    }

    setLoading(true)
    setError('')
    setResults(null)

    try {
      const response = await client.post('/admin/vector-search', {
        query: query.trim(),
        limit: limit
      })
      setResults(response.data)
    } catch (err) {
      setError(err.response?.data?.detail || '搜索失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ padding: '20px' }}>
      <h2>向量搜索</h2>
      
      <div style={{ 
        marginBottom: '30px', 
        padding: '20px', 
        backgroundColor: '#f8f9fa', 
        borderRadius: '4px' 
      }}>
        <h3 style={{ marginTop: '0' }}>搜索说明</h3>
        <p style={{ marginBottom: '10px' }}>
          使用语义向量搜索功能，在日志数据中查找与查询文本语义相似的内容。
        </p>
        <ul style={{ marginBottom: '0', paddingLeft: '20px' }}>
          <li>搜索基于 Qwen text-embedding-v4 模型生成的 1024 维向量</li>
          <li>使用余弦距离计算相似度（距离越小，相似度越高）</li>
          <li>搜索结果按相似度从高到低排序</li>
        </ul>
      </div>

      <form onSubmit={handleSearch} style={{ marginBottom: '20px' }}>
        <div style={{ marginBottom: '15px' }}>
          <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
            搜索查询:
          </label>
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="例如：操作仪器、人员进入、操作手机等"
            rows="3"
            required
            style={{ 
              width: '100%', 
              padding: '10px', 
              fontSize: '14px',
              border: '1px solid #ddd',
              borderRadius: '4px',
              fontFamily: 'inherit'
            }}
          />
        </div>
        
        <div style={{ marginBottom: '15px' }}>
          <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
            返回结果数量:
          </label>
          <input
            type="number"
            value={limit}
            onChange={(e) => setLimit(Math.max(1, Math.min(50, parseInt(e.target.value) || 10)))}
            min="1"
            max="50"
            style={{ 
              padding: '8px', 
              fontSize: '14px',
              border: '1px solid #ddd',
              borderRadius: '4px',
              width: '100px'
            }}
          />
          <span style={{ marginLeft: '10px', color: '#666', fontSize: '14px' }}>
            (1-50)
          </span>
        </div>

        {error && (
          <div style={{ 
            color: 'red', 
            marginBottom: '15px', 
            padding: '10px',
            backgroundColor: '#ffe6e6',
            borderRadius: '4px'
          }}>
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          style={{
            padding: '10px 20px',
            backgroundColor: loading ? '#6c757d' : '#007bff',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: loading ? 'not-allowed' : 'pointer',
            fontSize: '16px',
            fontWeight: 'bold'
          }}
        >
          {loading ? '搜索中...' : '搜索'}
        </button>
      </form>

      {results && (
        <div>
          <div style={{ 
            marginBottom: '15px', 
            padding: '10px', 
            backgroundColor: '#d4edda', 
            borderRadius: '4px' 
          }}>
            <strong>查询:</strong> "{results.query}" | 
            <strong> 找到 {results.total} 个结果</strong>
          </div>

          <div style={{ overflowX: 'auto' }}>
            {results.results.map((result, idx) => (
              <div
                key={result.chunk_id}
                style={{
                  marginBottom: '20px',
                  padding: '15px',
                  backgroundColor: '#fff',
                  border: '1px solid #ddd',
                  borderRadius: '4px',
                  boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
                }}
              >
                <div style={{ 
                  display: 'flex', 
                  justifyContent: 'space-between', 
                  alignItems: 'center',
                  marginBottom: '10px'
                }}>
                  <div>
                    <strong style={{ fontSize: '16px' }}>
                      #{idx + 1} 分块 ID: {result.chunk_id}
                    </strong>
                  </div>
                  <div style={{ 
                    padding: '5px 10px', 
                    backgroundColor: '#007bff', 
                    color: 'white',
                    borderRadius: '4px',
                    fontSize: '14px'
                  }}>
                    距离: {result.distance.toFixed(6)}
                  </div>
                </div>
                
                <div style={{ marginBottom: '10px' }}>
                  <strong>文本内容:</strong>
                  <div style={{ 
                    marginTop: '5px', 
                    padding: '10px', 
                    backgroundColor: '#f8f9fa',
                    borderRadius: '4px',
                    fontSize: '14px',
                    lineHeight: '1.6'
                  }}>
                    {result.chunk_text}
                  </div>
                </div>
                
                <div style={{ 
                  display: 'flex', 
                  gap: '20px', 
                  fontSize: '13px',
                  color: '#666'
                }}>
                  <div>
                    <strong>时间范围:</strong> {result.start_time} - {result.end_time}
                  </div>
                  <div>
                    <strong>关联事件:</strong> {result.related_event_ids || '无'}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

