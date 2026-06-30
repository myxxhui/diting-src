import cytoscape from 'cytoscape'
import type { PropagationStep } from '../types/graph'
import { IMPACT_COLORS } from './cytoscape-config'

const IMPACT_CLASS: Record<string, string> = {
  critical: 'impact-critical',
  major: 'impact-major',
  minor: 'impact-minor',
  benefit: 'impact-benefit',
  unknown: '',
}

export interface AnimationStep {
  nodeId: string
  impactClass: string
  delay: number
}

export function buildAnimationSteps(
  propagation: PropagationStep[]
): AnimationStep[] {
  const steps: AnimationStep[] = []
  let delay = 0
  for (const p of propagation) {
    const cls = IMPACT_CLASS[p.level] || ''
    steps.push({
      nodeId: p.to,
      impactClass: cls,
      delay,
    })
    delay += 800
  }
  return steps
}

export function playPropagationAnimation(
  cy: cytoscape.Core,
  steps: AnimationStep[],
  onComplete: () => void
) {
  let i = 0

  function animateNext() {
    if (i >= steps.length) {
      onComplete()
      return
    }
    const step = steps[i]
    const node = cy.getElementById(step.nodeId)

    node.removeClass('impact-critical impact-major impact-minor impact-benefit')
      .addClass(step.impactClass)
      .animate({
        style: { 'border-width': 6, 'border-opacity': 1 },
        duration: 300,
      })
      .animate({
        style: { 'border-width': 2, 'border-opacity': 0.7 },
        duration: 500,
      })

    cy.animate({
      fit: { eles: node, padding: 120 },
      duration: 400,
    })

    i++
    setTimeout(animateNext, 800)
  }

  animateNext()
}
