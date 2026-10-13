"""SQLite persistence adapters for local LearnGraph Lite state."""

from __future__ import annotations

from contextlib import closing
import json
import hashlib
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from learngraph_lite.application.documents import ChunkSearchResult, DocumentAccessError
from learngraph_lite.application.document_imports import UploadRecord
from learngraph_lite.application.learning import LearningState
from learngraph_lite.application.lessons import LessonState
from learngraph_lite.application.planning import PlanningError, PlanningState
from learngraph_lite.domain.documents import Citation, Document, DocumentChunk, DocumentKind, tokenize
from learngraph_lite.domain.lessons import ComponentKind, LessonComponent, LessonEvent, LessonPackage
from learngraph_lite.domain.learning import Attempt, ExerciseOption, ExercisePrivate, GoalDraft, GraphEdge, GraphNode, GraphSnapshot, GraphStatus


class SQLitePlanningRepository:
    """Persist goal planning state with the Python standard library.

    This is the first narrow SQLite adapter. It intentionally covers only the
    planning state already exercised by the application layer: goal draft,
    clarification round and the current graph snapshot.
    """

    def __init__(self, database_path: str | Path):
        self._database_path = str(database_path)
        self._initialize()

    def save(self, goal_id: str, state: PlanningState) -> None:
        with closing(self._connect()) as connection:
            with connection:
                self._save(connection, goal_id, state)

    def _save(self, connection, goal_id, state):
        connection.execute(
            """insert into planning_states(goal_id, goal_json, graph_json, clarification_round, version, questions_json)
            values (?, ?, ?, ?, ?, ?)
            on conflict(goal_id) do update set goal_json=excluded.goal_json, graph_json=excluded.graph_json,
                clarification_round=excluded.clarification_round, version=excluded.version,
                questions_json=excluded.questions_json""",
            (goal_id, json.dumps(_goal_to_json(state.goal), ensure_ascii=False, sort_keys=True),
             json.dumps(_graph_to_json(state.graph), ensure_ascii=False, sort_keys=True) if state.graph else None,
             state.clarification_round, state.version, json.dumps(state.questions, ensure_ascii=False)),
        )

    def get(self, goal_id: str) -> PlanningState:
        with closing(self._connect()) as connection:
            return self._get(connection, goal_id)

    def _get(self, connection, goal_id):
        row = connection.execute(
            "select goal_json, graph_json, clarification_round, version, questions_json from planning_states where goal_id = ?",
            (goal_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown goal: {goal_id}")
        goal_json, graph_json, clarification_round, version, questions_json = row
        return PlanningState(
            goal=_goal_from_json(json.loads(goal_json)),
            graph=_graph_from_json(json.loads(graph_json)) if graph_json else None,
            clarification_round=int(clarification_round),
            version=int(version), questions=tuple(json.loads(questions_json)),
        )

    def create(self, goal_id: str, state: PlanningState) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute("select 1 from planning_states where goal_id=?", (goal_id,)).fetchone():
                    raise PlanningError("goal_exists", "Goal already exists.")
                self._save(connection, goal_id, state)

    def list_ids(self) -> tuple[str, ...]:
        with closing(self._connect()) as connection:
            return tuple(row[0] for row in connection.execute("select goal_id from planning_states order by goal_id"))

    def mutate(self, goal_id, update):
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                state = self._get(connection, goal_id)
                result = update(state)
                state.version += 1
                self._save(connection, goal_id, state)
                return result

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    create table if not exists planning_states (
                        goal_id text primary key,
                        goal_json text not null,
                        graph_json text,
                        clarification_round integer not null,
                        version integer not null default 0,
                        questions_json text not null default '[]'
                    )
                    """
                )
                columns = {row[1] for row in connection.execute("pragma table_info(planning_states)")}
                if "version" not in columns:
                    connection.execute("alter table planning_states add column version integer not null default 0")
                if "questions_json" not in columns:
                    connection.execute("alter table planning_states add column questions_json text not null default '[]'")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)


class SQLiteDocumentRepository:
    """Persist documents, bindings and chunk search index with SQLite FTS5."""

    def __init__(self, database_path: str | Path):
        self._database_path = str(database_path)
        self._initialize()

    def save_document(self, document: Document, chunks: tuple[DocumentChunk, ...]) -> None:
        with closing(self._connect()) as connection, connection:
            self._save_document(connection, document, chunks)

    def _save_document(self, connection: sqlite3.Connection, document: Document,
                       chunks: tuple[DocumentChunk, ...]) -> None:
        connection.execute(
            """
            insert into documents(document_id, title, kind, text, version)
            values (?, ?, ?, ?, ?)
            on conflict(document_id) do update set
                title = excluded.title,
                kind = excluded.kind,
                text = excluded.text,
                version = excluded.version
            """,
            (document.id, document.title, document.kind.value, document.text, document.version),
        )
        connection.execute("delete from document_chunks where document_id = ?", (document.id,))
        connection.execute("delete from document_chunks_fts where document_id = ?", (document.id,))
        connection.executemany(
            """
            insert into document_chunks(
                chunk_id,
                document_id,
                document_version,
                chunk_index,
                text,
                start_offset,
                end_offset,
                page_number,
                text_hash,
                heading
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    chunk.id,
                    chunk.document_id,
                    chunk.document_version,
                    chunk.index,
                    chunk.text,
                    chunk.start_offset,
                    chunk.end_offset,
                    chunk.page_number,
                    hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
                    chunk.heading,
                )
                for chunk in chunks
            ),
        )
        connection.executemany(
            "insert into document_chunks_fts(chunk_id, document_id, content) values (?, ?, ?)",
            ((chunk.id, chunk.document_id, " ".join(tokenize(chunk.text))) for chunk in chunks),
        )

    def bind_to_goal(self, goal_id: str, document_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("begin immediate")
            self._require_document(connection, document_id)
            connection.execute(
                "insert or ignore into goal_document_bindings(goal_id, document_id) values (?, ?)",
                (goal_id, document_id),
            )

    def bind_to_node(self, goal_id: str, node_id: str, document_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("begin immediate")
            self._require_document(connection, document_id)
            if not self._is_bound_to_goal(connection, goal_id, document_id):
                raise DocumentAccessError("goal_binding_required", "document must be bound to goal before binding to node")
            connection.execute(
                """
                insert or ignore into node_document_bindings(goal_id, node_id, document_id)
                values (?, ?, ?)
                """,
                (goal_id, node_id, document_id),
            )

    def bound_document_ids(self, goal_id: str, node_id: str | None = None) -> set[str]:
        with closing(self._connect()) as connection:
            if node_id is None:
                rows = connection.execute(
                    "select document_id from goal_document_bindings where goal_id = ?",
                    (goal_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    select goal_binding.document_id
                    from goal_document_bindings as goal_binding
                    join node_document_bindings as node_binding
                        on node_binding.goal_id = goal_binding.goal_id
                        and node_binding.document_id = goal_binding.document_id
                    where goal_binding.goal_id = ? and node_binding.node_id = ?
                    """,
                    (goal_id, node_id),
                ).fetchall()
        return {row[0] for row in rows}

    def unbind_from_goal(self, goal_id: str, document_id: str) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("delete from node_document_bindings where goal_id = ? and document_id = ?",
                                   (goal_id, document_id))
                connection.execute("delete from goal_document_bindings where goal_id = ? and document_id = ?",
                                   (goal_id, document_id))

    def unbind_from_node(self, goal_id: str, node_id: str, document_id: str) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("delete from node_document_bindings where goal_id = ? and node_id = ? and document_id = ?",
                                   (goal_id, node_id, document_id))

    def search_chunks(self, document_ids: set[str], query_tokens: set[str], limit: int) -> tuple[ChunkSearchResult, ...]:
        if not document_ids or limit <= 0:
            return ()
        match_query = _fts_match_query(query_tokens)
        if not match_query:
            return ()
        placeholders = ",".join("?" for _ in document_ids)
        params = [match_query, *sorted(document_ids), limit]
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                select chunks.chunk_id,
                    chunks.document_id,
                    chunks.document_version,
                    chunks.chunk_index,
                    chunks.text,
                    chunks.start_offset,
                    chunks.end_offset,
                    chunks.page_number, chunks.heading,
                    bm25(document_chunks_fts) as rank
                from document_chunks_fts as fts
                join document_chunks as chunks on chunks.chunk_id = fts.chunk_id
                where document_chunks_fts match ?
                    and chunks.document_id in ({placeholders})
                    and not exists (select 1 from document_uploads as uploads
                                    where uploads.document_id = chunks.document_id and uploads.status != 'ready')
                order by rank, chunks.document_id, chunks.chunk_index
                limit ?
                """,
                params,
            ).fetchall()
        return tuple(ChunkSearchResult(chunk=_chunk_from_row(row), score=-float(row[9])) for row in rows)

    def resolve_citation(self, citation: Citation) -> DocumentChunk:
        with closing(self._connect()) as connection:
            document_row = connection.execute(
                "select version from documents where document_id = ?",
                (citation.document_id,),
            ).fetchone()
            if document_row is None:
                raise ValueError("unknown citation document")
            if int(document_row[0]) != citation.document_version:
                raise ValueError("citation document version is stale")
            chunk_row = connection.execute(
                """
                select chunk_id, document_id, document_version, chunk_index, text, start_offset, end_offset, page_number, heading
                from document_chunks
                where chunk_id = ? and document_id = ? and document_version = ?
                """,
                (citation.chunk_id, citation.document_id, citation.document_version),
            ).fetchone()
        if chunk_row is None:
            raise ValueError("citation chunk is missing")
        return _chunk_from_row(chunk_row)

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("""create table if not exists document_uploads (
                    document_id text primary key, filename text not null, kind text, status text not null,
                    size_bytes integer not null, content_hash text not null, revision integer not null,
                    reason text, original blob not null)""")
                connection.execute(
                    """
                    create table if not exists documents (
                        document_id text primary key,
                        title text not null,
                        kind text not null,
                        text text not null,
                        version integer not null
                    )
                    """
                )
                connection.execute(
                    """
                    create table if not exists document_chunks (
                        chunk_id text primary key,
                        document_id text not null,
                        document_version integer not null,
                        chunk_index integer not null,
                        text text not null,
                        start_offset integer not null,
                        end_offset integer not null,
                        page_number integer,
                        text_hash text,
                        heading text,
                        foreign key(document_id) references documents(document_id)
                    )
                    """
                )
                columns = {row[1] for row in connection.execute("pragma table_info(document_chunks)")}
                if "text_hash" not in columns:
                    connection.execute("alter table document_chunks add column text_hash text")
                if "heading" not in columns:
                    connection.execute("alter table document_chunks add column heading text")
                for chunk_id, text in connection.execute("select chunk_id, text from document_chunks where text_hash is null").fetchall():
                    connection.execute("update document_chunks set text_hash = ? where chunk_id = ?",
                                       (hashlib.sha256(text.encode("utf-8")).hexdigest(), chunk_id))
                connection.execute(
                    """
                    create table if not exists goal_document_bindings (
                        goal_id text not null,
                        document_id text not null,
                        primary key(goal_id, document_id),
                        foreign key(document_id) references documents(document_id)
                    )
                    """
                )
                connection.execute(
                    """
                    create table if not exists node_document_bindings (
                        goal_id text not null,
                        node_id text not null,
                        document_id text not null,
                        primary key(goal_id, node_id, document_id),
                        foreign key(document_id) references documents(document_id)
                    )
                    """
                )
                try:
                    connection.execute("""create virtual table if not exists document_chunks_fts
                        using fts5(chunk_id unindexed, document_id unindexed, content)""")
                except sqlite3.OperationalError as exc:
                    raise RuntimeError("SQLite FTS5 is required for document search; install Python 3.13+ with FTS5-enabled SQLite (see README).") from exc
                connection.execute("create table if not exists document_index_metadata (name text primary key, value text)")
                indexed = connection.execute("select value from document_index_metadata where name = 'tokenizer'").fetchone()
                if indexed is None or indexed[0] != 'jieba-0.42.1-search-v1':
                    connection.execute("delete from document_chunks_fts")
                    rows = connection.execute("select chunk_id, document_id, text from document_chunks").fetchall()
                    connection.executemany("insert into document_chunks_fts(chunk_id, document_id, content) values (?, ?, ?)",
                                           ((row[0], row[1], ' '.join(tokenize(row[2]))) for row in rows))
                    connection.execute("insert or replace into document_index_metadata values ('tokenizer', 'jieba-0.42.1-search-v1')")

    def create_upload(self, record: UploadRecord, original: bytes) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("insert into document_uploads values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (record.document_id, record.filename, record.kind, record.status, record.size_bytes,
                                record.content_hash, record.revision, record.reason, original))

    def get_upload(self, document_id: str) -> UploadRecord:
        with closing(self._connect()) as connection:
            row = connection.execute("""select document_id, filename, kind, status, size_bytes, content_hash,
                                        revision, reason from document_uploads where document_id = ?""",
                                     (document_id,)).fetchone()
        if row is None:
            raise KeyError(document_id)
        return UploadRecord(row[0], row[1], DocumentKind(row[2]) if row[2] else None, *row[3:])

    def original_bytes(self, document_id: str) -> bytes:
        with closing(self._connect()) as connection:
            row = connection.execute("select original from document_uploads where document_id = ?", (document_id,)).fetchone()
        if row is None:
            raise KeyError(document_id)
        return bytes(row[0])

    def transition_upload(self, document_id: str, expected: tuple[str, ...], status: str) -> bool:
        placeholders = ','.join('?' for _ in expected)
        with closing(self._connect()) as connection, connection:
            return connection.execute(f"update document_uploads set status = ?, reason = null where document_id = ? and status in ({placeholders})",
                                      (status, document_id, *expected)).rowcount == 1

    def finish_upload(self, document_id: str, status: str, reason: str | None,
                      document: Document | None = None, chunks: tuple[DocumentChunk, ...] = ()) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("begin immediate")
            changed = connection.execute("update document_uploads set status = ?, reason = ? where document_id = ? and status = 'parsing'",
                                         (status, reason, document_id)).rowcount
            # Deletion or restart recovery must not be undone by a late worker.
            if changed and document is not None:
                self._save_document(connection, document, chunks)

    def recover_uploads(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("update document_uploads set status = 'failed', reason = 'interrupted' where status in ('uploaded', 'parsing')")

    def document_chunks(self, document_id: str) -> tuple[DocumentChunk, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute("""select chunk_id, document_id, document_version, chunk_index, text,
                start_offset, end_offset, page_number, heading from document_chunks where document_id = ? order by chunk_index""",
                                      (document_id,)).fetchall()
        return tuple(_chunk_from_row(row) for row in rows)

    def delete_document(self, document_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            for table in ('document_chunks_fts', 'document_chunks', 'node_document_bindings',
                          'goal_document_bindings', 'documents', 'document_uploads'):
                connection.execute(f"delete from {table} where document_id = ?", (document_id,))

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)

    def _require_document(self, connection: sqlite3.Connection, document_id: str) -> None:
        row = connection.execute("select 1 from documents where document_id = ?", (document_id,)).fetchone()
        if row is None:
            raise DocumentAccessError("document_not_found", f"unknown document: {document_id}")
        upload = connection.execute("select status from document_uploads where document_id = ?", (document_id,)).fetchone()
        if upload and upload[0] != "ready":
            raise DocumentAccessError("document_not_ready", "Document is not ready.")

    def _is_bound_to_goal(self, connection: sqlite3.Connection, goal_id: str, document_id: str) -> bool:
        row = connection.execute(
            "select 1 from goal_document_bindings where goal_id = ? and document_id = ?",
            (goal_id, document_id),
        ).fetchone()
        return row is not None


class SQLiteLearningRepository:
    """Persist learning graph, private exercises and attempts with SQLite."""

    def __init__(self, database_path: str | Path):
        self._database_path = str(database_path)
        self._initialize()

    def save(self, goal_id: str, state: LearningState) -> None:
        with closing(self._connect()) as connection, connection:
            self._save(connection, goal_id, state)

    def mutate(self, goal_id: str, update):
        with closing(self._connect()) as connection, connection:
            connection.execute("begin immediate")
            state = self._get(connection, goal_id)
            result = update(state)
            self._save(connection, goal_id, state)
            return result

    def _save(self, connection: sqlite3.Connection, goal_id: str, state: LearningState) -> None:
        connection.execute(
            """
            insert into learning_states(goal_id, graph_json, run_ids_json)
            values (?, ?, ?)
            on conflict(goal_id) do update set
                graph_json = excluded.graph_json,
                run_ids_json = excluded.run_ids_json
            """,
            (
                goal_id,
                json.dumps(_graph_to_json(state.graph), ensure_ascii=False, sort_keys=True),
                json.dumps(
                    {
                        "run_ids_by_key": state.run_ids_by_key,
                        "final_text_by_key": state.final_text_by_key,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )
        connection.execute("delete from learning_generation_operations where goal_id = ?", (goal_id,))
        connection.executemany(
            """
            insert into learning_generation_operations(goal_id, operation_key, fingerprint, exercise_ids_json)
            values (?, ?, ?, ?)
            """,
            ((goal_id, key, operation["fingerprint"], json.dumps(operation["ids"]))
             for key, operation in state.generation_operations.items()),
        )
        connection.execute("delete from learning_exercises where goal_id = ?", (goal_id,))
        connection.executemany(
            """
            insert into learning_exercises(
                goal_id,
                exercise_id,
                node_id,
                graph_content_revision,
                prompt,
                options_json,
                correct_option_id,
                explanation,
                normalized_hash,
                sources_json
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    goal_id,
                    exercise.id,
                    exercise.node_id,
                    exercise.graph_content_revision,
                    exercise.prompt,
                    json.dumps([asdict(option) for option in exercise.options], ensure_ascii=False, sort_keys=True),
                    exercise.correct_option_id,
                    exercise.explanation,
                    exercise.normalized_hash,
                    json.dumps({"source_mode": exercise.source_mode, "citation_ids": exercise.citation_ids,
                                "citation_map": exercise.citation_map}, ensure_ascii=False, sort_keys=True),
                )
                for exercise in state.exercises.values()
            ),
        )
        connection.execute("delete from learning_attempts where goal_id = ?", (goal_id,))
        connection.executemany(
            """
            insert into learning_attempts(
                goal_id,
                attempt_id,
                exercise_id,
                node_id,
                selected_option_id,
                is_correct,
                counted,
                created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    goal_id,
                    attempt.id,
                    attempt.exercise_id,
                    attempt.node_id,
                    attempt.selected_option_id,
                    1 if attempt.is_correct else 0,
                    1 if attempt.counted else 0,
                    attempt.created_at.isoformat(),
                )
                for attempt in state.attempts
            ),
        )

    def get(self, goal_id: str) -> LearningState:
        with closing(self._connect()) as connection, connection:
            connection.execute("begin")
            return self._get(connection, goal_id)

    def _get(self, connection: sqlite3.Connection, goal_id: str) -> LearningState:
        state_row = connection.execute(
            "select graph_json, run_ids_json from learning_states where goal_id = ?",
            (goal_id,),
        ).fetchone()
        if state_row is None:
            raise KeyError(f"unknown learning goal: {goal_id}")
        exercise_rows = connection.execute(
            """
            select exercise_id, node_id, graph_content_revision, prompt, options_json,
                correct_option_id, explanation, normalized_hash, sources_json
            from learning_exercises
            where goal_id = ?
            order by exercise_id
            """,
            (goal_id,),
        ).fetchall()
        attempt_rows = connection.execute(
            """
            select attempt_id, exercise_id, node_id, selected_option_id, is_correct, counted, created_at
            from learning_attempts
            where goal_id = ?
            order by rowid
            """,
            (goal_id,),
        ).fetchall()
        exercises = {
            row[0]: ExercisePrivate(
                id=row[0],
                goal_id=goal_id,
                node_id=row[1],
                graph_content_revision=int(row[2]),
                prompt=row[3],
                options=tuple(ExerciseOption(**option) for option in json.loads(row[4])),
                correct_option_id=row[5],
                explanation=row[6],
                normalized_hash=row[7],
                source_mode=json.loads(row[8]).get("source_mode", "general"),
                citation_ids=tuple(json.loads(row[8]).get("citation_ids", ())),
                citation_map=json.loads(row[8]).get("citation_map", {}),
            )
            for row in exercise_rows
        }
        attempts = [
            Attempt(
                id=row[0],
                exercise_id=row[1],
                goal_id=goal_id,
                node_id=row[2],
                selected_option_id=row[3],
                is_correct=bool(row[4]),
                counted=bool(row[5]),
                created_at=datetime.fromisoformat(row[6]),
            )
            for row in attempt_rows
        ]
        run_ids_by_key, final_text_by_key = _learning_run_maps(state_row[1])
        return LearningState(
            graph=_graph_from_json(json.loads(state_row[0])),
            exercises=exercises,
            attempts=attempts,
            run_ids_by_key=run_ids_by_key,
            final_text_by_key=final_text_by_key,
            generation_operations={row[0]: {"fingerprint": row[1], "ids": json.loads(row[2])}
                                   for row in connection.execute(
                                       "select operation_key, fingerprint, exercise_ids_json "
                                       "from learning_generation_operations where goal_id = ?", (goal_id,))},
        )

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    create table if not exists learning_states (
                        goal_id text primary key,
                        graph_json text not null,
                        run_ids_json text not null
                    )
                    """
                )
                connection.execute(
                    """
                    create table if not exists learning_exercises (
                        goal_id text not null,
                        exercise_id text not null,
                        node_id text not null,
                        graph_content_revision integer not null,
                        prompt text not null,
                        options_json text not null,
                        correct_option_id text not null,
                        explanation text not null,
                        normalized_hash text not null,
                        sources_json text not null default '{}',
                        primary key(goal_id, exercise_id)
                    )
                    """
                )
                exercise_columns = {row[1] for row in connection.execute("pragma table_info(learning_exercises)")}
                if "sources_json" not in exercise_columns:
                    connection.execute("alter table learning_exercises add column sources_json text not null default '{}'")
                connection.execute(
                    """
                    create table if not exists learning_attempts (
                        goal_id text not null,
                        attempt_id text not null,
                        exercise_id text not null,
                        node_id text not null,
                        selected_option_id text not null,
                        is_correct integer not null,
                        counted integer not null,
                        created_at text not null,
                        primary key(goal_id, attempt_id)
                    )
                    """
                )

                connection.execute(
                    """
                    create table if not exists learning_generation_operations (
                        goal_id text not null,
                        operation_key text not null,
                        fingerprint text not null,
                        exercise_ids_json text not null,
                        primary key(goal_id, operation_key)
                    )
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)


class SQLiteLessonRepository:
    """Persist declarative lesson packages, events and explanation idempotency."""

    def __init__(self, database_path: str | Path):
        self._database_path = str(database_path)
        self._initialize()

    def state(self, goal_id: str) -> LessonState:
        with closing(self._connect()) as connection:
            package_rows = connection.execute(
                """
                select package_id, node_id, graph_content_revision, markdown, components_json
                from lesson_packages
                where goal_id = ?
                order by package_id
                """,
                (goal_id,),
            ).fetchall()
            event_rows = connection.execute(
                """
                select event_id, package_id, component_id, action, payload_json
                from lesson_events
                where goal_id = ?
                order by event_id
                """,
                (goal_id,),
            ).fetchall()
            explanation_rows = connection.execute(
                """
                select event_id, slot, run_id, failed
                from lesson_explanations
                where goal_id = ?
                order by event_id, slot
                """,
                (goal_id,),
            ).fetchall()
        packages = {
            row[0]: LessonPackage(
                id=row[0],
                goal_id=goal_id,
                node_id=row[1],
                graph_content_revision=int(row[2]),
                markdown=row[3],
                components=tuple(
                    LessonComponent(id=item["id"], kind=ComponentKind(item["kind"]), props=dict(item["props"]))
                    for item in json.loads(row[4])
                ),
            )
            for row in package_rows
        }
        events = {
            row[0]: LessonEvent(
                id=row[0],
                package_id=row[1],
                component_id=row[2],
                action=row[3],
                payload=dict(json.loads(row[4])),
            )
            for row in event_rows
        }
        explanation_runs = {
            (row[0], row[1]): row[2]
            for row in explanation_rows
            if row[2] is not None and not bool(row[3])
        }
        failed_explanations = {
            (row[0], row[1])
            for row in explanation_rows
            if bool(row[3])
        }
        return LessonState(
            packages=packages,
            events=events,
            explanation_runs=explanation_runs,
            failed_explanations=failed_explanations,
        )

    def save(self, goal_id: str, state: LessonState) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("delete from lesson_packages where goal_id = ?", (goal_id,))
                connection.execute("delete from lesson_events where goal_id = ?", (goal_id,))
                connection.execute("delete from lesson_explanations where goal_id = ?", (goal_id,))
                connection.executemany(
                    """
                    insert into lesson_packages(
                        goal_id,
                        package_id,
                        node_id,
                        graph_content_revision,
                        markdown,
                        components_json
                    )
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            goal_id,
                            package.id,
                            package.node_id,
                            package.graph_content_revision,
                            package.markdown,
                            json.dumps(
                                [
                                    {
                                        "id": component.id,
                                        "kind": component.kind.value,
                                        "props": component.props,
                                    }
                                    for component in package.components
                                ],
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                        )
                        for package in state.packages.values()
                    ),
                )
                connection.executemany(
                    """
                    insert into lesson_events(goal_id, event_id, package_id, component_id, action, payload_json)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            goal_id,
                            event.id,
                            event.package_id,
                            event.component_id,
                            event.action,
                            json.dumps(event.payload, ensure_ascii=False, sort_keys=True),
                        )
                        for event in state.events.values()
                    ),
                )
                explanation_keys = set(state.explanation_runs) | state.failed_explanations
                connection.executemany(
                    """
                    insert into lesson_explanations(goal_id, event_id, slot, run_id, failed)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            goal_id,
                            event_id,
                            slot,
                            state.explanation_runs.get((event_id, slot)),
                            1 if (event_id, slot) in state.failed_explanations else 0,
                        )
                        for event_id, slot in sorted(explanation_keys)
                    ),
                )

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    create table if not exists lesson_packages (
                        goal_id text not null,
                        package_id text not null,
                        node_id text not null,
                        graph_content_revision integer not null,
                        markdown text not null,
                        components_json text not null,
                        primary key(goal_id, package_id)
                    )
                    """
                )
                connection.execute(
                    """
                    create table if not exists lesson_events (
                        goal_id text not null,
                        event_id text not null,
                        package_id text not null,
                        component_id text not null,
                        action text not null,
                        payload_json text not null,
                        primary key(goal_id, event_id)
                    )
                    """
                )
                connection.execute(
                    """
                    create table if not exists lesson_explanations (
                        goal_id text not null,
                        event_id text not null,
                        slot text not null,
                        run_id text,
                        failed integer not null,
                        primary key(goal_id, event_id, slot)
                    )
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)


def _goal_to_json(goal: GoalDraft) -> dict:
    data = asdict(goal)
    data["document_ids"] = list(goal.document_ids)
    data["assumptions"] = list(goal.assumptions)
    return data


def _goal_from_json(data: dict) -> GoalDraft:
    return GoalDraft(
        title=data["title"],
        desired_outcome=data.get("desired_outcome", ""),
        current_level=data.get("current_level", ""),
        time_budget_minutes=data.get("time_budget_minutes"),
        constraints=data.get("constraints", ""),
        document_ids=tuple(data.get("document_ids", ())),
        assumptions=tuple(data.get("assumptions", ())),
        confirmed=bool(data.get("confirmed", False)),
    )


def _graph_to_json(graph: GraphSnapshot | None) -> dict | None:
    if graph is None:
        return None
    return {
        "goal_id": graph.goal_id,
        "nodes": [asdict(node) for node in graph.nodes],
        "edges": [asdict(edge) for edge in graph.edges],
        "status": graph.status.value,
        "revision": graph.revision,
        "content_revision": graph.content_revision,
        "source_mode": graph.source_mode,
        "citation_map": graph.citation_map,
    }


def _graph_from_json(data: dict) -> GraphSnapshot:
    return GraphSnapshot(
        goal_id=data["goal_id"],
        nodes=tuple(GraphNode(**{**node, "citation_ids": tuple(node.get("citation_ids", ()))})
                    for node in data.get("nodes", ())),
        edges=tuple(GraphEdge(**edge) for edge in data.get("edges", ())),
        status=GraphStatus(data["status"]),
        revision=int(data.get("revision", 0)),
        content_revision=int(data.get("content_revision", 0)),
        source_mode=data.get("source_mode", "general"),
        citation_map=data.get("citation_map", {}),
    )


def _chunk_from_row(row: sqlite3.Row | tuple) -> DocumentChunk:
    return DocumentChunk(
        id=row[0],
        document_id=row[1],
        document_version=int(row[2]),
        index=int(row[3]),
        text=row[4],
        start_offset=int(row[5]),
        end_offset=int(row[6]),
        page_number=int(row[7]) if row[7] is not None else None,
        heading=row[8],
    )


def _fts_match_query(query_tokens: set[str]) -> str:
    tokens = sorted(token for token in query_tokens if token)
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)


def _learning_run_maps(data: str) -> tuple[dict[str, str], dict[str, str]]:
    payload = json.loads(data)
    if "run_ids_by_key" in payload:
        return dict(payload["run_ids_by_key"]), dict(payload.get("final_text_by_key", {}))
    return dict(payload), {}
