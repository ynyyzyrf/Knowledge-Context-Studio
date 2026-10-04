# Automatic storage and complete results Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 已提交資料可按設定自動存儲，Agent 與管理員能查到完整結果。
**Architecture:** 延用 Subject extraction/publication 與 Person+Space namespace 兩條流程，各自授權，不混用所有權。
**Tech Stack:** FastAPI / SQLAlchemy / Alembic / PostgreSQL / React / Node MCP。
**Spec:** ../../requirements/2026-10-03-storage-results-scope.md

## Global Constraints

不收集未提交內容，不改原有權限及删除清理；保留未提交工作；本地實作與驗收，不隱式發布到生產。按使用者「這兩個先做」授權在本會話直接執行，不再重複詢問範圍。改動集中同一分支，交付可檢查 diff，不混入既有部署文件。

## Review Focus

- 撤權或變更政策發生在模型執行期間：完成時重檢，測試在 Task 2。
- 重放提交、同批重复與跨 session 重複：只一份正式記憶，Task 2。
- 只有寫權的個人 Agent：回執不返回後續修改正文，Task 3。
- 發布失敗／刪除：完整結果不能虛報 ready 或洩露刪除內容，Task 2。
- 空提取和舊任務：no_durable_facts / manual fallback，Task 2。

## Task 1: Policy and result persistence

Files: src/kcs/models.py, src/kcs/agent_routes.py, migrations/versions/91a6d3e8c502_automatic_storage.py, tests/test_automatic_storage.py.

- [x] Write policy test: existing Agent manual; PUT /tenants/{tenant}/agents/{agent}/memory-policy with {mode:automatic} succeeds; machine cannot change; /agent/me advertises mode.
- [x] Run `.venv/Scripts/python.exe -m pytest tests/test_automatic_storage.py -q`; expect missing route/field failures.
- [x] Add Agent.memory_policy (manual default), NamespaceScopeGrant.auto_store (false default), BackgroundJob.storage_policy nullable, MemoryCandidate.storage_outcome/storage_reason nullable, duplicate_of nullable. Migration preserves current rows.
- [x] Implement admin policy endpoint, same tenant lock/audit as existing policy changes. No permission expansion.
- [x] Rerun focused tests; expect PASS after dependent tasks are completed.

## Task 2: Automatic extraction storage and complete job result

Files: src/kcs/jobs.py, src/kcs/memory_routes.py, new src/kcs/memory_storage.py, src/kcs/job_routes.py, tests/test_automatic_storage.py.

Interfaces: `create_revision(db, memory, *, actor_id, request_id, content, sources, status, reason)` shared by human and worker; `job_result(db, job)` returns summary/items and pipeline_state.

- [x] Tests cover normal automatic creation and fake-engine publication then authorized retrieval; manual default; zero results; assistant-only provenance review; dedup across snapshots; policy change/revocation; failed publication; deleted content redaction; foreign job 404.
- [x] Run focused tests; observe missing result/creation failures.
- [x] Refactor revision creation to explicit actor/request IDs; call from worker only inside fenced transaction after authorization check. Check all referenced message roles for auto approval; dedup normalized exact current pending/active memory within tenant+Agent+Subject. Record outcome without copying result bodies to job JSON.
- [x] `job_payload(row, db)` adds results using current candidate/revision/projection rows, read authorization unchanged. Use counters and pipeline_state waiting/processing/review_required/no_changes/indexing/ready/failed; preserve extraction state.
- [x] Run extraction/publication/context/governance tests; expect PASS.

## Task 3: Personal storage policy and receipt

Files: src/kcs/personal_context_routes.py, tests/test_automatic_storage.py, web/src/personal-context.tsx (confirm actual filename).

- [x] Test explicit owner opt-in, default pending, no implicit grant, write-only replay, skills unchanged.
- [x] Extend GrantInput with auto_store default false; permit only memories+can_write. Add to grant listing. create_entry active for enabled machine memory submissions; receipt storage outcome/reason plus indexing, preserving content and source IDs.
- [x] Run personal context/index/retrieval tests; expect PASS.

## Task 4: UI and MCP delivery

Files: web/src/pages.tsx, web/src/types.ts, personal directory UI, integrations/mag-kb/server.mjs, integrations/mag-kb/README.md, tests/test_personal_mcp.py.

- [x] Extend real Node→HTTP MCP test with kb_job_result querying pending/succeeded/zero outcomes; observe unknown tool failure first.
- [x] Add kb_job_result(job_id), return actionable job lookup from submit; update descriptions to configured policy and exact source distinction.
- [x] Add Agent policy control and personal grant control; Jobs table shows results/Agent, drawer shows contents, sources, current publication errors. Poll during publication as well as extraction.
- [x] Run Node contract tests, `.venv/Scripts/python.exe -m pytest -q`, `npm --prefix web test`, `npm --prefix web run build`; inspect all failures, record skipped live checks honestly.
- [x] Review diff and migration locally; independent code review for authorization/result correctness; fix and rerun relevant tests. Record evidence, leave unrelated changes intact.

## Execution ledger

2026-10-03: Specification and interfaces checked against repository. Existing v1 checkout retained, no implementation changes at plan creation. Ruling: no autonomous semantic overwrite in this increment; full results report actual behavior. Native execution follows user's selected scope. No automatic collection code.


2026-10-03 verification: Task 1–4 complete locally. Initial feature tests failed at missing policy/result fields (7 failures); implementation passed. Real MCP test failed for unknown kb_job_result, then passed. Final full Python suite 112 passed / 9 skipped; PostgreSQL storage/jobs 18 passed plus PostgreSQL concurrency 4 passed; frontend 8 tests passed and production build passed.

Final review: independent read-only reviewer found automatic resurrection from deleted/disabled source history. Fixed with source tombstones; both regression tests observed RED then GREEN. Conservative skipped-source behavior added to spec. MCP maximum-length idempotency key also reproduced HTTP 422, fixed via bounded deterministic child keys, contract test passed in full suite.

Ruling: keep this delivery as a reviewable uncommitted diff in existing v1 checkout; do not include earlier deployment/architecture changes in a commit or deploy without a current release step. No production policy was changed.

UI verification: isolated SQLite synthetic dataset at loopback 8189. Browser login, Agent policy change and reload to manual, job results list and drawer verified actual persisted content/source/memory ID and indexing state. No billed live model or real engine call made.
