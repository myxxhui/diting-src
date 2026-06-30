import React, { useState } from 'react'
import { useGraphStore } from '../../stores/graph-store'
import { runReasoning } from '../../services/graph-service'

export function TriggerBar() {
  const { graphData, selectedNodeId, setIsReasoning, setReasoningResult, reasoningResult } = useGraphStore()
  const [changePct, setChangePct] = useState(20)
  const [variable, setVariable] = useState('price')

  if (!selectedNodeId || !graphData) return null

  const node = graphData.nodes.find((n) => (n.id || n.name) === selectedNodeId)
  const nodeName = (node?.cn_name || node?.name || node?.label || selectedNodeId) as string

  const handleTrigger = async () => {
    setIsReasoning(true)
    try {
      const result = await runReasoning({
        node_id: selectedNodeId,
        variable,
        new_value: `变化${changePct > 0 ? '+' : ''}${changePct}%`,
        change_pct: changePct,
      }, 3)
      setReasoningResult(result)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      alert(`推演失败: ${msg}`)
    } finally {
      setIsReasoning(false)
    }
  }

  return (
    <div style={{ padding: 16, borderBottom: '1px solid #e0e0e0' }}>
      <h4 style={{ margin: '0 0 12px', fontSize: 14 }}>🎮 触发推演</h4>

      <div style={{ marginBottom: 8 }}>
        <label style={{ fontSize: 12, color: '#666', display: 'block', marginBottom: 4 }}>
          影响节点: <strong>{nodeName}</strong>
        </label>
      </div>

      <div style={{ marginBottom: 8 }}>
        <label style={{ fontSize: 12, color: '#666', display: 'block', marginBottom: 4 }}>变量</label>
        <select
          value={variable}
          onChange={(e) => setVariable(e.target.value)}
          style={{ width: '100%', padding: '6px 8px', borderRadius: 4, border: '1px solid #ccc' }}
        >
          <option value="price">现货价格</option>
          <option value="capacity">产能利用率</option>
          <option value="tariff">关税</option>
          <option value="demand">下游需求</option>
        </select>
      </div>

      <div style={{ marginBottom: 12 }}>
        <label style={{ fontSize: 12, color: '#666', display: 'block', marginBottom: 4 }}>
          变化幅度: {changePct > 0 ? '+' : ''}{changePct}%
        </label>
        <input
          type="range"
          min={-80}
          max={200}
          value={changePct}
          onChange={(e) => setChangePct(Number(e.target.value))}
          style={{ width: '100%' }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#999' }}>
          <span>-80%</span>
          <span>0%</span>
          <span>+200%</span>
        </div>
      </div>

      <button
        onClick={handleTrigger}
        style={{
          width: '100%',
          padding: '10px',
          background: '#3498DB',
          color: '#fff',
          border: 'none',
          borderRadius: 6,
          fontSize: 14,
          cursor: 'pointer',
          fontWeight: 600,
        }}
      >
        开始推演
      </button>

      {reasoningResult && (
        <div style={{ marginTop: 12, fontSize: 12, color: '#27AE60' }}>
          上次推演完成 · 置信度: {reasoningResult.confidence_overall.toFixed(2)}
        </div>
      )}
    </div>
  )
}
