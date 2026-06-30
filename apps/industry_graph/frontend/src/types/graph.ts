export interface GraphNodeData {
  id: string
  name?: string
  label?: string
  cn_name?: string
  type?: string
  node_type?: string
  gross_margin?: number
  market_concentration?: number
  key_companies?: string[]
  [key: string]: unknown
}

export interface GraphEdgeData {
  source: string
  target: string
  type?: string
  supply_ratio?: number
  cost_ratio?: number
  is_critical?: boolean
  [key: string]: unknown
}

export interface GraphData {
  nodes: GraphNodeData[]
  edges: GraphEdgeData[]
}

export interface ReasoningResult {
  trigger: Record<string, unknown>
  paths: PathImpact[]
  beneficiaries: Beneficiary[]
  overall_assessment: string
  confidence_overall: number
}

export interface PathImpact {
  path_id: string
  path_chain: string[]
  propagation: PropagationStep[]
  endpoint_impact: { node: string; margin_hit_level: string; summary: string }
  confidence: number
}

export interface PropagationStep {
  step: number
  from: string
  to: string
  cost_pass_through_pct: number
  margin_hit_min: number
  margin_hit_max: number
  level: 'benefit' | 'minor' | 'major' | 'critical' | 'unknown'
  lag_days: number
  reasoning: string
}

export interface Beneficiary {
  node_name: string
  reason: string
}

export type ImpactLevel = 'benefit' | 'minor' | 'major' | 'critical' | 'unknown'
