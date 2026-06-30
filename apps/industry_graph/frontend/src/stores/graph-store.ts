import { create } from 'zustand'
import type { GraphData, GraphNodeData, ReasoningResult } from '../types/graph'

interface GraphStore {
  graphData: GraphData | null
  selectedNodeId: string | null
  reasoningResult: ReasoningResult | null
  isReasoning: boolean
  setGraphData: (data: GraphData) => void
  selectNode: (id: string | null) => void
  setReasoningResult: (result: ReasoningResult | null) => void
  setIsReasoning: (v: boolean) => void
}

export const useGraphStore = create<GraphStore>((set) => ({
  graphData: null,
  selectedNodeId: null,
  reasoningResult: null,
  isReasoning: false,
  setGraphData: (data) => set({ graphData: data }),
  selectNode: (id) => set({ selectedNodeId: id }),
  setReasoningResult: (result) => set({ reasoningResult: result }),
  setIsReasoning: (v) => set({ isReasoning: v }),
}))
