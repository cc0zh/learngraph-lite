"""HTTP lifecycle adapter; model execution and terminal state belong to AgentLoop."""

from __future__ import annotations

import asyncio
import math
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Callable, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from learngraph_lite.application.agent import AgentLoop, RunAdmissionError, RunRequest, TERMINAL_STATUSES
from learngraph_lite.application.documents import DocumentAccessError
from learngraph_lite.application.document_imports import DocumentImports, MAX_UPLOAD_BYTES
from learngraph_lite.application.exercise_generation import ExerciseError, GenerateExercise
from learngraph_lite.application.lesson_generation import GenerateLesson, LessonInput
from learngraph_lite.application.lessons import LessonError, LessonService
from learngraph_lite.application.learning_agent import LearningContext, LearningContextError
from learngraph_lite.application.planning import PlanningError, PlanningService
from learngraph_lite.application.planning_generation import CandidateGraph
from learngraph_lite.domain.learning import GoalDraft, GraphSnapshot, GraphValidationError, RevisionConflict
from learngraph_lite.domain.lessons import LessonComponent, LessonEvent
from learngraph_lite.presentation.sse import encode_snapshot, encode_sse, public_run


Identifier = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=128)]


class SubmitRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: Identifier
    user_text: str | None = Field(default=None, strict=True, min_length=1, max_length=16000)
    goal_id: Identifier | None = None
    node_id: Identifier | None = None
    mode: Literal["runner", "teaching", "explanation"] = "runner"
    retry_of_run_id: Identifier | None = None
    source_event_id: Identifier | None = None
    explanation_slot: Identifier | None = None

    @field_validator("user_text")
    @classmethod
    def nonempty_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("user_text must contain text")
        return value

    @model_validator(mode="after")
    def valid_input(self):
        if self.mode == "explanation":
            if any(value is None for value in (self.goal_id, self.node_id, self.source_event_id, self.explanation_slot)):
                raise ValueError("Explanation requires goal, node, event and slot.")
            if self.user_text is not None:
                raise ValueError("Explanation input is constructed by the server.")
        elif self.user_text is None or self.source_event_id is not None or self.explanation_slot is not None:
            raise ValueError("Ordinary runs require user_text and no explanation reference.")
        return self


class AnswerSource(BaseModel):
    id: str
    document_id: str
    document_version: int
    chunk_id: str
    quote: str
    start_offset: int
    end_offset: int
    page_number: int | None = None
    heading: str | None = None
    text_hash: str
    status: Literal["valid", "stale", "unavailable"]
    cited: bool


class PublicOption(BaseModel):
    id: str
    text: str


class PublicExercise(BaseModel):
    id: str
    goal_id: str
    node_id: str
    graph_content_revision: int
    prompt: str
    options: list[PublicOption]
    source_mode: Literal["general", "documents"] = "general"
    citation_ids: list[str] = Field(default_factory=list)
    citation_map: dict[str, AnswerSource] = Field(default_factory=dict)
    unverified_citation_ids: list[str] = Field(default_factory=list)


class PublicLesson(BaseModel):
    id: str
    goal_id: str
    node_id: str
    graph_content_revision: int
    schema_version: int
    version: int
    title: str
    markdown: str
    components: list[LessonComponent]
    source_mode: Literal["general", "documents"]
    citation_ids: list[str]
    citation_map: dict[str, AnswerSource]
    unverified_citation_ids: list[str]
    outdated: bool


class PlanningView(BaseModel):
    goal_id: str
    goal: GoalDraft
    graph: GraphSnapshot | None
    clarification_round: int
    version: int
    questions: list[str]


class CreateGoal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    desired_outcome: str = Field(default="", max_length=2000)
    current_level: str = Field(default="", max_length=2000)
    time_budget_minutes: int | None = Field(default=None, ge=1)
    constraints: str = Field(default="", max_length=2000)
    document_ids: list[Identifier] = Field(default_factory=list, max_length=30)


class EditGoal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=0)
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)] | None = None
    desired_outcome: str | None = Field(default=None, max_length=2000)
    current_level: str | None = Field(default=None, max_length=2000)
    time_budget_minutes: int | None = Field(default=None, ge=1)
    constraints: str | None = Field(default=None, max_length=2000)
    document_ids: list[Identifier] | None = Field(default=None, max_length=30)

    @model_validator(mode="before")
    @classmethod
    def reject_null_fields(cls, value):
        if isinstance(value, dict) and not (value.keys() - {"expected_version"}):
            raise ValueError("At least one goal field is required")
        if isinstance(value, dict) and any(item is None for name, item in value.items() if name != "time_budget_minutes"):
            raise ValueError("Only time_budget_minutes may be cleared with null")
        return value


class PlanningVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=0)


class PlanningTask(PlanningVersion):
    request_id: Identifier
    retry_of_run_id: Identifier | None = None


class GraphTask(PlanningTask):
    node_count: int = Field(default=10, ge=1, le=30)


class EditGraph(CandidateGraph):
    expected_version: int = Field(ge=0)


class PublishGraph(PlanningVersion):
    expected_revision: int = Field(ge=0)


class AnswerSources(BaseModel):
    citation_map: dict[str, AnswerSource] = Field(default_factory=dict)
    unverified_citation_ids: list[str] = Field(default_factory=list)
    exercises: list[PublicExercise] | None = None
    source_mode: Literal["general", "documents"] | None = None
    planning: PlanningView | None = None
    lesson: PublicLesson | None = None


class SubmitExercises(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: Identifier
    request_id: Identifier
    count: int = Field(default=1, strict=True, ge=1, le=3)
    purpose: str = Field(default="practice", strict=True, min_length=1, max_length=2000)
    retry_of_run_id: Identifier | None = None


class SubmitAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_id: Identifier
    selected_option_id: Identifier


class SubmitLesson(LessonInput):
    session_id: Identifier
    request_id: Identifier
    retry_of_run_id: Identifier | None = None


class SubmitLessonEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event_id: Identifier
    package_version: int = Field(ge=1)
    component_id: Identifier
    action: Literal["mark_read", "step_changed", "request_explanation"]
    payload: dict = Field(default_factory=dict)


class PublicDocument(BaseModel):
    document_id: str
    filename: str
    kind: Literal["text", "markdown", "pdf_text"] | None
    status: Literal["uploaded", "parsing", "ready", "failed", "unsupported"]
    size_bytes: int
    content_hash: str
    revision: int
    reason: str | None


class DocumentBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    document_id: Identifier
    node_id: Identifier | None = None


class DocumentSearch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=500)
    node_id: Identifier | None = None
    limit: int = Field(default=5, ge=1, le=5)


class LocatedSource(BaseModel):
    source: AnswerSource
    text: str
    start_offset: int
    end_offset: int
    page_number: int | None = None
    heading: str | None = None


class PublicRun(BaseModel):
    user_text: str = ""
    mode: str = "runner"
    partial_text: str = ""
    tool_activity: dict[str, dict] = Field(default_factory=dict)
    run_id: str
    session_id: str
    root_task_id: str
    goal_id: str | None = None
    node_id: str | None = None
    task_ref: str | None = None
    status: Literal["queued", "running", "completed", "failed", "cancelled", "budget_exceeded", "interrupted"]
    summary: str
    created_at: datetime
    updated_at: datetime
    final_text: str | None = None
    error: str | None = None
    usage: dict[str, int] | None = None
    output: AnswerSources | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool
    run_id: str | None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


def _error(status: int, code: str, message: str, *, retryable: bool = False, run_id: str | None = None):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "retryable": retryable, "run_id": run_id}},
    )


def create_app(
    loop: AgentLoop,
    *,
    model_mode: Literal["fixture", "real"] = "fixture",
    model_configured: bool = False,
    heartbeat_seconds: float = 15.0,
    on_close: Callable[[], None] | None = None,
    learning_context: LearningContext | None = None,
    exercises: GenerateExercise | None = None,
    planning: PlanningService | None = None,
    on_publish: Callable[[GraphSnapshot], None] | None = None,
    document_imports: DocumentImports | None = None,
    lessons: GenerateLesson | None = None,
    lesson_events: LessonService | None = None,
) -> FastAPI:
    """Create a process-local API, with cooperative shutdown and snapshot-first SSE."""
    if not math.isfinite(heartbeat_seconds) or heartbeat_seconds <= 0:
        raise ValueError("heartbeat_seconds must be finite and positive")
    if model_mode not in {"fixture", "real"}:
        raise ValueError("model_mode must be fixture or real")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            try:
                await asyncio.to_thread(loop.close)
            finally:
                try:
                    if document_imports is not None:
                        await asyncio.to_thread(document_imports.close)
                finally:
                    if on_close is not None:
                        await asyncio.to_thread(on_close)

    app = FastAPI(
        title="LearnGraph Lite", version="0.1.0", lifespan=lifespan,
        responses={422: {"model": ErrorEnvelope}},
    )

    @app.middleware("http")
    async def local_request_boundary(request: Request, call_next):
        try:
            hostname = request.url.hostname
        except ValueError:
            hostname = None
        if hostname not in {"127.0.0.1", "localhost", "::1"}:
            return _error(400, "untrusted_host", "Only local hosts are allowed.")
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin is not None:
            expected_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
            if origin != expected_origin:
                return _error(403, "untrusted_origin", "Write requests must use the same origin.")
        return await call_next(request)

    @app.exception_handler(RunAdmissionError)
    async def admission_error(request: Request, exc: RunAdmissionError):
        status = {"session_busy": 409, "capacity_exceeded": 429, "idempotency_conflict": 409,
                  "shutting_down": 503, "storage_unavailable": 503, "invalid_scope": 422, "session_scope_conflict": 409, "invalid_retry": 409}
        return _error(
            status[exc.code], exc.code, str(exc),
            retryable=exc.code in {"session_busy", "capacity_exceeded", "shutting_down"},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return _error(422, "invalid_request", "Invalid request parameters.")

    @app.exception_handler(LearningContextError)
    async def learning_error(request: Request, exc: LearningContextError):
        status = 404 if exc.code in {"goal_not_found", "node_not_found"} else 409
        return _error(status, exc.code, str(exc))

    @app.exception_handler(DocumentAccessError)
    async def document_error(request: Request, exc: DocumentAccessError):
        statuses = {"document_not_found": 404, "node_not_found": 404, "upload_too_large": 413,
                    "source_not_found": 404,
                    "invalid_document_request": 422, "document_capacity_exceeded": 429, "shutting_down": 503}
        return _error(statuses.get(exc.code, 409), exc.code, str(exc),
                      retryable=exc.code in {"document_capacity_exceeded", "shutting_down"})

    @app.exception_handler(ExerciseError)
    async def exercise_error(request: Request, exc: ExerciseError):
        return _error(404 if exc.code == "exercise_not_found" else 409, exc.code, str(exc))

    @app.exception_handler(LessonError)
    async def lesson_error(request: Request, exc: LessonError):
        status = 404 if exc.code in {"lesson_not_found", "event_not_found"} else 422 if exc.code == "invalid_lesson_event" else 409
        return _error(status, exc.code, str(exc))

    @app.exception_handler(PlanningError)
    async def planning_error(request: Request, exc: PlanningError):
        return _error(404 if exc.code == "goal_not_found" else 409, exc.code, str(exc))

    @app.exception_handler(RevisionConflict)
    async def revision_error(request: Request, exc: RevisionConflict):
        return _error(409, "revision_conflict", str(exc))

    @app.exception_handler(GraphValidationError)
    async def graph_error(request: Request, exc: GraphValidationError):
        return _error(422, "invalid_graph", str(exc))

    if document_imports is not None:
        @app.post("/api/documents", status_code=202, response_model=PublicDocument)
        async def upload_document(file: Annotated[UploadFile, File()]):
            try:
                original = await file.read(MAX_UPLOAD_BYTES + 1)
                return await asyncio.to_thread(document_imports.upload, file.filename or "upload", original)
            finally:
                await file.close()

        @app.get("/api/documents/{document_id}", response_model=PublicDocument)
        def get_document(document_id: Identifier):
            return document_imports.get(document_id)

        @app.get("/api/documents/{document_id}/chunks")
        def get_chunks(document_id: Identifier, offset: Annotated[int, Query(ge=0)] = 0,
                       limit: Annotated[int, Query(ge=1, le=50)] = 50):
            return document_imports.chunks(document_id, offset=offset, limit=limit)

        @app.post("/api/documents/{document_id}/reparse", status_code=202, response_model=PublicDocument)
        def reparse_document(document_id: Identifier):
            return document_imports.reparse(document_id)

        @app.delete("/api/documents/{document_id}")
        def delete_document(document_id: Identifier):
            document_imports.delete(document_id)
            return {"deleted": True}

        @app.post("/api/goals/{goal_id}/document-bindings")
        def bind_document(goal_id: Identifier, body: DocumentBinding):
            return document_imports.bind(goal_id, body.document_id, body.node_id)

        @app.delete("/api/goals/{goal_id}/document-bindings")
        def unbind_document(goal_id: Identifier, body: DocumentBinding):
            return document_imports.bind(goal_id, body.document_id, body.node_id, remove=True)

        @app.post("/api/goals/{goal_id}/document-search")
        def search_documents(goal_id: Identifier, body: DocumentSearch):
            return document_imports.search(goal_id, body.query, node_id=body.node_id, limit=body.limit)

    if planning is not None:
        @app.get("/api/goals", response_model=list[PlanningView])
        def list_goals():
            return planning.list_goals()

        @app.post("/api/goals", status_code=201, response_model=PlanningView)
        def create_goal(body: CreateGoal):
            goal_id = str(uuid4())
            fields = body.model_dump()
            planning.create_goal(goal_id, fields.pop("title"), **fields)
            return planning.describe(goal_id)

        @app.get("/api/goals/{goal_id}", response_model=PlanningView)
        def get_goal(goal_id: Identifier):
            return planning.describe(goal_id)

        @app.patch("/api/goals/{goal_id}", response_model=PlanningView)
        def edit_goal(goal_id: Identifier, body: EditGoal):
            fields = body.model_dump(exclude_unset=True)
            version = fields.pop("expected_version")
            planning.edit_goal(goal_id, version, **fields)
            return planning.describe(goal_id)

        @app.post("/api/goals/{goal_id}/confirm", response_model=PlanningView)
        def confirm_goal(goal_id: Identifier, body: PlanningVersion):
            planning.confirm_goal(goal_id, body.expected_version)
            return planning.describe(goal_id)

        def planning_run(goal_id, body, mode):
            return public_run(loop.submit(RunRequest(
                session_id=f"planning:{goal_id}", task_ref=f"goal:{goal_id}", goal_id=goal_id,
                user_text="澄清目标" if mode == "clarify" else "生成图谱", mode=mode,
                idempotency_key=body.request_id, retry_of_run_id=body.retry_of_run_id,
                planning_version=body.expected_version, graph_node_count=getattr(body, "node_count", 10),
            )))

        @app.post("/api/goals/{goal_id}/clarify", status_code=202, response_model=PublicRun, response_model_exclude_unset=True)
        def clarify_goal(goal_id: Identifier, body: PlanningTask):
            return planning_run(goal_id, body, "clarify")

        @app.post("/api/goals/{goal_id}/graph-drafts", status_code=202, response_model=PublicRun, response_model_exclude_unset=True)
        def generate_graph(goal_id: Identifier, body: GraphTask):
            return planning_run(goal_id, body, "graph")

        @app.get("/api/goals/{goal_id}/graph", response_model=PlanningView)
        def get_graph(goal_id: Identifier):
            state = planning.get_state(goal_id)
            data = {"goal_id": goal_id, **asdict(state)}
            if learning_context is not None and state.graph is not None:
                data["graph"] = learning_context.project_graph_sources(state.graph)
            return data

        @app.patch("/api/goals/{goal_id}/graph", response_model=PlanningView)
        def edit_graph(goal_id: Identifier, body: EditGraph):
            try:
                graph = body.graph()
            except ValueError as exc:
                return _error(422, "invalid_graph", str(exc))
            planning.save_graph_draft(goal_id, graph.nodes, graph.edges, expected_version=body.expected_version)
            return planning.describe(goal_id)

        @app.post("/api/goals/{goal_id}/graph/publish", response_model=PlanningView)
        def publish_graph(goal_id: Identifier, body: PublishGraph):
            graph = planning.publish_graph(goal_id, body.expected_revision, body.expected_version)
            if on_publish is not None:
                on_publish(graph)
            return planning.describe(goal_id)

    if exercises is not None:
        @app.post("/api/goals/{goal_id}/nodes/{node_id}/exercises", status_code=202,
                  response_model=PublicRun, response_model_exclude_unset=True)
        def generate_exercises(goal_id: Identifier, node_id: Identifier, body: SubmitExercises):
            return public_run(loop.submit(RunRequest(
                session_id=body.session_id, user_text="生成练习", idempotency_key=body.request_id,
                mode="exercise", goal_id=goal_id, node_id=node_id,
                exercise_count=body.count, exercise_purpose=body.purpose,
                retry_of_run_id=body.retry_of_run_id,
            )))

        @app.get("/api/goals/{goal_id}/nodes/{node_id}/exercises")
        def list_exercises(goal_id: Identifier, node_id: Identifier):
            return exercises.list_exercises(goal_id, node_id)

        @app.get("/api/goals/{goal_id}/exercises/{exercise_id}", response_model=PublicExercise)
        def get_exercise(goal_id: Identifier, exercise_id: Identifier):
            return exercises.get_exercise(goal_id, exercise_id)

        @app.post("/api/goals/{goal_id}/exercises/{exercise_id}/attempts")
        def submit_answer(goal_id: Identifier, exercise_id: Identifier, body: SubmitAnswer):
            return exercises.submit_answer(goal_id, exercise_id, body.selected_option_id, body.submission_id)

    if lessons is not None:
        @app.post("/api/goals/{goal_id}/nodes/{node_id}/lessons", status_code=202,
                  response_model=PublicRun, response_model_exclude_unset=True)
        def generate_lesson(goal_id: Identifier, node_id: Identifier, body: SubmitLesson):
            return public_run(loop.submit(RunRequest(
                session_id=body.session_id, user_text="生成学习页", idempotency_key=body.request_id,
                mode="lesson", goal_id=goal_id, node_id=node_id, lesson_purpose=body.purpose,
                lesson_exercise_ids=tuple(body.exercise_ids), retry_of_run_id=body.retry_of_run_id,
            )))

        @app.get("/api/goals/{goal_id}/nodes/{node_id}/lessons")
        def list_lessons(goal_id: Identifier, node_id: Identifier):
            return lessons.list_packages(goal_id, node_id)

        @app.get("/api/goals/{goal_id}/lessons/{package_id}", response_model=PublicLesson)
        def get_lesson(goal_id: Identifier, package_id: Identifier):
            return lessons.get_package(goal_id, package_id)

        if lesson_events is not None:
            @app.post("/api/goals/{goal_id}/lessons/{package_id}/events")
            def lesson_event(goal_id: Identifier, package_id: Identifier, body: SubmitLessonEvent):
                accepted = lesson_events.ack_event(goal_id, LessonEvent(
                    body.event_id, package_id, body.component_id, body.action, body.payload, body.package_version))
                return {"event": asdict(accepted)}

    if learning_context is not None:
        def located(goal_id, node_id, source):
            chunk = learning_context.locate_run_source(goal_id, node_id, source)
            return {"source": {**source, "status": "valid"}, "text": chunk["text"],
                    "start_offset": chunk["start_offset"], "end_offset": chunk["end_offset"],
                    "page_number": chunk["page_number"], "heading": chunk["heading"]}

        if planning is not None:
            @app.get("/api/goals/{goal_id}/graph/citations/{citation_id}", response_model=LocatedSource)
            def locate_graph_citation(goal_id: Identifier, citation_id: Identifier,
                                      version: Annotated[int, Query(ge=0)]):
                state = planning.get_state(goal_id)
                if state.version != version:
                    return _error(409, "stale_graph_citation", "Graph version changed; refresh the artifact.")
                source = state.graph.citation_map.get(citation_id) if state.graph is not None else None
                if source is None:
                    return _error(404, "source_not_found", "Citation does not exist in this graph version.")
                return located(goal_id, None, source)

        if exercises is not None:
            @app.get("/api/goals/{goal_id}/exercises/{exercise_id}/citations/{citation_id}", response_model=LocatedSource)
            def locate_exercise_citation(goal_id: Identifier, exercise_id: Identifier, citation_id: Identifier):
                node_id, source = exercises.locate_citation(goal_id, exercise_id, citation_id)
                return located(goal_id, node_id, source)

        if lessons is not None:
            @app.get("/api/goals/{goal_id}/lessons/{package_id}/citations/{citation_id}", response_model=LocatedSource)
            def locate_lesson_citation(goal_id: Identifier, package_id: Identifier, citation_id: Identifier):
                node_id, source = lessons.locate_citation(goal_id, package_id, citation_id)
                return located(goal_id, node_id, source)

        @app.get("/api/goals/{goal_id}/nodes/{node_id}/context")
        def node_context(goal_id: Identifier, node_id: Identifier):
            return learning_context.context(goal_id, node_id)

        @app.get("/api/goals/{goal_id}/nodes/{node_id}/next-action")
        def next_action(goal_id: Identifier, node_id: Identifier,
                        available_minutes: Annotated[int | None, Query(gt=0)] = None):
            return learning_context.next_action(goal_id, node_id, available_minutes)

        @app.get("/api/runs/{run_id}/citations/{citation_id}", response_model=LocatedSource,
                 responses={code: {"model": ErrorEnvelope} for code in (404, 409)})
        def locate_citation(run_id: Identifier, citation_id: Identifier):
            try:
                record = loop.get_run(run_id)
            except KeyError:
                return _error(404, "run_not_found", "Run does not exist.", run_id=run_id)
            source = record.output.get("citation_map", {}).get(citation_id)
            if source is None or record.goal_id is None:
                return _error(404, "source_not_found", "Citation was not returned in this run.", run_id=run_id)
            return located(record.goal_id, record.node_id, source)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/model/status")
    async def model_status():
        return {"mode": model_mode, "configured": model_configured and model_mode == "real"}

    @app.post("/api/sessions/{session_id}/runs", status_code=202, response_model=PublicRun,
              response_model_exclude_unset=True,
              responses={code: {"model": ErrorEnvelope} for code in (409, 429, 503)})
    def submit_run(session_id: Identifier, body: SubmitRun):
        if body.mode == "explanation":
            if lesson_events is None:
                return _error(409, "explanation_not_configured", "Lesson explanations are not configured.")
            return public_run(lesson_events.submit_explanation(session_id, body.goal_id, body.node_id,
                body.source_event_id, body.explanation_slot, body.request_id, body.retry_of_run_id))
        record = loop.submit(RunRequest(
            session_id=session_id, user_text=body.user_text, idempotency_key=body.request_id,
            goal_id=body.goal_id, node_id=body.node_id,
            mode=body.mode, retry_of_run_id=body.retry_of_run_id,
            stream=True,
        ))
        return public_run(record)

    @app.get("/api/sessions/{session_id}/runs", response_model=list[PublicRun], response_model_exclude_unset=True)
    async def session_runs(session_id: Identifier):
        return [public_run(record) for record in loop.list_runs(session_id)]

    @app.get("/api/runs/{run_id}", response_model=PublicRun, response_model_exclude_unset=True,
             responses={404: {"model": ErrorEnvelope}})
    async def get_run(run_id: Identifier):
        try:
            return public_run(loop.get_run(run_id))
        except KeyError:
            return _error(404, "run_not_found", "Run does not exist.", run_id=run_id)

    @app.post("/api/runs/{run_id}/cancel", response_model=PublicRun, response_model_exclude_unset=True,
              responses={404: {"model": ErrorEnvelope}})
    async def cancel_run(run_id: Identifier):
        try:
            return public_run(loop.cancel(run_id))
        except KeyError:
            return _error(404, "run_not_found", "Run does not exist.", run_id=run_id)

    @app.get("/api/runs/{run_id}/events", response_class=StreamingResponse,
             responses={200: {"content": {"text/event-stream": {}}}, 404: {"model": ErrorEnvelope}})
    async def run_events(run_id: Identifier, request: Request):
        try:
            record, cursor = loop.snapshot(run_id)
        except KeyError:
            return _error(404, "run_not_found", "Run does not exist.", run_id=run_id)

        async def stream():
            nonlocal cursor
            yield encode_snapshot(record, cursor)
            if record.status in TERMINAL_STATUSES:
                return
            while not await request.is_disconnected():
                events = await asyncio.to_thread(loop.wait_events, run_id, cursor, heartbeat_seconds)
                if events and events[0].seq > cursor + 1:
                    latest, cursor = loop.snapshot(run_id)
                    yield encode_snapshot(latest, cursor)
                    if latest.status in TERMINAL_STATUSES:
                        return
                    continue
                for event in events:
                    yield encode_sse(event)
                    cursor = event.seq
                # Read status and cursor together so a concurrent terminal event cannot be skipped.
                latest, latest_seq = loop.snapshot(run_id)
                if latest.status in TERMINAL_STATUSES and cursor >= latest_seq:
                    return
                if not events:
                    yield ": heartbeat\n\n"

        return StreamingResponse(
            stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
