import cytoscape from 'cytoscape'
import type { GraphData } from '../types/graph'

export const IMPACT_COLORS: Record<string, string> = {
  critical: '#E74C3C',
  major: '#F39C12',
  minor: '#F1C40F',
  benefit: '#27AE60',
  unknown: '#95A5A6',
}

export const NODE_STYLES = [
  {
    selector: 'node[type="Sector"]',
    style: { 'background-color': '#4A90D9', shape: 'round-rectangle', width: 140, height: 52, 'font-size': 14 },
  },
  {
    selector: 'node[type="SubSector"]',
    style: { 'background-color': '#7B9FC8', shape: 'round-rectangle', width: 120, height: 42, 'font-size': 13 },
  },
  {
    selector: 'node[type="IndustryNode"]',
    style: { 'background-color': '#A8C8E8', shape: 'ellipse', width: 100, height: 40, 'font-size': 12 },
  },
  {
    selector: 'node[type="Company"]',
    style: { 'background-color': '#C5DCF0', shape: 'ellipse', width: 80, height: 32, 'font-size': 11 },
  },
  {
    selector: 'node.impact-critical',
    style: { 'background-color': IMPACT_COLORS.critical, 'border-width': 4, 'border-color': '#C0392B', 'border-opacity': 1 },
  },
  {
    selector: 'node.impact-major',
    style: { 'background-color': IMPACT_COLORS.major, 'border-width': 3, 'border-color': '#E67E22' },
  },
  {
    selector: 'node.impact-minor',
    style: { 'background-color': IMPACT_COLORS.minor, 'border-width': 2, 'border-color': '#F9E79F' },
  },
  {
    selector: 'node.impact-benefit',
    style: { 'background-color': IMPACT_COLORS.benefit, 'border-width': 3, 'border-color': '#1E8449' },
  },
  {
    selector: 'edge',
    style: { width: 2, 'line-color': '#999', 'target-arrow-color': '#999', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier' },
  },
  {
    selector: 'edge[type="AFFECTS"], edge[type="IMPACTS"]',
    style: { 'line-color': '#E74C3C', 'line-style': 'dashed', 'target-arrow-color': '#E74C3C' },
  },
  {
    selector: 'edge.active-propagation',
    style: { 'line-color': '#E74C3C', width: 4, 'line-style': 'solid' },
  },
]

export const LAYOUT = {
  name: 'dagre' as const,
  rankDir: 'LR',
  nodeSep: 80,
  edgeSep: 30,
  rankSep: 150,
  animate: true,
  animationDuration: 500,
}

export function transformGraphData(data: GraphData): cytoscape.ElementDefinition[] {
  const elements: cytoscape.ElementDefinition[] = []

  for (const node of data.nodes) {
    const nid = node.id || node.name || ''
    const label = node.cn_name || node.name || node.label || nid
    elements.push({
      data: {
        id: nid,
        label,
        ...node,
      },
    })
  }

  for (const edge of data.edges) {
    const source = edge.source || edge.from
    const target = edge.target || edge.to
    if (!source || !target) continue
    elements.push({
      data: {
        id: `${source}->${target}`,
        source,
        target,
        ...edge,
      },
    })
  }

  return elements
}
