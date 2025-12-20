/** 普通用户视图 */

import { useAuth } from '../hooks/useAuth'
import QRCode from './QRCode'

export default function UserDashboard() {
  const { user } = useAuth()

  return (
    <div style={{ padding: '20px' }}>
      <h2 style={{ marginBottom: '20px' }}>用户中心</h2>

      <div style={{ marginBottom: '30px' }}>
        <h3>用户信息</h3>
        <p><strong>用户 ID:</strong> {user?.user_id}</p>
        <p><strong>用户名:</strong> {user?.username}</p>
        <p><strong>角色:</strong> {user?.role}</p>
      </div>

      <div>
        <QRCode />
      </div>

      <div style={{ marginTop: '30px', padding: '20px', backgroundColor: '#f8f9fa', borderRadius: '4px' }}>
        <h3>功能说明</h3>
        <p>二维码用于向视频采集端证明您的身份。请妥善保管您的私钥。</p>
        <p>后续功能：解密请求、工单查看等（待实现）</p>
      </div>
    </div>
  )
}

