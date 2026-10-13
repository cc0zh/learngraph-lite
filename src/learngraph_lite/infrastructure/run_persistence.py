"""SQLite run admission, snapshots and explanation task links for one API process."""

from __future__ import annotations

from contextlib import closing
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from learngraph_lite.application.agent import RunAdmissionError, RunEvent, RunRecord, RunRequest


def _json(value) -> str:
    return json.dumps(asdict(value), ensure_ascii=False, sort_keys=True,
                      default=lambda item: item.isoformat())


class SQLiteRunRepository:
    def __init__(self, database_path: str | Path):
        self._database_path = str(database_path)
        with closing(self._connect()) as connection, connection:
            connection.execute("""create table if not exists agent_runs (
                run_id text primary key, session_id text not null, request_id text not null,
                request_json text not null, record_json text not null,
                unique(session_id, request_id))""")
            connection.execute("""create table if not exists agent_run_events (
                run_id text not null, seq integer not null, event_json text not null,
                primary key(run_id, seq))""")
            connection.execute("""create table if not exists lesson_run_tasks (
                goal_id text not null, event_id text not null, slot text not null,
                root_task_id text not null, initial_input text not null,
                primary key(goal_id, event_id, slot))""")

    def load(self) -> tuple[tuple[RunRequest, RunRecord, tuple[RunEvent, ...]], ...]:
        with closing(self._connect()) as connection, connection:
            connection.execute("begin")
            result = []
            for run_id, request_json, record_json in connection.execute(
                    "select run_id, request_json, record_json from agent_runs order by rowid"):
                request = json.loads(request_json)
                request["lesson_exercise_ids"] = tuple(request.get("lesson_exercise_ids", ()))
                record = json.loads(record_json)
                for field in ("created_at", "updated_at"):
                    record[field] = datetime.fromisoformat(record[field])
                events = []
                for (event_json,) in connection.execute(
                        "select event_json from agent_run_events where run_id=? order by seq", (run_id,)):
                    event = json.loads(event_json)
                    event["created_at"] = datetime.fromisoformat(event["created_at"])
                    events.append(RunEvent(**event))
                result.append((RunRequest(**request), RunRecord(**record), tuple(events)))
            return tuple(result)

    def admit(self, request: RunRequest, record: RunRecord) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("begin immediate")
            if request.source_event_id is not None:
                # The ACK must already be durable in this same database. Lesson mutate
                # may rewrite lesson tables; links deliberately live in a separate table.
                row = connection.execute("""select p.node_id, e.package_version, p.metadata_json
                    from lesson_events e join lesson_packages p
                    on e.goal_id=p.goal_id and e.package_id=p.package_id
                    where e.goal_id=? and e.event_id=?""",
                    (request.goal_id, request.source_event_id)).fetchone()
                if row is None or row[0] != request.node_id or row[1] != json.loads(row[2]).get("version", 1):
                    raise RunAdmissionError("invalid_scope", "explanation requires a saved event in the bound node/version")
                if request.retry_of_run_id is None:
                    connection.execute("""insert into lesson_run_tasks
                        (goal_id, event_id, slot, root_task_id, initial_input) values (?, ?, ?, ?, ?)""",
                        (request.goal_id, request.source_event_id, request.explanation_slot,
                         record.root_task_id, request.user_text))
                else:
                    link = connection.execute("""select root_task_id, initial_input from lesson_run_tasks
                        where goal_id=? and event_id=? and slot=?""",
                        (request.goal_id, request.source_event_id, request.explanation_slot)).fetchone()
                    if link != (record.root_task_id, request.user_text):
                        raise RunAdmissionError("invalid_retry", "retry must keep the saved explanation task/input")
            connection.execute("insert into agent_runs values (?, ?, ?, ?, ?)",
                               (record.run_id, request.session_id, request.idempotency_key, _json(request), _json(record)))

    def save(self, record: RunRecord, events: tuple[RunEvent, ...]) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("begin immediate")
            cursor = connection.execute("update agent_runs set record_json=? where run_id=?",
                                        (_json(record), record.run_id))
            if cursor.rowcount != 1:
                raise KeyError("cannot save an unadmitted run")
            # AgentLoop emits one event per state transition; the history is append-only.
            event = events[-1]
            connection.execute("insert into agent_run_events values (?, ?, ?)",
                               (record.run_id, event.seq, _json(event)))

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)
