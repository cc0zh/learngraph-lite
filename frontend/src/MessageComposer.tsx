import type { ReactNode } from 'react';
import { Icon } from './components';

interface ComposerProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  submitLabel: string;
  disabled: boolean;
  placeholder: string;
  maxLength: number;
  children?: ReactNode;
  note?: ReactNode;
  stop?: { label: string; onClick: () => void };
}

export function MessageComposer({ id, label, value, onChange, onSubmit, submitLabel, disabled, placeholder, maxLength, children, note, stop }: ComposerProps) {
  return <form className="composer wb-composer message-composer" onSubmit={event => {
    event.preventDefault();
    if (!disabled && value.trim()) onSubmit();
  }}>
    <label className="sr-only" htmlFor={id}>{label}</label>
    <textarea id={id} value={value} maxLength={maxLength} placeholder={placeholder} onChange={event => onChange(event.target.value)}
      aria-keyshortcuts="Control+Enter Meta+Enter" onKeyDown={event => {
        if (event.key !== 'Enter' || !(event.ctrlKey || event.metaKey) || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229 || disabled) return;
        event.preventDefault(); event.currentTarget.form?.requestSubmit();
      }}/>
    <div className="composer-toolbar"><div className="composer-context">{children}</div><div className="composer-controls">
      <span className="composer-shortcut">Ctrl / ⌘ + Enter 发送</span>
      {stop && <button type="button" className="quiet composer-stop" onClick={stop.onClick}><Icon name="stop"/>{stop.label}</button>}
      <button type="submit" className="composer-send" disabled={disabled} aria-label={submitLabel} title={submitLabel}><Icon name="arrowUp"/></button>
    </div></div>
    {note && <div className="composer-note">{note}</div>}
  </form>;
}
