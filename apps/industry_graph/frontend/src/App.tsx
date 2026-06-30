import React, { useEffect, useState } from 'react'
import { GraphCanvas } from './components/graph/GraphCanvas'
import { NodeDetailPanel } from './components/panels/NodeDetailPanel'
import { TriggerBar } from './components/panels/TriggerBar'
import { ReasoningPanel } from './components/panels/ReasoningPanel'
import { useGraphStore } from './stores/graph-store'
import { fetchFullGraph } from './services/graph-service'

export default function App() {
  const { setGraphData, selectedNodeId } = useGraphStore()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchFullGraph()
      .then((data) => {
        setGraphData(data)
        setLoading(false)
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : String(e))
        setLoading(false)
      })
  }, [])

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: '#666' }}>
        加载图谱数据...
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <div style={{ color: '#E74C3C', fontSize: 16, marginBottom: 12 }}>图谱加载失败</div>
        <div style={{ color: '#999', fontSize: 13 }}>{error}</div>
        <div style={{ marginTop: 16, fontSize: 12, color: '#888' }}>
          请确认后端服务已启动(NEO4J_URI正确)，然后刷新页面
        </div>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      {/* 主画布区 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {/* 顶部标题栏 */}
        <div style={{
          height: 48, display: 'flex', alignItems: 'center', padding: '0 20px',
          background: '#2C3E50', color: '#fff',
        }}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>🏭 产业关系图谱系统</span>
          <span style={{ marginLeft: 'auto', fontSize: 11, color: '#95A5A6' }}>
            点击节点查看详情 · 选中节点后触发推演
          </span>
        </div>

        {/* 图谱画布 */}
        <div style={{ flex: 1, position: 'relative' }}>
          <GraphCanvas />
        </div>
      </div>

      {/* 右侧面板 */}
      {selectedNodeId && (
        <div style={{
          width: 320, borderLeft: '1px solid #e0e0e0',
          background: '#fff', overflowY: 'auto',
        }}>
          {/* 节点详情 */}
          <NodeDetailPanel />

          {/* 触发推演 */}
          <TriggerBar />

          {/* 推演结果 */}
          <ReasoningPanel />
        </div>
      )}
    </div>
  )
}
