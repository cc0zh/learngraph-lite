import { useState } from 'react';
import { api } from '../api';
import { ErrorBox } from '../components';
import { Citations } from '../documents';
import type { Feedback } from '../types';
import type { PublicExercise } from './types';
import { LessonMarkdown } from './LessonMarkdown';

export function QuizCard({ goalId, exercise, feedback, title, readOnly = false, onChanged }: {
  goalId: string; exercise: PublicExercise; feedback?: Feedback; title: string; readOnly?: boolean;
  onChanged?: () => void | Promise<void>;
}) {
  const [choice, setChoice] = useState('');
  const [submitted, setSubmitted] = useState<Feedback>();
  const [answering, setAnswering] = useState(false);
  const [error, setError] = useState('');
  const result = feedback || submitted;
  async function answer() {
    if (!choice || readOnly || answering || result) return;
    setAnswering(true); setError('');
    // Transport retries preserve the attempt identity; only attempts can affect mastery.
    const key = `learngraph:answer:${exercise.id}:${choice}`;
    const submission = localStorage.getItem(key) || crypto.randomUUID();
    localStorage.setItem(key, submission);
    try {
      const accepted = await api<Feedback>(`/goals/${goalId}/exercises/${exercise.id}/attempts`, { submission_id: submission, selected_option_id: choice });
      setSubmitted(accepted);
      await onChanged?.();
    } catch (e) { setError(String(e)); }
    finally { setAnswering(false); }
  }
  return <article className="exercise"><h3>{title}</h3><LessonMarkdown>{exercise.prompt}</LessonMarkdown>
    <fieldset disabled={readOnly || answering || !!result}><legend>选择一个答案</legend>
      {exercise.options.map(option => <label className="option" key={option.id}><input type="radio" name={`quiz-${exercise.id}-${title}`} checked={(result?.attempt.selected_option_id || choice) === option.id} onChange={() => setChoice(option.id)}/><span>{option.text}</span></label>)}
      <button disabled={!choice} onClick={() => { void answer(); }}>提交答案</button>
    </fieldset><ErrorBox error={error}/>
    {readOnly && <p className="muted small">历史题目只读，不接受新作答。</p>}
    {result && <div className={`feedback ${result.attempt.is_correct ? 'correct' : 'incorrect'}`} role="status"><strong>{result.attempt.is_correct ? '回答正确' : '再理解一下'}</strong><LessonMarkdown>{result.explanation}</LessonMarkdown><p>正确答案：{exercise.options.find(option => option.id === result.correct_option_id)?.text}</p></div>}
    <Citations citationMap={exercise.citation_map || {}} unverifiedIds={exercise.unverified_citation_ids}
      endpoint={`/api/goals/${goalId}/exercises/${exercise.id}/citations/{citationId}`} goalId={exercise.goal_id || goalId} nodeId={exercise.node_id}/>
  </article>;
}
