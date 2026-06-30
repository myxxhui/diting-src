import React from 'react'
import { useGraphStore } from '../../stores/graph-store'
import type { GraphNodeData } from '../../types/graph'

export function NodeDetailPanel() {
  const { graphData, selectedNodeId } = useGraphStore()
  if (!selectedNodeId || !graphData) return null

  const node = graphData.nodes.find((n) => (n.id || n.name) === selectedNodeId) as GraphNodeData | undefined
  if (!node) return <div style={{ padding: 16, color: '#999' }}>未找到节点信息</div>

  const label = (node.cn_name || node.name || node.label || node.id || '') as string

  return (
    <div style={{ padding: 16, fontSize: 13, lineHeight: 1.8, borderBottom: '1px solid #e0e0e0' }}>
      <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>{label}</h3>

      <div style={{ color: '#666', marginBottom: 4 }}>
        类型: {node.type || node.node_type || '-'}
      </div>

      {typeof node.gross_margin === 'number' && (
        <div style={{ color: '#666' }}>
          毛利率: {(node.gross_margin * 100).toFixed(1)}%
        </div>
      )}

      {typeof node.market_concentration === 'number' && (
        <div style={{ color: '#666' }}>
          市场集中度(CR5): {(node.market_concentration * 100).toFixed(0)}%
        </div>
      )}

      {node.key_companies && Array.isArray(node.key_companies) && node.key_companies.length > 0 && (
        <div style={{ color: '#666', marginTop: 4 }}>
          代表标的: {node.key_companies.join(', ')}
        </div>
      )}
    </div>
  )
}
