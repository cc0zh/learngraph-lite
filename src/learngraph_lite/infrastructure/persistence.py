"""SQLite persistence adapters for local LearnGraph Lite state."""

from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from learngraph_lite.application.documents import ChunkSearchResult
from learngraph_lite.application.learning import LearningState
from learngraph_lite.application.planning import PlanningState
from learngraph_lite.domain.documents import Citation, Document, DocumentChunk, tokenize
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
                connection.execute(
                    """
                    insert into planning_states(goal_id, goal_json, graph_json, clarification_round)
                    values (?, ?, ?, ?)
                    on conflict(goal_id) do update set
                        goal_json = excluded.goal_json,
                        graph_json = excluded.graph_json,
                        clarification_round = excluded.clarification_round
                    """,
                    (
                        goal_id,
                        json.dumps(_goal_to_json(state.goal), ensure_ascii=False, sort_keys=True),
                        json.dumps(_graph_to_json(state.graph), ensure_ascii=False, sort_keys=True) if state.graph else None,
                        state.clarification_round,
                    ),
                )

    def get(self, goal_id: str) -> PlanningState:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "select goal_json, graph_json, clarification_round from planning_states where goal_id = ?",
                (goal_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown goal: {goal_id}")
        goal_json, graph_json, clarification_round = row
        return PlanningState(
            goal=_goal_from_json(json.loads(goal_json)),
            graph=_graph_from_json(json.loads(graph_json)) if graph_json else None,
            clarification_round=int(clarification_round),
        )

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    create table if not exists planning_states (
                        goal_id text primary key,
                        goal_json text not null,
                        graph_json text,
                        clarification_round integer not null
                    )
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)


class SQLiteDocumentRepository:
    """Persist documents, bindings and chunk search index with SQLite FTS5."""

    def __init__(self, database_path: str | Path):
        self._database_path = str(database_path)
        self._initialize()

    def save_document(self, document: Document, chunks: tuple[DocumentChunk, ...]) -> None:
        with closing(self._connect()) as connection:
            with connection:
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
                        page_number
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?)
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
                        )
                        for chunk in chunks
                    ),
                )
                connection.executemany(
                    "insert into document_chunks_fts(chunk_id, document_id, content) values (?, ?, ?)",
                    ((chunk.id, chunk.document_id, " ".join(tokenize(chunk.text))) for chunk in chunks),
                )

    def bind_to_goal(self, goal_id: str, document_id: str) -> None:
        with closing(self._connect()) as connection:
            self._require_document(connection, document_id)
            with connection:
                connection.execute(
                    "insert or ignore into goal_document_bindings(goal_id, document_id) values (?, ?)",
                    (goal_id, document_id),
                )

    def bind_to_node(self, goal_id: str, node_id: str, document_id: str) -> None:
        with closing(self._connect()) as connection:
            self._require_document(connection, document_id)
            if not self._is_bound_to_goal(connection, goal_id, document_id):
                raise ValueError("document must be bound to goal before binding to node")
            with connection:
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

    def search_chunks(self, document_ids: set[str], query_tokens: set[str], limit: int) -> tuple[ChunkSearchResult, ...]:
        if not document_ids or limit <= 0:
            return ()
        match_query = _fts_match_query(query_tokens)
        if not match_query:
            return ()
        placeholders = ",".join("?" for _ in document_ids)
        params = [match_query, *sorted(document_ids)]
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
                    chunks.page_number
                from document_chunks_fts as fts
                join document_chunks as chunks on chunks.chunk_id = fts.chunk_id
                where document_chunks_fts match ?
                    and chunks.document_id in ({placeholders})
                """,
                params,
            ).fetchall()
        results: list[ChunkSearchResult] = []
        for row in rows:
            chunk = _chunk_from_row(row)
            chunk_tokens = tokenize(chunk.text)
            chunk_text = chunk.text.casefold()
            score = sum(1 for token in query_tokens if token in chunk_tokens or token in chunk_text)
            if score > 0:
                results.append(ChunkSearchResult(chunk=chunk, score=score))
        results.sort(key=lambda result: (-result.score, result.chunk.document_id, result.chunk.index))
        return tuple(results[:limit])

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
                select chunk_id, document_id, document_version, chunk_index, text, start_offset, end_offset, page_number
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
                        foreign key(document_id) references documents(document_id)
                    )
                    """
                )
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
                connection.execute(
                    """
                    create virtual table if not exists document_chunks_fts
                    using fts5(chunk_id unindexed, document_id unindexed, content)
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)

    def _require_document(self, connection: sqlite3.Connection, document_id: str) -> None:
        row = connection.execute("select 1 from documents where document_id = ?", (document_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown document: {document_id}")

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
        with closing(self._connect()) as connection:
            with connection:
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
                        normalized_hash
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        with closing(self._connect()) as connection:
            state_row = connection.execute(
                "select graph_json, run_ids_json from learning_states where goal_id = ?",
                (goal_id,),
            ).fetchone()
            if state_row is None:
                raise KeyError(f"unknown learning goal: {goal_id}")
            exercise_rows = connection.execute(
                """
                select exercise_id, node_id, graph_content_revision, prompt, options_json,
                    correct_option_id, explanation, normalized_hash
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
                        primary key(goal_id, exercise_id)
                    )
                    """
                )
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
    }


def _graph_from_json(data: dict) -> GraphSnapshot:
    return GraphSnapshot(
        goal_id=data["goal_id"],
        nodes=tuple(GraphNode(**node) for node in data.get("nodes", ())),
        edges=tuple(GraphEdge(**edge) for edge in data.get("edges", ())),
        status=GraphStatus(data["status"]),
        revision=int(data.get("revision", 0)),
        content_revision=int(data.get("content_revision", 0)),
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
    )


def _fts_match_query(query_tokens: set[str]) -> str:
    tokens = sorted(token for token in query_tokens if token)
    return " OR ".join(f'"{token}"' for token in tokens)


def _learning_run_maps(data: str) -> tuple[dict[str, str], dict[str, str]]:
    payload = json.loads(data)
    if "run_ids_by_key" in payload:
        return dict(payload["run_ids_by_key"]), dict(payload.get("final_text_by_key", {}))
    return dict(payload), {}
