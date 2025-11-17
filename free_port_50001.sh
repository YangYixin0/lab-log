#!/usr/bin/env bash
# 释放占用 50001 端口的进程（TCP）
# 依赖：优先使用 lsof（apt-get install -y lsof），若无则尝试 ss

PORT=50001

echo "查找占用端口 ${PORT} 的进程..."

# 优先使用 lsof
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -t -i :"${PORT}")
else
  # 备选：使用 ss + awk
  PIDS=$(ss -lptn 'sport = :'${PORT} | awk 'NR>1 {gsub(/pid=/,"",$6); split($6,a,","); print a[1]}')
fi

if [ -z "$PIDS" ]; then
  echo "端口 ${PORT} 当前没有被占用。"
  exit 0
fi

echo "将结束以下进程（占用端口 ${PORT}）：$PIDS"

# 先尝试优雅结束
kill $PIDS 2>/dev/null

sleep 1

# 检查是否仍然存在
for pid in $PIDS; do
  if kill -0 "$pid" 2>/dev/null; then
    echo "进程 $pid 未结束，执行强制杀死..."
    kill -9 "$pid" 2>/dev/null || echo "无法杀死进程 $pid，请手动检查。"
  fi
done

echo "端口 ${PORT} 清理完成。"