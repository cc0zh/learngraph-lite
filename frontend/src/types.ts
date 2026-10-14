export type ClarificationField = 'desired_outcome' | 'current_level' | 'time_budget_minutes';
export interface Goal { title: string; desired_outcome: string; current_level: string; time_budget_minutes: number | null; constraints: string; confirmed: boolean; assumptions?: string[]; skipped_fields?: ClarificationField[] }
export interface CitationSource { id: string; document_id: string; document_version: number; chunk_id: string; quote: string; start_offset: number; end_offset: number; page_number: number | null; heading: string | null; text_hash: string; status: 'valid' | 'stale' | 'unavailable'; cited: boolean }
export interface RunOutput extends Record<string, unknown> { citation_map?: Record<string, CitationSource>; unverified_citation_ids?: string[]; source_mode?: 'general' | 'documents' }
export interface GraphNode { id: string; title: string; explanation: string; learning_outcome: string; estimated_minutes: number; priority: number; citation_ids: string[] }
export interface GraphEdge { source: string; target: string; kind: 'prerequisite' }
export interface Graph { nodes: GraphNode[]; edges: GraphEdge[]; status: string; revision: number; content_revision: number; source_mode?: string; citation_map?: Record<string, CitationSource> }
export interface Plan { goal_id: string; goal: Goal; graph: Graph | null; version: number; questions: string[]; clarification_round: number }
export interface ToolActivity { call_id: string; name: string; status: string; elapsed_ms?: number }
export interface Run { run_id: string; status: string; mode: string; user_text: string; final_text?: string; partial_text: string; error?: string; created_at: string; tool_activity: Record<string, ToolActivity>; summary?: string; usage?: Record<string, number>; output?: RunOutput }
export interface Context { node: GraphNode & { mastery: string; sample_count: number; accuracy: number }; prerequisites: GraphNode[] }
export interface NextAction { node_id: string | null; reason_text: string; estimated_minutes: number }
export interface Exercise { id: string; prompt: string; options: { id: string; text: string }[]; source_mode?: 'general' | 'documents'; citation_map?: Record<string, CitationSource>; unverified_citation_ids?: string[]; graph_content_revision?: number }
export interface Feedback { attempt: { is_correct: boolean; counted: boolean; selected_option_id: string }; explanation: string; correct_option_id: string }
