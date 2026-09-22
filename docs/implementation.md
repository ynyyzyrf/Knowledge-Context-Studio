# V1.0 implementation ledger and plan

Latest status: [專案進度總覽](../PROGRESS.md). This ledger retains chronological engineering decisions and evidence; older entries describe their date, not current product behavior. Update the overview after each delivery or acceptance result.

Objective: complete the internal-team V1.0 and start the project. Scope remains R01–R12 and N01–N09 in ../docs/production (workspace root), not a demo.

## Rulings

- User now explicitly authorizes V1 development and startup. Earlier G0-only execution limit is superseded; unresolved gates remain acceptance work, not reasons to avoid implementing the product.
- New isolated product repository at studio/, branch v1. OpenViking and loci stay read-only. Local startup is the first deployment; no public publication inferred.
- Product API: FastAPI + SQLAlchemy/PostgreSQL, persistent worker operations. React/TypeScript UI. OpenViking stays an internal HTTP service pinned to validated source.
- Internal first release uses administrator-provisioned password accounts with argon2-cffi hashing and revocable server-side sessions; no public signup. OIDC remains optional integration, not a fabricated existing IdP.
- User selected existing OpenAI-compatible provider. Endpoint/model/key must be configured locally; missing provider blocks live acceptance but not implementation. No fake provider in shipped runtime.
- Candidate extraction goes to product staging, outside the engine retrieval corpus. Activate through a durable operation; no user-wide memory publication for Subject facts. Context adapter uses scope-restricted retrieval and checks product source/permission state before delivery.
- Authoritative policy/deletion ledger must survive engine restore. Recovery remains quarantined until replay + positive/negative checks complete.

## Work packages (test first, then implement, verify, update evidence)

- [ ] P1: configuration, schema migration, admin bootstrap, password sessions, CSRF, membership, audit; tests invalid/revoked credentials, disabled member and tenant boundary.
- [x] P2: Agent, Subject and space grants; one-time credentials, rotations, disable and scoped access; composite tenant FK and negative authorization tests. Product-policy APIs verified; engine ACL projection remains P3 and whole-branch review remains P7.
- [ ] P3: durable operations/worker, OpenViking adapter, versioned file ingestion, deletion/tombstones, retry/lease/idempotency; real native integration and worker interruption.
- [ ] P4: context scope intersections, session/message bindings, extraction candidate staging, activate/edit/disable and provenance; tests cross Subject/space/candidate leakage and in-flight revocation.
- [ ] P5: full Chinese product UI (login, spaces/files, Agents/subjects, operations, cognition, audit/settings), source-backed state and browser verification.
- [ ] P6: configuration for actual models, quotas/usage, backups/recovery quarantine + replay, migrations/runbooks, health/metrics; end-to-end internal Agent workflow, load and restore evidence.
- [ ] P7: final independent review, fix findings, launch via documented command, verify browser and complete acceptance matrix. Do not mark goal complete while any explicit requirement remains unverified.

## Technical references consulted

- https://docs.sqlalchemy.org/en/20/orm/session_basics.html : transaction/session lifecycle.
- https://argon2-cffi.readthedocs.io/en/stable/howto.html : password hashing and verification.

## Current evidence

2026-09-21: independent product repository initialized. PostgreSQL 16 container is healthy on loopback 55488; migration b954958cfe04 applied to product database. Application/UI are not yet launched.

- Seven PostgreSQL-backed auth tests pass against isolated schemas initialized through Alembic: login/logout/CSRF, wrong password and Origin, tenant membership and revocation, last admin retention, lockout/expiry, existing account membership, concurrent mutual admin disable.
- Six model adapter contract tests pass using explicit HTTP fixtures: configuration/secret redaction, chat+embedding parsing, auth/rate-limit/unavailable errors, invalid embedding response. These are not real provider acceptance.
- Earlier identity/model suite: 13 passed, later 15 after HTTP opt-in and independent chat checks. These historical counts do not represent the current full suite. Existing native G0 evidence stays in workspace validation/.
- User-supplied provider stored only in ignored local configuration. `/v1/models` returned 200 with metis-coder, metis-coder-auto, metis-coder-max. Real metis-coder chat passed (17 input / 3 output tokens); metis-coder-auto returned 429. Default is metis-coder; no silent fallback. Vector model is still unspecified and live embedding acceptance remains open.
- Added exact-origin opt-in for the explicitly supplied remote HTTP endpoint; other origins/ports retain HTTPS requirement. Chat works independently of missing embeddings; embedding calls fail explicitly with embedding_not_configured.
- `python -m kcs.manage check-chat` verifies real chat; `check-models` requires both chat and embeddings. No provider key or response body is recorded in evidence.
- P1 remains open for broader operational hardening/review; P3–P7 remain incomplete. No claim of production completion or full project startup.

### Product policy and session package

- Migrations `4bbdda4f45e5` and `9558aa10ae69` applied on local PostgreSQL. Agent/credential/Subject/space grants and session/message references use tenant-qualified compound foreign keys. Alembic check reports no schema drift.
- API supports Agent/Subject creation and disable/enable, explicit finite credential Subject scope, one-time token issuance, expiry, revoke and atomic rotation. Only token hashes are stored. Lists and audit omit raw tokens. Forged identity headers cannot change bearer identity.
- Space creation defaults to pending engine synchronization. Product grants are authoritative; ordinary people require explicit space grants. No ingestion/context code currently publishes pending spaces.
- Session creation binds Agent and Subject; there is no public rebinding route. Per-Agent creation keys and per-session message IDs deduplicate retries, with content/Subject conflicts rejected. Message and session lists require current credential Subject authorization.
- Ruling: serialize short session requests on tenant policy row, then refresh identity before access — prevents policy mutations racing accepted session writes and supports duplicate event serialization — cost is per-tenant throughput, to measure before N04 acceptance. No model or engine calls run under this lock.
- PostgreSQL tests cover concurrent mutual admin disable, concurrent credential rotation, duplicate concurrent message delivery, explicit revocation, credential expiry, Subject disable, cross-Agent session access and direct cross-tenant/cross-Agent FK violations.
- Full PostgreSQL suite: 27 passed, two dependency deprecation warnings. Ruff lint passes; source/tests/migrations formatted. This is local API/database evidence, not browser, worker, real Agent or production acceptance.
- Next implementation: durable jobs and extraction staging, private OpenViking runtime adapter/ingestion, then UI and operations. Real chat is available; embedding model remains awaiting user selection.

### Durable extraction package

- Migration `7bfd5a3d5fb8` adds jobs, submission receipts and a separate candidate staging table. A submitted session snapshot is deduplicated across multiple receipt keys; later messages do not mutate an earlier submission.
- PostgreSQL SKIP LOCKED claims, finite leases, replacement tokens and completion fencing prevent two workers accepting the same job result. Abandoned leases reach failed after bounded attempts. Transient model errors use delayed retry; explicit retry retains cumulative attempt counts.
- Worker loads source messages in a short authorized transaction, releases database locks during the model call, then rechecks lease and current credential/Agent/Subject authorization before atomically staging candidates and succeeding. Staged output has validated source IDs from the snapshot. No engine publication path exists yet.
- Ruling: unfinished jobs remain bound to the submitting credential, including expiry/revocation — fail closed after loss of authority — rotation may require an explicit retry from a replacement credential with the same Subject authorization.
- Full default PostgreSQL suite: 38 passed, 1 skipped (opt-in real model test), two dependency deprecation warnings, 32.63 seconds. JUnit: `docs/evidence/jobs-suite.xml`. Includes parallel claim, stale result rejection, post-claim process exit, retry exhaustion, in-flight Subject revocation, and job cross-Agent/Subject visibility.
- Real model worker evidence: first extraction timed out and was correctly recorded retry; second independent run passed, with a candidate and exact source attribution. Details: `docs/evidence/extraction-live.md`. Does not establish model availability SLO or extraction quality.
- Ruff lint and Alembic schema check pass. P3 is still incomplete until actual engine adapter/ingestion, deletion and engine-facing recovery work is complete; P4 still needs candidate governance, active memory versions and context.

### Governance package

- Added administrator candidate approval/rejection, pending publication records, versioned edits, immediate product-side disable/delete, current cognition and provenance APIs. Full PostgreSQL suite now passes 43 tests with 1 opt-in live model skip; publisher integration remains outstanding.
- Migration `f69e84eead44` applied. Autogenerated ordering initially tried to create a referencing table before adding the candidate compound unique constraint; corrected by creating the named constraint first and dropping it last during downgrade. PostgreSQL rolled back the failed attempt. Alembic check now passes.
- Approval/edit create durable memory projection requests; no publisher processes them yet, so state stays pending. Delete clears all product memory revision bodies and originating candidate body while preserving identifiers; engine purge remains pending.
- User asked remaining distance: explained that core workflow/UI/production acceptance remain substantial. Next priority is the complete document upload→index→retrieval→Agent flow and usable UI; current unit/API counts do not establish V1 completion.

### Management frontend and external API testing

- Implemented React/TypeScript/Vite Chinese workbench: login/team switch, role-aware navigation, spaces/grants, external Agent/Subject/finite credentials, members, jobs, candidate governance/provenance/history and audit. Served by FastAPI on localhost:8088; Swagger remains on /docs.
- Boundary confirmed with user: no embedded Agent runtime. API testing explicitly records external messages, submits extraction, displays real job status and requires explicit retry. Agent tokens remain in browser memory only; human cookie/CSRF and Agent bearer requests are separate.
- Browser tested account login, persistent space creation, Agent/Subject registration, bearer identity, session/message submission, real extraction failure/retry/success, candidate provenance, approval, v2 editing/history, rejection audit and switching to a viewer-only second tenant. See `docs/evidence/frontend-acceptance.md` for exact scope and remaining gaps.
- Five frontend tests, production build and runtime dependency audit pass. Fixed session-expiry query observer hang, same-token retry, rejection-reason audit loss, terminal polling and stale job details. Build still warns about main chunk size.
- scripts/start.ps1 builds frontend and starts/restarts only recognized local API/worker processes, runs migrations, checks API/database and frontend readiness. Initial local admin credentials stay in a restricted ignored runtime file. This is not a production process supervisor.
- Remaining production path: ingestion/indexing, engine publication/deletion and authorized context retrieval, vector model selection, real external consumer acceptance, extraction format reliability, performance and tested recovery/deployment.

### Memory publication and readback package (2026-09-22)

- Connected private pinned native OpenViking to real BAAI/bge-m3 (1024 dimensions), preserving the separately configured chat/embedding providers. No embedded Agent runtime.
- Added fenced durable publication, exact-version deletion with retries/reconciliation, current authorized memory listing and semantic `/v1/context`; engine hits only identify candidates and PostgreSQL supplies current approved content. Revalidate credential and Subject after engine I/O.
- Added API testing UI for published memory and semantic reference retrieval; verified real HTTP submission, real extraction, browser approval, publication and a paraphrased question returning the fact with provenance.
- Found and fixed missing native index after interrupted initialization; require actual index readiness and per-URI indexed count. Removed unnecessary deletion wait on ancestor semantic refresh; verify exact body and vectors absent instead.
- Evidence: docs/evidence/readback-acceptance.md; integration guide: docs/external-agent-readback.md. Full PG suite 51 passed/2 skipped, focused PG boundaries 8 passed, true vector roundtrip 1 passed, native fixture contract 1 passed, frontend 5 passed/build passed. Independent review found no remaining important leak/permanent cleanup omission in the revised boundary.
- P3/P4 advance for memories only. File ingestion, external Agent consumer, production delivery/recovery/performance remain open; overall production goal is not complete.

### Durable file ingestion and authorized retrieval (2026-09-22)

- Added real Markdown/UTF-8 text/text-PDF upload, bounded isolated parsing, durable document/chunk storage, leased indexing and persistent deletion reconciliation. No embedded Agent runtime. Migration `1db99657541c` applied with no schema drift.
- Space UI supports upload, polling, source preview, retry and delete. External `/v1/context` now searches authorized space roots alongside Subject memories, rechecks grants after engine I/O and supplies only current succeeded PostgreSQL chunks.
- Fixed format-confused checksum dedup and enforced a hard parser process memory ceiling; independent follow-up review found no new P1/P2.
- Full PG suite 59 passed/3 opt-in skips before final three added boundary tests; final document PG suite 10 passed; real three-format native-engine roundtrip 1 passed; frontend 6 passed/build passed. Browser verified Chinese file upload, completed index, preview and paraphrased reference retrieval. API verified deletion and engine cleanup; isolated acceptance identities were disabled/revoked.
- Evidence: `docs/evidence/document-import-acceptance.md`; usage/API: `docs/document-import.md`. File ingestion portion of P3/P4 advances; third-party autonomous Agent use, production deployment/recovery/load/quality acceptance remain outstanding. DOCX/OCR/batch imports are not included.

### Unified Docker deployment (2026-09-22)

- Added pinned multi-stage platform image, separate API/worker services, private PostgreSQL/native engine, isolated runtime configuration, migration/start sequence and offline image export. Existing development services remain separate.
- Explicit exact-origin HTTP allowance supports the private Docker engine without accepting arbitrary HTTP endpoints. Publisher setup resolves the environment-file symlink before atomic updates, so non-root tools can update the mounted configuration directory.
- Local Linux containers passed real upload/index/context/deletion and external message write/read/idempotency smoke checks. Exported all three images; no runtime configuration or data volumes included. Bash script syntax checked, equivalent Compose steps executed from Windows.
- Evidence: `docs/evidence/docker-deployment-acceptance.md`; instructions: `docs/docker-deployment.md`. Tencent Cloud machine, HTTPS, Hermes and production restore/load remain unverified.

### Two-layer information architecture refactor (2026-09-22)

- Restructured the frontend into two product layers. Organization level: Knowledge Space list (dense stat cards: files/memory/agents/last activity, no UUID exposure), external Agent access, members, audit and a Settings page that now hosts jobs, memory governance and API testing. Space level: full-screen per-space Context Studio with left space nav (files/search/upload/agent access), middle context tree (context:// resources by filename-derived category plus subjects with memories/peers/sessions counts) and a right detail panel with URI, metadata, agent readability and per-subject read/write scopes.
- Backend: added `description` to knowledge spaces (migration `c58d1e7a2b40`, applied, alembic check clean), space list/detail now return document/agent/memory counts and last activity, new admin-only `PATCH /spaces/{id}`, `GET /spaces/{id}/context` tree data and `POST /spaces/{id}/search` which queries only that space's engine root and verifies hits against current PostgreSQL chunks. Memory counts attribute a subject's memories to every space its agent can read, matching the current memory ownership model.
- Fixed a useParams-outside-Route bug in the space layer by resolving the space id via matchPath in the shell and passing it as a prop.
- Verification: backend sqlite suite 60 passed/8 opt-in skips (3 new tests covering description+stats, context tree, verified search); ruff clean on touched files; frontend 6 tests and production build pass; live browser smoke test on localhost:8088 covered login, org navigation, space cards, space studio tabs (context tree, search, grants) and settings tabs. Full browser acceptance of the new IA and responsive behavior is still pending.
