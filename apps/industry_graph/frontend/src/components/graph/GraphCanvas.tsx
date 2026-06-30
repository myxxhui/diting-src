import React, { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'
import dagre from 'cytoscape-dagre'
import { useGraphStore } from '../stores/graph-store'
import { NODE_STYLES, LAYOUT, transformGraphData } from '../graph/cytoscape-config'
import { playPropagationAnimation, buildAnimationSteps } from '../graph/animations'

cytoscape.use(dagre)

export function GraphCanvas() {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)
  const { graphData, selectNode, reasoningResult, setReasoningResult } = useGraphStore()

  useEffect(() => {
    if (!containerRef.current || !graphData) return

    // 销毁旧实例
    cyRef.current?.destroy()

    const elements = transformGraphData(graphData)
    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: NODE_STYLES,
      layout: LAYOUT,
      wheelSensitivity: 0.3,
    })
    cyRef.current = cy

    // 点击节点事件
    cy.on('tap', 'node', (evt) => {
      const node = evt.target
      selectNode(node.id())
    })

    cy.on('tap', (evt) => {
      if (evt.target === cy) {
        selectNode(null)
      }
    })

    return () => {
      cy.destroy()
    }
  }, [graphData])

  // 推理结果动画
  useEffect(() => {
    if (!reasoningResult || !cyRef.current) return
    const allSteps = reasoningResult.paths.flatMap((p) => buildAnimationSteps(p.propagation))
    playPropagationAnimation(cyRef.current, allSteps, () => {
      // 动画完成
    })
  }, [reasoningResult])

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '100%', minHeight: 500, background: '#f5f7fa' }}
    />
  )
}
