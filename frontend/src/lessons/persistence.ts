import { useState } from 'react';
import { api } from '../api';
import type { PublicLesson, SavedEvent } from './types';

export function readSaved<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(key) || 'null') as T ?? fallback; }
  catch { return fallback; }
}
export function useSaved<T>(key: string, fallback: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => readSaved(key, fallback));
  return [value, next => { localStorage.setItem(key, JSON.stringify(next)); setValue(next); }];
}
export function newEvent(lesson: PublicLesson, componentId: string, action: SavedEvent['action'], payload: Record<string, unknown> = {}): SavedEvent {
  const event = { event_id: crypto.randomUUID(), package_version: lesson.version, component_id: componentId, action, payload, acknowledged: false };
  localStorage.setItem(`learngraph:lesson-event:${event.event_id}`, JSON.stringify({ packageId: lesson.id, packageVersion: lesson.version, componentId }));
  return event;
}
export async function acknowledge(lesson: PublicLesson, event: SavedEvent): Promise<SavedEvent> {
  if (lesson.outdated || lesson.schema_version !== 1) throw new Error('历史学习包只读。');
  const { acknowledged: _acknowledged, ...body } = event;
  const result = await api<{ event: { id: string; package_id: string; package_version: number; component_id: string; action: string; payload: Record<string, unknown> } }>(`/goals/${lesson.goal_id}/lessons/${lesson.id}/events`, body);
  if (result.event.id !== event.event_id || result.event.package_id !== lesson.id || result.event.package_version !== lesson.version
    || result.event.component_id !== event.component_id || result.event.action !== event.action
    || JSON.stringify(result.event.payload) !== JSON.stringify(event.payload)) throw new Error('事件确认不匹配，尚未保存。');
  return { ...event, acknowledged: true };
}
