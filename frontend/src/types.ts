export interface Goal { title: string; desired_outcome: string; current_level: string; time_budget_minutes: number | null; constraints: string; confirmed: boolean }
export interface GraphNode { id: string; title: string; explanation: string; learning_outcome: string; estimated_minutes: number; priority: number; citation_ids: string[] }
export interface GraphEdge { source: string; target: string; kind: 'prerequisite' }
export interface Graph { nodes: GraphNode[]; edges: GraphEdge[]; status: string; revision: number; content_revision: number }
export interface Plan { goal_id: string; goal: Goal; graph: Graph | null; version: number; questions: string[]; clarification_round: number }
export interface ToolActivity { call_id: string; name: string; status: string; elapsed_ms?: number }
export interface Run { run_id: string; status: string; mode: string; user_text: string; final_text?: string; partial_text: string; error?: string; created_at: string; tool_activity: Record<string, ToolActivity> }
export interface Context { node: GraphNode & { mastery: string; sample_count: number; accuracy: number }; prerequisites: GraphNode[] }
export interface NextAction { node_id: string | null; reason_text: string; estimated_minutes: number }
export interface Exercise { id: string; prompt: string; options: { id: string; text: string }[] }
export interface Feedback { attempt: { is_correct: boolean; counted: boolean; selected_option_id: string }; explanation: string; correct_option_id: string }
