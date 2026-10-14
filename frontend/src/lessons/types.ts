import type { CitationSource, Exercise } from '../types';
export interface ArtifactSources {
  citation_map?: Record<string, CitationSource>;
  unverified_citation_ids?: string[];
  source_mode?: 'general' | 'documents';
}
export interface PublicExercise extends Exercise, ArtifactSources {
  goal_id?: string; node_id?: string; graph_content_revision?: number;
}
export interface LessonComponent { id: string; kind: string; props: unknown }
export interface PublicLesson extends ArtifactSources {
  id: string; goal_id: string; node_id: string; graph_content_revision: number;
  schema_version: number; version: number; title: string; markdown: string;
  components: LessonComponent[]; outdated: boolean;
}
export interface SavedEvent {
  event_id: string; package_version: number; component_id: string;
  action: 'mark_read' | 'step_changed' | 'request_explanation';
  payload: Record<string, unknown>;
  acknowledged: boolean;
}
export interface ExplanationLink { event: SavedEvent; slot: string; requestId: string }
export interface Step { title: string; description: string; slots: { text?: string } }
export type ValidComponent =
  | { id: string; kind: 'markdown'; props: { text: string } }
  | { id: string; kind: 'quiz_choice'; props: { exercise_id: string } }
  | { id: string; kind: 'stepper'; props: { steps: Step[] } }
  | { id: string; kind: 'comparison_table'; props: { columns: string[]; rows: string[][] } };

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const keys = (value: Record<string, unknown>, allowed: string[]) => Object.keys(value).every(key => allowed.includes(key));
const text = (value: unknown, max: number): value is string => typeof value === 'string' && !!value.trim() && value.length <= max;

// Select exact supported fields; unknown/legacy components never become executable UI.
export function validComponent(component: unknown): ValidComponent | undefined {
  if (!record(component) || !keys(component, ['id', 'kind', 'props'])) return;
  const { id, kind, props } = component;
  if (!text(id, 128) || id === 'chapter' || !record(props)) return;
  if (kind === 'markdown' && keys(props, ['text']) && text(props.text, 4000)) return { id, kind, props: { text: props.text } };
  if (kind === 'quiz_choice' && keys(props, ['exercise_id']) && text(props.exercise_id, 128)) return { id, kind, props: { exercise_id: props.exercise_id } };
  if (kind === 'stepper' && keys(props, ['steps']) && Array.isArray(props.steps) && props.steps.length >= 1 && props.steps.length <= 12) {
    const steps: Step[] = [];
    for (const step of props.steps) {
      if (!record(step) || !keys(step, ['title', 'description', 'slots']) || !text(step.title, 200) || !text(step.description, 2000)
        || !record(step.slots) || !keys(step.slots, ['text']) || (step.slots.text !== undefined && !text(step.slots.text, 2000))) return;
      steps.push({ title: step.title, description: step.description, slots: { text: step.slots.text as string | undefined } });
    }
    return { id, kind, props: { steps } };
  }
  if (kind === 'comparison_table' && keys(props, ['columns', 'rows']) && Array.isArray(props.columns) && props.columns.length >= 1 && props.columns.length <= 6
    && props.columns.every(column => text(column, 200)) && Array.isArray(props.rows) && props.rows.length >= 1 && props.rows.length <= 20
    && props.rows.every(row => Array.isArray(row) && row.length === (props.columns as unknown[]).length && row.every(cell => text(cell, 2000)))) {
    return { id, kind, props: { columns: props.columns as string[], rows: props.rows as string[][] } };
  }
}
