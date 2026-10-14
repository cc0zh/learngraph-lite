import { useEffect, useRef, useState } from 'react';
import type { ClarificationField, Goal } from '../types';

const questions: { field: ClarificationField; title: string; reason: string; options: { label: string; value: string | number }[] }[] = [
  { field: 'desired_outcome', title: '希望学到什么程度？', reason: '这会决定学习的范围、深度，以及最后用什么成果来检查进展。', options: [
    { label: '理解核心概念', value: '理解核心概念，并能用自己的话解释和举例' },
    { label: '能独立完成一个小成果', value: '能独立完成一个与目标相关的小成果，并解释关键步骤' },
    { label: '深入原理与复杂应用', value: '深入理解原理，能够分析取舍并应用到复杂场景' },
  ] },
  { field: 'current_level', title: '从哪里开始更合适？', reason: '你的自述帮助安排起点，避免重复学习或跨度过大；它不是经过验证的能力。', options: [
    { label: '第一次接触', value: '第一次接触这个主题' },
    { label: '了解一些概念，还没实践', value: '了解一些概念，但还没有实践经验' },
    { label: '做过相关练习或项目', value: '做过相关练习或项目（用户自述，未验证）' },
  ] },
  { field: 'time_budget_minutes', title: '这次愿意投入多少时间？', reason: '这里是本次学习的总投入，不是每天的时间；它帮助控制路线长度，而不是承诺完成期限。', options: [
    { label: '1 小时 · 快速了解', value: 60 }, { label: '4 小时 · 入门实践', value: 240 }, { label: '12 小时 · 系统学习', value: 720 },
  ] },
];

export function GoalGuide({ goal, confirmed, editing, busy, onChange, onConfirm }: {
  goal: Goal; confirmed: boolean; editing: boolean; busy: boolean;
  onChange: (patch: Partial<Goal>) => void; onConfirm: () => void;
}) {
  const [step, setStep] = useState(() => questions.findIndex(q => !goal[q.field] && !goal.skipped_fields?.includes(q.field)));
  const [summary, setSummary] = useState(confirmed || step < 0);
  const [editSummary, setEditSummary] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, [step, summary]);
  useEffect(() => { if (editing) { setSummary(true); setEditSummary(true); } }, [editing]);
  const question = questions[Math.max(0, step)];
  const writable = !confirmed || editing;
  const skipped = (field: ClarificationField) => goal.skipped_fields?.includes(field);
  function answer(field: ClarificationField, value: string | number | null) {
    onChange({ [field]: value, skipped_fields: (goal.skipped_fields || []).filter(name => name !== field) });
  }
  function next(skip = false) {
    if (skip) onChange({ [question.field]: question.field === 'time_budget_minutes' ? null : '',
      skipped_fields: [...new Set([...(goal.skipped_fields || []), question.field])] });
    if (step >= questions.length - 1) setSummary(true);
    else setStep(step + 1);
  }
  function missing(field: ClarificationField) { return skipped(field) ? '已跳过 · 默认假设' : '未提供 · 默认假设'; }
  return <div className="goal-guide">
    {!summary && writable ? <form onSubmit={event => { event.preventDefault(); next(); }}>
      <fieldset disabled={busy}>
        <p className="eyebrow">关键问题 {step + 1} / 3 · 可以跳过</p>
        <h3 tabIndex={-1} ref={heading}>{question.title}</h3>
        <p className="muted small">为什么问：{question.reason}</p>
        <div className="guide-options">{question.options.map(option => <button type="button" key={option.label}
          className={goal[question.field] === option.value ? 'selected' : 'quiet'} aria-pressed={goal[question.field] === option.value}
          onClick={() => answer(question.field, option.value)}>{option.label}</button>)}</div>
        {question.field === 'time_budget_minutes' ? <label>可投入时间（总分钟）<input type="number" min="1" step="1" required
          value={goal.time_budget_minutes ?? ''} onChange={event => answer(question.field, event.target.value ? Number(event.target.value) : null)}/></label>
          : <label>{question.field === 'desired_outcome' ? '期望成果（也可以自己写）' : '已有基础（用户自述，未验证）'}<textarea required maxLength={2000}
            value={goal[question.field]} onChange={event => answer(question.field, event.target.value)}/></label>}
        <div className="actions"><button type="submit">下一步</button><button type="button" className="quiet" onClick={() => next(true)}>跳过这一项</button>
          {step > 0 && <button type="button" className="quiet" onClick={() => setStep(step - 1)}>上一步</button>}</div>
        <button type="button" className="text-button" onClick={() => setSummary(true)}>先看目标摘要</button>
      </fieldset>
    </form> : <>
      <h3 tabIndex={-1} ref={heading}>目标摘要</h3>
      <p className="muted small">确认的是你的学习意图，不是能力认证。以下假设会用于生成路线，可以随时修改后再确认。</p>
      <dl className="goal-summary">
        <dt>学习意图</dt><dd>{goal.title}</dd>
        <dt>成果与深度</dt><dd>{goal.desired_outcome || '理解核心概念、完成适合主题的练习并解释结果。'}{!goal.desired_outcome && <small>{missing('desired_outcome')}</small>}</dd>
        <dt>起点</dt><dd>{goal.current_level || '基础未知，从必要的入门内容开始，不假设已经掌握。'}<small>{goal.current_level ? '用户自述 · 未验证' : missing('current_level')}</small></dd>
        <dt>总投入</dt><dd>{goal.time_budget_minutes ? `${goal.time_budget_minutes} 分钟` : '暂按 240 分钟作为规划参考，不代表你的承诺。'}{!goal.time_budget_minutes && <small>{missing('time_budget_minutes')}</small>}</dd>
        <dt>约束与重点</dt><dd>{goal.constraints || '未提供，不额外假设期限或工具偏好。'}</dd>
      </dl>
      {writable && <>
        <button type="button" className="quiet" disabled={busy} onClick={() => setEditSummary(value => !value)}>{editSummary ? '收起摘要编辑' : '修改摘要'}</button>
        <form onSubmit={event => { event.preventDefault(); onConfirm(); }}>
          <fieldset disabled={busy}>
            {editSummary && <div className="summary-editor">
              <label>目标<input required maxLength={2000} value={goal.title} onChange={event => onChange({ title: event.target.value })}/></label>
              <label>期望成果<textarea maxLength={2000} value={goal.desired_outcome} onChange={event => answer('desired_outcome', event.target.value)}/></label>
              <label>已有基础（用户自述，未验证）<textarea maxLength={2000} value={goal.current_level} onChange={event => answer('current_level', event.target.value)}/></label>
              <label>可投入时间（总分钟）<input type="number" min="1" step="1" value={goal.time_budget_minutes ?? ''} onChange={event => answer('time_budget_minutes', event.target.value ? Number(event.target.value) : null)}/></label>
              <label>其他约束与重点<textarea maxLength={2000} value={goal.constraints} onChange={event => onChange({ constraints: event.target.value })}/></label>
            </div>}
            <div className="actions"><button type="submit">确认目标摘要</button>{!confirmed && <button type="button" className="quiet" onClick={() => { setStep(0); setSummary(false); }}>返回引导问题</button>}</div>
          </fieldset>
        </form>
      </>}
      {confirmed && !editing && <p className="hint">目标已明确确认。路线草稿不会自动发布。</p>}
    </>}
  </div>;
}
