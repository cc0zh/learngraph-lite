# LearnGraph Lite Fixture Demo Script

This is a deterministic fixture demo for local review. It does not call a real model and must not be presented as real model output.

## Scenario

- Goal: 四周做出 RAG 应用
- Mode: fixture
- Clarification questions: 0
- Goal confirmed: true

## Walkthrough

| Step | Observable result |
| --- | --- |
| 1. Confirm goal | graph revision 1 with 8 nodes |
| 2. Bind material and ask grounded question | 1 citation(s); 根据已绑定资料：RAG 系统先检索资料片段，再生成带引用的回答。 Chunking controls retrieval quality. |
| 3. Ask unrelated question | 0 citation(s); 没有在已绑定资料中找到足够依据，不能给出带引用的回答。 |
| 4. Learn first node | fixture-demo: 解释 RAG 的目标和边界 |
| 5. Submit three exercises | mastery=proficient, samples=3, accuracy=1.00 |
| 6. Get next action | learn_node:document-loading |
| 7. Render declarative lesson | 3 fixed component(s); explanation run recorded=true |
| 8. Review graph proposal | proposal=accepted; updated graph nodes=9 |

## Evidence boundary

- This demo proves the current deterministic application/domain slices can be replayed locally.
- Real model smoke, browser UI, FastAPI routes, SQLite persistence and video recording are still separate M5 work.
