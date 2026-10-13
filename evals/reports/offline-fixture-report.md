# Offline M5 Fixture Evaluation Report

- Suite: offline-m5-fixture
- Mode: fixture / deterministic local services
- Real model smoke: not run; no provider API key is configured in this environment.
- Result: 20/20 cases passed

| Case | Area | Status | Evidence |
| --- | --- | --- | --- |
| goal_clarification_questions | planning | passed | returned 3 clarification questions |
| goal_confirm_with_assumptions | planning | passed | confirmed with 3 assumptions |
| graph_publish_revision | planning | passed | published graph revision 1/content revision 1 |
| graph_cycle_rejected | planning | passed | graph must be acyclic |
| learning_node_run_idempotent | learning | passed | same request_id reused the first run result |
| exercise_public_hides_answer | learning | passed | public exercise excludes answer and explanation |
| attempt_first_counted_retry_not_counted | learning | passed | first attempt counted; retry ignored for mastery |
| mastery_reaches_proficient | learning | passed | 3/3 counted attempts reached proficient |
| mastery_can_drop_after_new_wrong | learning | passed | dropped to learning with accuracy 0.40 |
| next_action_blocks_until_prereq | learning | passed | next action advanced only after prerequisite proficiency |
| document_upload_chunks | documents | passed | created 2 chunks with page metadata |
| document_search_citation | documents | passed | search returned citation tied to a chunk |
| document_empty_retrieval | documents | passed | empty retrieval refused grounded answer |
| citation_stale_rejected | documents | passed | citation document version is stale |
| lesson_rejects_executable_markdown | lessons | passed | lesson text cannot contain executable HTML or dangerous URLs |
| lesson_event_idempotent | lessons | passed | duplicate event id preserved first payload |
| lesson_explanation_idempotent | lessons | passed | same event and slot reused explanation run |
| proposal_pending_no_side_effect | proposals | passed | pending proposal did not mutate graph |
| proposal_accept_updates_graph | proposals | passed | accepted proposal updated graph |
| run_lifecycle_sse_cancel_budget | agent | passed | cancelled and budget_exceeded are distinct public terminal states |

This report proves only deterministic fixture behavior for the implemented slices.
It must not be used as evidence of real model quality or browser E2E behavior.
