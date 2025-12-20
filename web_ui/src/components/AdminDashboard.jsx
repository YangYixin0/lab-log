/** Admin 数据表格视图 */

import { useState, useEffect } from 'react'
import client from '../api/client'

export default function AdminDashboard() {
  const [tables, setTables] = useState([])
  const [selectedTable, setSelectedTable] = useState('')
  const [tableData, setTableData] = useState(null)
  const [page, setPage] = useState(1)
  const [limit] = useState(50)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // 获取表列表
  useEffect(() => {
    const fetchTables = async () => {
      try {
        const response = await client.get('/admin/tables')
        setTables(response.data.tables)
        if (response.data.tables.length > 0) {
          setSelectedTable(response.data.tables[0])
        }
      } catch (err) {
        setError(err.response?.data?.detail || '获取表列表失败')
      }
    }
    fetchTables()
  }, [])

  // 获取表数据
  const fetchTableData = async (tableName, pageNum) => {
    setLoading(true)
    setError('')
    try {
      const response = await client.get(`/admin/table/${tableName}`, {
        params: { page: pageNum, limit }
      })
      setTableData(response.data)
    } catch (err) {
      setError(err.response?.data?.detail || '获取表数据失败')
    } finally {
      setLoading(false)
    }
  }

  // 当选择的表改变时，重新获取数据
  useEffect(() => {
    if (selectedTable) {
      fetchTableData(selectedTable, 1)
      setPage(1)
    }
  }, [selectedTable])

  // 轮询刷新（每 10 秒）
  useEffect(() => {
    if (!selectedTable) return

    const interval = setInterval(() => {
      fetchTableData(selectedTable, page)
    }, 10000)  // 10 秒

    return () => clearInterval(interval)
  }, [selectedTable, page])

  const handlePageChange = (newPage) => {
    setPage(newPage)
    fetchTableData(selectedTable, newPage)
  }

  return (
    <div style={{ padding: '20px' }}>
      <h2>查看数据库</h2>
      
      <div style={{ marginBottom: '20px' }}>
        <label>
          选择表:
          <select
            value={selectedTable}
            onChange={(e) => setSelectedTable(e.target.value)}
            style={{ marginLeft: '10px', padding: '5px' }}
          >
            {tables.map(table => (
              <option key={table} value={table}>{table}</option>
            ))}
          </select>
        </label>
      </div>

      {error && (
        <div style={{ color: 'red', marginBottom: '15px' }}>{error}</div>
      )}

      {loading && <div>加载中...</div>}

      {tableData && (
        <>
          <div style={{ marginBottom: '15px' }}>
            <p>
              共 {tableData.total} 条记录，第 {tableData.page} / {tableData.total_pages} 页
            </p>
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', border: '1px solid #ddd', tableLayout: 'fixed' }}>
              <thead>
                <tr style={{ backgroundColor: '#f2f2f2' }}>
                  {tableData.columns.map(col => {
                    // 根据列名和数据类型设置宽度
                    let columnWidth = 'auto'
                    const columnName = col.COLUMN_NAME.toLowerCase()
                    const dataType = col.DATA_TYPE.toLowerCase()
                    
                    // Vector 类型列（如 embedding）设置较窄宽度
                    if (dataType.includes('vector') || columnName.includes('embedding')) {
                      columnWidth = '150px'
                    }
                    // Text 类型列（如 chunk_text）设置较宽宽度
                    else if (dataType.includes('text') || columnName.includes('text') || columnName.includes('chunk_text')) {
                      columnWidth = '400px'
                    }
                    // JSON 类型列设置较宽宽度（与 text 类似）
                    else if (dataType.includes('json')) {
                      columnWidth = '400px'
                    }
                    // 其他文本类型列（如 varchar）设置中等宽度
                    else if (dataType.includes('varchar') || dataType.includes('char')) {
                      columnWidth = '200px'
                    }
                    // ID 类型列设置较窄宽度
                    else if (columnName.includes('_id') || columnName.includes('id')) {
                      columnWidth = '150px'
                    }
                    // 时间类型列设置中等宽度
                    else if (dataType.includes('time') || dataType.includes('date')) {
                      columnWidth = '180px'
                    }
                    // 其他类型使用默认宽度
                    else {
                      columnWidth = '120px'
                    }
                    
                    return (
                      <th
                        key={col.COLUMN_NAME}
                        style={{ 
                          padding: '10px', 
                          border: '1px solid #ddd', 
                          textAlign: 'left',
                          width: columnWidth,
                          minWidth: columnWidth,
                          maxWidth: columnWidth,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap'
                        }}
                        title={`${col.COLUMN_NAME} (${col.DATA_TYPE})`}
                      >
                        {col.COLUMN_NAME}
                        <br />
                        <small style={{ color: '#666' }}>
                          {col.DATA_TYPE}
                          {col.IS_NULLABLE === 'YES' && ' (nullable)'}
                        </small>
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody>
                {tableData.data.map((row, idx) => (
                  <tr key={idx}>
                    {tableData.columns.map(col => {
                      const columnName = col.COLUMN_NAME.toLowerCase()
                      const dataType = col.DATA_TYPE.toLowerCase()
                      
                      // 对于 text 和 json 类型列，显示更多内容并允许换行
                      const isTextColumn = dataType.includes('text') || columnName.includes('text') || columnName.includes('chunk_text')
                      const isJsonColumn = dataType.includes('json')
                      const isVectorColumn = dataType.includes('vector') || columnName.includes('embedding')
                      // ID 类型列（如 event_id, chunk_id 等）完整显示
                      const isIdColumn = columnName.includes('_id') || columnName.includes('id')
                      
                      // 根据列类型决定显示长度
                      let displayLength = 100
                      if (isVectorColumn) {
                        displayLength = 50  // Vector 列显示更少
                      } else if (isTextColumn || isJsonColumn) {
                        displayLength = 300  // Text 和 JSON 列显示更多
                      } else if (isIdColumn) {
                        displayLength = Infinity  // ID 列完整显示，不截断
                      }
                      
                      const cellValue = row[col.COLUMN_NAME] !== null && row[col.COLUMN_NAME] !== undefined
                        ? String(row[col.COLUMN_NAME])
                        : '(null)'
                      
                      // ID 列不截断，其他列按长度截断
                      const displayValue = (isIdColumn || cellValue.length <= displayLength)
                        ? cellValue
                        : cellValue.substring(0, displayLength) + '...'
                      
                      return (
                        <td
                          key={col.COLUMN_NAME}
                          style={{ 
                            padding: '8px', 
                            border: '1px solid #ddd',
                            overflow: isIdColumn ? 'visible' : 'hidden',
                            textOverflow: isIdColumn ? 'clip' : 'ellipsis',
                            whiteSpace: (isTextColumn || isJsonColumn) ? 'normal' : (isIdColumn ? 'normal' : 'nowrap'),
                            wordBreak: (isTextColumn || isJsonColumn || isIdColumn) ? 'break-word' : 'normal',
                            maxWidth: '0'  // 配合 tableLayout: 'fixed' 使用
                          }}
                          title={cellValue !== displayValue ? cellValue : undefined}
                        >
                          {displayValue}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ marginTop: '15px' }}>
            <button
              onClick={() => handlePageChange(page - 1)}
              disabled={page <= 1}
              style={{ marginRight: '10px', padding: '5px 10px' }}
            >
              上一页
            </button>
            <span>第 {page} 页</span>
            <button
              onClick={() => handlePageChange(page + 1)}
              disabled={page >= tableData.total_pages}
              style={{ marginLeft: '10px', padding: '5px 10px' }}
            >
              下一页
            </button>
          </div>
        </>
      )}
    </div>
  )
}

