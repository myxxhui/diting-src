import type {
  GraphData, GraphNodeData, GraphEdgeData,
  ReasoningResult, ImpactLevel,
} from '../types/graph'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

export async function fetchFullGraph(): Promise<GraphData> {
  const resp = await fetch(`${API_BASE}/api/graph/query/full`)
  if (!resp.ok) throw new Error(`图谱加载失败: ${resp.status}`)
  return resp.json()
}

export async function fetchNodeDetail(nodeId: string) {
  const resp = await fetch(`${API_BASE}/api/graph/query/node/${nodeId}`)
  if (!resp.ok) throw new Error(`节点加载失败: ${resp.status}`)
  return resp.json()
}

export async function runReasoning(
  trigger: { node_id: string; variable: string; new_value: string; change_pct: number },
  maxDepth = 3
): Promise<ReasoningResult> {
  const resp = await fetch(`${API_BASE}/api/graph/reason/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ trigger, max_depth: maxDepth }),
  })
  if (!resp.ok) throw new Error(`推演失败: ${resp.status}`)
  const data = await resp.json()
  if (data.status !== 'ok') {
    throw new Error(data.error_detail || '推演服务不可用')
  }
  return data.result
}

export async function searchNodes(q: string) {
  const resp = await fetch(`${API_BASE}/api/graph/query/search?q=${encodeURIComponent(q)}`)
  if (!resp.ok) throw new Error(`搜索失败: ${resp.status}`)
  return resp.json()
}
