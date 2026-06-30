import React from 'react'
import { useGraphStore } from '../../stores/graph-store'

export function ReasoningPanel() {
  const { reasoningResult, isReasoning } = useGraphStore()

  if (isReasoning) {
    return (
      <div style={{ padding: 16, textAlign: 'center' }}>
        <div style={{ fontSize: 14, color: '#666', marginBottom: 12 }}>AI 推演中...</div>
        <div style={{
          width: 40, height: 40, margin: '0 auto',
          border: '3px solid #e0e0e0', borderTopColor: '#3498DB',
          borderRadius: '50%', animation: 'spin 1s linear infinite',
        }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    )
  }

  if (!reasoningResult) return null

  return (
    <div style={{ padding: 16, fontSize: 13, lineHeight: 1.8, maxHeight: 400, overflowY: 'auto' }}>
      <h4 style={{ margin: '0 0 12px', fontSize: 14 }}>📊 推演报告</h4>

      {reasoningResult.paths.map((path) => (
        <div
          key={path.path_id}
          style={{
            marginBottom: 12,
            padding: 10,
            background: '#f9f9f9',
            borderRadius: 6,
            border: '1px solid #e0e0e0',
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 6, fontSize: 12 }}>
            {path.path_id}: {path.path_chain.join(' → ')}
          </div>

          {path.propagation.map((step) => (
            <div key={step.step} style={{ fontSize: 11, marginBottom: 4, color: '#555' }}>
              {step.from} → {step.to}:
              毛利率受损 {step.margin_hit_min.toFixed(1)}~{step.margin_hit_max.toFixed(1)}pp ({step.level})
              · 延迟 {step.lag_days}天
            </div>
          ))}

          <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
            置信度: {(path.confidence * 100).toFixed(0)}%
          </div>
        </div>
      ))}

      {reasoningResult.beneficiaries.length > 0 && (
        <div style={{ marginTop: 12, padding: 10, background: '#e8f5e9', borderRadius: 6 }}>
          <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 4 }}>受益方</div>
          {reasoningResult.beneficiaries.map((b) => (
            <div key={b.node_name} style={{ fontSize: 11, color: '#2E7D32' }}>
              {b.node_name}: {b.reason}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
