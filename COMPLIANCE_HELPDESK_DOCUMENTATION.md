# Compliance Helpdesk API — Codebase Documentation

A field-level reference for the FastAPI service that powers compliance queries, self-declarations (COBCE/COI), and annual declarations. Written directly from the source on `release/helpdesk`.

- **Service:** compliance-helpdesk
- **Framework:** FastAPI + SQLAlchemy (async)


## Contents

1. [Module Overview](#1-module-overview)
2. [System Components](#2-system-components)
3. [Data Design](#3-data-design)
4. [Data Orchestration Workflows](#4-data-orchestration-workflows)
5. [Common Response Contract](#5-common-response-contract)
6. [API Documentation](#6-api-documentation)
8. [Caching Strategy](#8-caching-strategy)

---

## 1. Module Overview

### 1.1 Purpose

The service is a single FastAPI application (`main.py`) titled **"Compliance Helpdesk API"** that backs three related but distinct workflows for an organization's compliance function:

- **Compliance queries** — free-form questions raised by staff (COBCE, COI, ComplyShield, Gift, Other) that go through a request/response conversation with a compliance lead until closed.
- **Self-declarations** — structured COBCE (code-of-business-conduct-and-ethics) and COI (conflict-of-interest) forms, saved as drafts and then submitted for review.
- **Annual declarations** — a yearly, admin-driven declaration cycle with per-user status tracking, Excel-based bulk upload/sync, and reminder emails.

All three share one Postgres database, one Redis-backed cache layer, one Azure Blob Storage account for files/conversation JSON, and one notification pipeline (Azure Communication Services email).

### 1.2 Core Capabilities

- **Query & declaration lifecycle** — Raise → respond (ping-pong between owner and assigned lead) → close, with a JSON-file conversation log per record.
- **Role-based assignment (RBAC)** — Per-type "lead" flags on the user record gate who can view admin queues, get assigned records, and respond as compliance.
- **Unified dashboard** — One endpoint surfaces pending/all items across query, self-declaration and annual-declaration types, scoped by role, with an Excel export.
- **Excel-driven annual sync** — Admins upload a workbook to bulk-create/update per-user declaration status and trigger targeted reminder emails.
- **Recent activity tracking** — A middleware + service pair keeps a rolling "last 5 records viewed" list per user.
- **Notifications** — Fire-and-forget async emails on record created / responded / closed / assigned, sent via Azure Communication Services.

> **Legacy cleanup in progress.** `db/db_manager.py`'s `init_db()` actively drops `compliance.gift_declarations` and `compliance.complaints`, and removes a `users.is_complaint_lead` column, on every startup — matching the recent commit "remove gift and complaint." `QueryType.Gift` still exists as an enum value in `db/validators/comp_help.py`, so a "Gift" query type can still be raised even though the dedicated gift-declaration table is gone; treat it as a query sub-type, not a standalone feature.

---

## 2. System Components

### 2.1 FastAPI Application Layer

`main.py` assembles the app with a `lifespan` context that runs `init_db()` for both the helpdesk and annual-declaration `Base` metadata, initializes an AI-safe logger, and on shutdown closes the storage client and Redis connection.

- Docs are mounted off the API root, not the default paths: `/api/compliance/docs`, `/api/compliance/redoc`, `/api/compliance/openapi.json`.
- **SecurityHeadersMiddleware** (custom) — adds `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`, and a strict `Content-Security-Policy` to every response, except it drops the CSP header on the three docs paths above so Swagger/Redoc can render.
- **RecentRecordsMiddleware** (`api/middleware/recent_records.py`) — observes responses and logs record views into the recent-activity table.
- **CORSMiddleware** — `allow_origins=["*"]` with all methods and headers allowed; there is no origin allowlist at this layer.
- Three routers are mounted: `annual_declaration_router` at `/api/declarations`, `health_router` and `compliance_helpdesk.router` both at `/api/compliance`. The helpdesk router itself is a composition of seven sub-routers (query, self-declaration, generic, respond, dashboard, recent-activity, admin) — see §6.

> **Dead code note.** `api/routes/helpdesk/cobce_routes.py` (`POST /cobce-draft`, `PUT /cobce/{id}`, `POST /cobce/{id}/submit`) and `api/routes/helpdesk/dashboard.py` exist on disk but are never imported into `compliance_helpdesk.py`'s router composition — they are not reachable in the running app. The live COBCE/COI save path is `POST /self-declaration` in `self_declaration_routes.py`.

### 2.2 PostgreSQL Database

A single Postgres instance (`docker-compose.yml` runs `postgres:16-alpine` locally as `auth-flow`) hosts three schemas, created idempotently in `init_db()`:

- `users` — the shared `users` table (two slightly different SQLAlchemy `User` models exist — one per `Base` — both mapping the same physical table with an overlapping-but-not-identical column set; see §3 note).
- `compliance` — query, COBCE, COI, and recent-records tables.
- `annual_declarations` — declaration, per-user status, and per-question response tables.

Access goes through `db/db_manager.py`'s `DBManager`: a generic async CRUD/list helper built on SQLAlchemy Core/ORM (`create`, `get`, `list` with Mongo-style `$gte/$lte/$in/$ilike/$or` filters and pagination, `update`, `delete`, `raw`). Connection is `asyncpg` via `postgresql+asyncpg://`, pool size 10 / max overflow 20 / 30s timeout, read from `POSTGRES_USER/PASSWORD/HOST/DB/PORT` env vars (Key Vault-backed lookups are present but commented out).

> **Startup migrations live in code.** `init_db()` runs raw DDL on every boot — dropping legacy tables/columns, adding `AssignedTo` / `ClosedBy` / `ClosedRemarks` / `LastUpdatedOn` to the three compliance tables, relaxing `PendingAt` to nullable, and adding a `remarks` column to `user_declaration_status` — before calling `Base.metadata.create_all`. There is no separate migrations tool (e.g. Alembic) in `requirements.txt`.

### 2.3 Redis Cache

`db/redis_cache.py` wraps `redis.asyncio` behind four functions: `cache_set`, `cache_get`, `cache_delete`, `cache_delete_pattern`. Connection comes from a single `REDIS_URL` env var (no host declared in `docker-compose.yml`, so Redis is expected to be provisioned externally in every environment). If `REDIS_URL` is unset, or the initial `ping()` fails, every call transparently falls back to a process-local `dict` with the same TTL semantics — so the service degrades to in-memory caching rather than failing.

### 2.4 Authentication Layer

`utils/deps.py`'s `get_current_user()` is the single FastAPI dependency every route uses for identity. Its own docstring reads: *"Replace with real auth; loads admin flags from users table when present."*

> **No request-level authentication is currently wired in.** `get_current_user()` hard-codes `staff_id = "STAFF001"` and looks that row up in `users.users` to hydrate role flags; it does not read any header, cookie, or token from the request. `PyJWT` and `python-jose[cryptography]` are listed in `requirements.txt` but are not imported anywhere in application code (only referenced in the Postman collection generator). Authorization on top of that identity is real, though: every write/admin route calls into `utils/authorize.py` to check per-type "lead" boolean flags (`is_query_lead`, `is_cobce_coi_gift_lead`, `is_master_admin`, `is_policy_hub_admin`, `is_knowledge_hub_admin`, `is_cheif_compliance_officer` — sic) stored on the user row.

Key authorization helpers in `utils/authorize.py`:

- `is_helpdesk_admin` / `is_active_helpdesk_admin` — true if any admin flag is set and the user is `active`.
- `is_lead_for_type(user, record_type)` — type-specific check only (`query` → `is_query_lead`; `cobce`/`coi` → `is_cobce_coi_gift_lead`); master admin / CCO do **not** get a bypass here.
- `get_dashboard_type_scope(user)` — resolves which record types a user's dashboard admin queue includes, on top of their own records.

Secrets (e.g. the Azure Blob and ACS connection strings) resolve through `utils/azure_secrets.py`, which currently reads environment variables only — the Azure Key Vault SDKs in `requirements.txt` are not yet wired into that lookup.

---

## 3. Data Design

Two independent SQLAlchemy `DeclarativeBase` subclasses exist — one in `db/models/helpdesk.py`, one in `db/models/annual_dec.py` — each initialized separately in `main.py`'s lifespan. Both define a `users.users` model against the physical table; the helpdesk version carries the helpdesk-lead boolean flags, the annual-declaration version carries the org-directory columns (email, department, division…). They are two views of one table, not two tables.

### `users.users` — helpdesk view (`db/models/helpdesk.py`)

| Field | Type | Description |
|---|---|---|
| `staff_id` | String(255), PK | Employee/staff identifier; primary key across both model views. |
| `username` | String(255), null | Display name. |
| `status` | String(50) | Account status, default `"active"`; gate for all admin checks. |
| `is_master_admin` | Boolean | Broad admin flag; included in `is_helpdesk_admin` checks but not a bypass for per-type lead checks. |
| `is_policy_hub_admin` | Boolean | Grants dashboard admin scope over Self Declaration + Query sections. |
| `is_knowledge_hub_admin` | Boolean | Annual-declaration admin flag (annual declarations stay own-scoped in the dashboard regardless). |
| `is_cobce_coi_gift_lead` | Boolean | Lead for COBCE/COI self-declarations; can be assigned records and respond as compliance. |
| `is_query_lead` | Boolean | Lead for compliance queries; same assignment/response rights for the `query` type. |
| `is_cheif_compliance_officer` | Boolean | CCO flag (spelling as in source); included in helpdesk-admin checks only. |

### `compliance.compliance_queries` — `ComplianceQuery`

| Field | Type | Description |
|---|---|---|
| `QueryId` | String(100), PK | Generated record id (see `utils/record_ids.next_query_id`). |
| `QueryType` | String(50) | One of `COBCE / COI / ComplyShield / Gift / Other` (`QueryType` enum). |
| `Title` | String(500) | Short query title, word-limited on input. |
| `Description` | String(5000) | Full query text, word-limited on input. |
| `CreatedOn` | DateTime(tz) | Server-default `now()`. |
| `CreatedBy` | String(255) | Raising staff id (record owner). |
| `OverallStatus` | String(50) | `Pending` / `Closed` (also checked against `Completed` in close guards). |
| `PendingAt` | Integer, null | Turn tracker: `1` = compliance's turn, `0` = owner's turn, `null` once closed. |
| `AssignedTo` | String(255), null | Assigned lead's staff id; added by an `init_db()` migration. |
| `ResponseJsonPath` | String(1000) | Blob path to the conversation JSON (see §2.1 storage, §4). |
| `ClosureDate` | DateTime(tz), null | Set on close. |
| `ClosedBy` | String(255), null | Closer's staff id. |
| `ClosedRemarks` | String(2000), null | Closing comment. |
| `LastUpdatedOn` | DateTime(tz) | Auto-touched on every `DBManager.update()` call. |

### `compliance.cobce_declarations` — `COBCEDeclarations`

| Field | Type | Description |
|---|---|---|
| `COBCEId` | String(80), PK | Generated record id. |
| `SubType` | String | COBCE row category (see form config, e.g. nature of violation). |
| `Description` | String | Free-text description. |
| `PersonDetails` | JSON | Structured row data — array of `{nature_of_violation, person_responsible, files}` entries per the save endpoint's `rows` payload. |
| `Status` | String | `Draft` / `In-Progress` / `Completed` (workflow status, distinct from `OverallStatus`). |
| `CreatedOn` | DateTime | Creation timestamp. |
| `CreatedBy` | String | Owner staff id. |
| `OverallStatus` | String, null | Response-cycle status, same convention as queries. |
| `PendingAt` | Integer, null | Turn tracker, nullable after an `init_db()` migration. |
| `AssignedTo` | String(255), null | Assigned COBCE/COI lead. |
| `ClosureDate` | DateTime, null | Set on close. |
| `ClosedBy` | String, null | Closer's staff id. |
| `ClosedRemarks` | String, null | Closing comment. |
| `LastUpdatedOn` | DateTime(tz), null | Last-touched timestamp. |
| `ResponseJsonPath` | String, null | Conversation JSON blob path; only present once submitted (draft-only records have none). |

### `compliance.coi_declarations` — `COIDeclarations`

| Field | Type | Description |
|---|---|---|
| `COIId` | String(80), PK | Generated record id. |
| `SubType` | String | One of the six COI question types (e.g. `OUTSIDE_ACTIVITY`, `DIRECTORSHIP`, `FINANCIAL_INTEREST`, `REPORTING_CONFLICT`, `GIFT`, `PRICE_SENSITIVE_INFO`, `OTHERS`). |
| `FormData` | JSON | Sub-type-specific answer object, shape validated per sub-type in `db/validators/comp_help.py`. |
| `Status` | String | `Draft` / `In-Progress` / `Completed`. |
| `CreatedOn` | DateTime | Creation timestamp. |
| `CreatedBy` | String | Owner staff id. |
| `OverallStatus` | String, null | Response-cycle status. |
| `PendingAt` | Integer, null | Turn tracker. |
| `AssignedTo` | String(255), null | Assigned lead. |
| `ClosureDate` | DateTime, null | Set on close. |
| `ClosedBy` | String, null | Closer's staff id. |
| `ClosedRemarks` | String, null | Closing comment. |
| `LastUpdatedOn` | DateTime(tz), null | Last-touched timestamp. |
| `ResponseJsonPath` | String, null | Conversation JSON blob path once submitted. |

### `compliance.recent_user_records` — `RecentUserRecords`

| Field | Type | Description |
|---|---|---|
| `id` | Integer, PK, autoincrement | Surrogate key. |
| `user_id` | String(255), indexed | Viewer's staff id. |
| `record_id` | String(100), indexed | Referenced record's id (query/COBCE/COI/annual). |
| `record_type` | String(50) | Type label used for grouping/display. |
| `title` | String(500) | Denormalized title, shown without a join. |
| `sub_type` | String(100), null | Denormalized sub-type. |
| `status` | String(50) | Denormalized status at time of last view. |
| `created_on` | DateTime(tz) | Original record creation time. |
| `pending_at` | String(255), null | Denormalized pending-at display value. |
| `last_accessed_on` | DateTime(tz), indexed | Auto-updated on every view; drives the "top 5 recent" ordering. |

### `annual_declarations.annual_declarations` — `AnnualDeclaration`

| Field | Type | Description |
|---|---|---|
| `id` | String(20), PK | Declaration cycle id. |
| `declaration_name` | String(20) | Declaration type name, e.g. `COBCE/COI` (`DeclarationType` enum); unique with `financial_year`. |
| `financial_year` | String(7) | Financial year label, e.g. `2026-27`. |
| `assigned_date` | Date | Date the cycle opens. |
| `due_date` | Date | User submission deadline. |
| `activity_closure_date` | Date | Date the cycle activity closes entirely. |
| `status` | String(50) | Cycle status, default `Pending`. |
| `last_updated_at` | DateTime(tz) | IST-timestamped, auto-touched on update. |
| `file_path` | Text, null | Path to the last-uploaded sync workbook. |
| `last_uploaded_file_at` | DateTime(tz), null | Last Excel upload time. |
| `last_uploaded_by` | String(50), null | Admin staff id who last uploaded. |
| `pending_count` | Integer | Denormalized pending-user count, default 0. |
| `total_count` | Integer | Denormalized total-user count, default 0. |
| `excel_pending_status` | String(20), null | Status of the last Excel sync job itself. |
| `sync_status` | Enum(`SyncStatus`), null | `PENDING / FAILED / COMPLETED`; null = no file uploaded yet. |

### `annual_declarations.user_declaration_status` — `UserDeclarationStatus`

| Field | Type | Description |
|---|---|---|
| `id` | String(80), PK | Built via `build_annual_user_status_id` (declaration id + staff id). |
| `declaration_id` | String(20), FK → `annual_declarations.id`, cascade delete | Parent declaration cycle. |
| `staff_id` | String(50) | Declaring user; unique with `declaration_id`. |
| `status` | String(20) | `draft` / submitted / etc., default `draft`. Lazily created on first save or admin Excel sync. |
| `has_conflicts` | Boolean | Whether the user declared a conflict, default false. |
| `notify` | Boolean | Whether this user is eligible for reminder emails, default true; excel sync skips `draft`/`completed` statuses regardless. |
| `remarks` | Text, null | Added via an `init_db()` migration (matches "added last updated on" / recent schema-tweak commits). |
| `submitted_at` | DateTime(tz), null | Set on submission. |
| `last_saved_at` | DateTime(tz) | IST-timestamped, auto-touched. |
| `created_at` | DateTime(tz) | IST-timestamped creation time. |

### `annual_declarations.user_declaration_responses` — `UserDeclarationResponse`

| Field | Type | Description |
|---|---|---|
| `id` | UUID, PK | Generated per row via `uuid.uuid4`. |
| `declaration_status_id` | String(80), FK → `user_declaration_status.id`, cascade delete | Parent per-user status row. |
| `question_id` | String(50) | Form question identifier; unique with `declaration_status_id` (one row per question per user per cycle). |
| `response` | String(20), null | Short answer value, e.g. yes/no. |
| `declaration_details` | JSONB, null | Full structured answer for that question. |
| `created_at` | DateTime(tz) | IST-timestamped. |
| `updated_at` | DateTime(tz) | IST-timestamped, auto-touched. |

---

## 4. Data Orchestration Workflows

### Query / self-declaration response cycle

Queries, COBCE and COI records all share one state machine driven by the `PendingAt` integer column plus a JSON conversation file in Blob Storage (`ResponseJsonPath`). This is implemented in `api/routes/helpdesk/query_routes.py` (and mirrored generically in `respond_routes.py` via `resolve_record`).

1. **Raise** — `POST /query` creates the Postgres row (`OverallStatus=Pending`, `PendingAt=1`), uploads any attached files, writes the first conversation entry to a new JSON blob via `storage_ops.init_json`, and fires `notify_record_created` as a background task.
2. **Respond** — `POST /query/{id}/respond` checks who may act: the owner may respond only when `PendingAt=0`; an assigned lead may respond only when `PendingAt=1` *and* they are the record's `AssignedTo`. Each response appends to the conversation JSON and flips `PendingAt` (0 ↔ 1), then fires `notify_record_responded`.
3. **Close** — `POST /query/{id}/close` is allowed for the owner or the assigned admin only; it sets `OverallStatus=Closed`, clears `PendingAt`, stamps `ClosureDate`/`ClosedRemarks`, and fires `notify_record_closed`.

COBCE/COI records add a draft phase in front of this: they are created via `POST /self-declaration` (`services/self_declaration_service.py`) with `status=draft` and no `ResponseJsonPath`; a draft cannot be responded to until it is submitted (`status=submit`), which is when the query-cycle fields above start being populated.

### Assignment (admin routing)

`PUT /assign/{record_id}` (`admin_routes.py`) lets a type lead set `AssignedTo` on any non-annual record. It re-validates the target staff id actually holds the matching lead flag (`ADMIN_ROLE_CHECKERS`) and refuses to assign a record to its own creator; reassignment is otherwise unrestricted. Assignment is a prerequisite for an admin to respond — see step 2 above.

### Annual declaration Excel sync

`services/excel_sync_service.py` processes admin-uploaded workbooks in batches of 500 rows. It maps header columns dynamically (`services/excel_service.py`'s `_header_index_map`), upserts `UserDeclarationStatus` rows by `build_annual_user_status_id(declaration_id, staff_id)`, and deliberately **skips** sending a reminder to any user whose status is already `draft` or `completed` (`_SKIP_EMAIL_STATUSES`) — matching the "EXCEL: email frequency changes" commit, i.e. don't re-notify people who already started or finished.

### Recent activity capture

`api/middleware/recent_records.py` inspects successful responses from record-detail routes and calls `services/recent_records_service.log_recent_record`, which upserts a row in `recent_user_records` keyed on `(user_id, record_id)` and bumps `last_accessed_on`. `GET /recent-activity` returns the 5 most recently accessed records per user; there is also a manual `POST /recent-activity` for clients to log a view directly.

### Notifications

`utils/email_notifications.py` exposes `notify_record_created / responded / closed / assigned`, each invoked with `asyncio.create_task(...)` from the route handler so the HTTP response is never blocked on email delivery. Each helper resolves recipients (record owner, or all active leads holding the relevant flag) via raw SQL against `users.users`, renders an HTML template from `utils/email_templates.py`, and sends through `utils/email_manager.send_email`, which wraps the Azure Communication Services `EmailClient` and falls back to `{staff_id}@abc.com` if a staff id has no email on file.

---

## 5. Common Response Contract

There is no response envelope or global exception handler. Every helpdesk route builds its own `JSONResponse` directly — most go through `api/routes/helpdesk/route_utils.py`'s `log_and_json_response(staff_id, request_params, endpoint, request_type, status_code, response_content)`, which best-effort logs the call (via `utils/loggers.log_record`, swallowing logging errors) and then returns `JSONResponse(content=response_content, status_code=status_code)` unmodified. The body shape is whatever each handler passes in — there is no shared `{success, data, error}` wrapper.

#### Success shape (typical)

Handlers return a flat object with whatever fields are relevant to that action, and the HTTP status carries the semantics (200 for read/update, 201 for creation).

```jsonc
// 201 Created — POST /query
{
  "details": "Query has been created with query_id: QRY-2026-000482",
  "status": "Pending",
  "query_id": "QRY-2026-000482"
}
```

```jsonc
// 200 OK — POST /query/{id}/respond
{
  "details": "Response added",
  "nextPending": "Compliance Team"
}
```

#### Error shape (typical)

Errors are always `{"error": "<message>"}`, sometimes with a `details` field carrying the raw exception string on unhandled 500s. There is no error code or machine-readable type field — only the message and the HTTP status.

```jsonc
// 403 Forbidden — POST /query/{id}/respond
{
  "error": "Only the assigned admin can respond to this record"
}
```

```jsonc
// 500 Internal Server Error — GET /query/{id}
{
  "error": "Error fetching querys",
  "details": "..."
}
```

#### Status codes in use

| Code | Used for |
|---|---|
| `200` | Successful read, update, respond, close, assign. |
| `201` | New query created; new self-declaration draft created. |
| `400` | Validation failure (word limits, bad JSON, invalid type/id, business-rule violation like "already closed" or "draft cannot be responded"). |
| `403` | Authorization failure — wrong turn in the cycle, not the owner/assignee, not a matching lead. |
| `404` | Record not found for the given id. |
| `500` | Unhandled exception; body includes an `error` label and a `details` string from the caught exception. |

A minority of routes (e.g. `GET /admins`, `GET/POST /recent-activity`, `GET /dashboard`) return `fastapi.responses.JSONResponse` directly instead of going through `log_and_json_response`, so those calls are not captured in the request/response log.

---

## 6. API Documentation

All helpdesk endpoints below are mounted under `/api/compliance`; all annual-declaration endpoints under `/api/declarations`. Auth on every route is the `get_current_user` stub described in §2.4 — no bearer token is required by the running service today.

### Compliance queries — `query_routes.py`

**`POST /api/compliance/query`**
Raise a new query. Multipart form: `queryType` (COBCE/COI/ComplyShield/Gift/Other), `title` (≤500 words), `description` (≤5000 words), up to 6 `files`.

```jsonc
// request (multipart/form-data)
queryType=COI
title=Possible conflict with vendor engagement
description=Need guidance on an advisory role with a supplier...
files[]=disclosure.pdf

// 201 response
{
  "details": "Query has been created with query_id: QRY-2026-000482",
  "status": "Pending",
  "query_id": "QRY-2026-000482"
}
```

**`GET /api/compliance/query/{query_id}`**
Fetch a query, COBCE or COI record's details plus its full conversation (resolved via `get_type_and_model_by_id`, so the id can be any of the three types).

```jsonc
// 200 response
{
  "details": {
    "id": "QRY-2026-000482",
    "status": "Pending",
    "pendingAt": "Compliance Team",
    "createdBy": "STAFF001",
    "actor_name": "A. Sharma",
    "createdOn": "2026-09-20 10:14:02+05:30",
    "closureDate": null,
    "closedBy": null,
    "closed_by_name": null,
    "closedRemarks": null,
    "workflowStatus": null
  },
  "conversation": {
    "id": "QRY-2026-000482",
    "conversation": [
      { "actor": "User", "actorId": "STAFF001",
        "actor_name": "A. Sharma",
        "dateTime": "2026-09-20T10:14:02+05:30",
        "data": { "title": "...", "description": "..." },
        "files": [] }
    ]
  }
}
```

**`POST /api/compliance/query/{query_id}/respond`**
Add a response. Only valid when it is the caller's turn per `PendingAt`; admins must be the record's `AssignedTo`. Multipart: `message` (≤2000 words), up to 6 `files`.

```jsonc
// 403 response — wrong turn
{ "error": "Waiting for the admin's response before you can respond again" }
```

**`POST /api/compliance/query/{query_id}/close`**
Close a record. Owner or assigned admin only, and it must not already be `Closed`/`Completed`. Form field: `comment` (≤2000 words).

```jsonc
// 200 response
{ "status": "Closed" }
```

### Self-declarations (COBCE / COI) — `self_declaration_routes.py`

**`GET /api/compliance/self-declaration/form-config`**
Returns the static form schema (`self_declaration_config.py`): the COBCE row schema and the six COI question types.

**`POST /api/compliance/self-declaration`**
Unified create/update for both COBCE and COI drafts and submissions. Omit `id` to create, pass it to update an existing draft. `status=draft` saves without validation triggers; `status=submit` validates per-subtype (COI) and starts the response cycle.

```jsonc
// request (multipart/form-data) — COI submission
declaration_type=coi
status=submit
subType=OUTSIDE_ACTIVITY
formData={"companyName":"Acme Pvt Ltd","address":"...","activityType":"Advisory","remarks":"..."}

// 200 response
{
  "message": "Declaration submitted successfully",
  "id": "COI-2026-000117"
}
```

**`GET /api/compliance/self-declaration/{record_id}`**
Fetch a COBCE/COI record by id; owner or the type's lead only (403 `Unauthorized` otherwise, 400 if the id resolves to a non-self-declaration record).

### Response threads (generic) — `respond_routes.py`

**`GET /api/compliance/conversation/{record_id}`**
Type-agnostic conversation fetch (resolves query/COBCE/COI via `resolve_record`), paginated with `limit` (default 50, max 500) and `offset`.

**`POST /api/compliance/respond/{record_id}`**
Generic counterpart to `/query/{id}/respond`, usable for any of the three record types by id alone.

**`POST /api/compliance/close/{record_id}`**
Generic counterpart to `/query/{id}/close`.

### Dashboard & export — `dashboard_routes.py`

**`GET /api/compliance/dashboard`**
Unified list across annual declarations, self-declarations and queries. `tab=pending|all`, optional `type` (comma-separated: `annual_declarations,self_declarations,query`), `sub_type`, status/date filters, `page`/`page_size`. Visible types are always all three for the caller's own records; role flags additionally grant org-wide admin visibility per `get_dashboard_type_scope`.

```jsonc
// 200 response (shape)
{
  "items": [
    { "id": "QRY-2026-000482", "type": "Query", "sub_type": "COI",
      "response_status": "Pending", "overall_status": "Pending",
      "updated_on": "...", "pending_at": "Compliance Team" }
  ],
  "total": 1,
  "page": 1,
  "page_size": 10
}
```

**`GET /api/compliance/dashboard/export`**
Same filters as `/dashboard`; streams an `.xlsx` workbook (`StreamingResponse`, `Content-Disposition: attachment`) built from `core.constants.EXPORT_COLUMNS`.

### Admin / RBAC — `admin_routes.py`

**`GET /api/compliance/admins`**
Lists active leads for a record `type` (Query / Annual Declaration / Self Declaration), with fuzzy `search` on username/staff id and pagination.

**`PUT /api/compliance/assign/{record_id}`**
Assigns a lead (`staff_id` in JSON body) to a query/COBCE/COI record. Caller must be a matching type lead; target must actually hold the lead flag; cannot assign to the record's own creator; not available for Annual Declarations.

```jsonc
// request
{ "staff_id": "STAFF017" }

// 200 response
{ "status": "Admin assigned", "record_id": "QRY-2026-000482", "assigned_to": "STAFF017" }
```

### Recent activity — `recent_activity_routes.py`

**`GET /api/compliance/recent-activity`**
Top 5 most recently accessed records for the caller.

**`POST /api/compliance/recent-activity`**
Manually log a record view. JSON body: `record_id, record_type, title, status, created_on`, optional `sub_type, pending_at`.

### Files & health

**`GET /api/compliance/querys/files`**
`path` query param must start with the compliance blob prefix; returns a 15-minute SAS download URL.

**`GET /api/compliance/health`**
Liveness check — returns `{"status": "ok"}`.

### Annual declarations — `annual_declaration_router.py`

Mounted at `/api/declarations`; backed by `services/declaration_service.py` (admin CRUD, per-user save/submit, export) and `services/excel_sync_service.py` (bulk upload sync) and `services/head_summary_service.py` (org-level summary).

| Method | Path | Purpose |
|---|---|---|
| POST | `/create-declaration` | Admin: open a new annual declaration cycle. |
| GET | `/list-declarations` | Admin: paginated, filtered, Redis-cached list of cycles (§8). |
| PUT | `/edit-declaration/{declaration_id}` | Admin: update editable cycle fields. |
| GET | `/export-declarations` | Admin: export cycles to `.xlsx`. |
| GET | `/declaration-responses/{declaration_id}` | Per-question responses for a declaration/user. |
| POST | `/save-declaration/{declaration_id}` | User: save/submit their own answers. |
| POST | `/upload-declaration-file/{declaration_id}` | Admin: upload sync workbook → `excel_sync_service` (§4). |
| GET | `/download-declaration-file` | Download the template workbook. |
| GET | `/download-declaration-file/{declaration_id}` | Download the last uploaded workbook for a cycle. |
| GET | `/head-summary` | Org-level rollup of declaration completion. |
| GET | `/head-summary/export` | Export the head-summary rollup to `.xlsx`. |
| GET | `/user-declaration-status` | Caller's own status across cycles. |
| GET | `/declarationtypes` | Lists supported `DeclarationType` values. |

---

## 8. Caching Strategy

Caching is deliberately narrow: only one read path is cached today — the admin annual-declarations list (`services/declaration_service.list_declarations`). Everything else (queries, self-declarations, dashboard, recent activity) reads Postgres directly on every request.

- **Key shape:** `declarations:list:<hash of filters+page+page_size>` under the `LIST_DECLARATIONS_CACHE_PREFIX = "declarations:list:"` namespace.
- **TTL:** `LIST_DECLARATIONS_CACHE_TTL = 300` seconds (5 minutes).
- **Read-through:** `cache_get(key)` is checked first; on a miss the service queries Postgres, builds the paginated result, and writes it back with `cache_set(key, result, ttl=300)`.
- **Invalidation:** any mutation to a declaration cycle calls `cache_delete_pattern(LIST_DECLARATIONS_CACHE_PREFIX)`, wiping every cached page/filter combination rather than targeting a single key — simple, but means one edit invalidates all cached list variants.
- **Backend:** real Redis when `REDIS_URL` is set and reachable; otherwise the process-local in-memory dict fallback in `db/redis_cache.py` (§2.3) — meaning cache state is not shared across replicas/workers unless Redis is actually configured.
- **Serialization:** values are JSON-encoded with `default=str`, so datetimes and other non-JSON-native types round-trip as strings, not their original Python types.

> **Scope note.** No other module calls `cache_set`/`cache_get` directly — confirmed by a repo-wide search. If additional list/read endpoints need caching in the future, the same prefix + read-through + pattern-delete pattern used in `declaration_service.py` is the established convention to follow.

---

Generated from the `release/helpdesk` branch by reading `main.py`, `db/models/*.py`, `db/db_manager.py`, `db/redis_cache.py`, `core/*.py`, `utils/authorize.py`, `utils/deps.py`, `api/routes/helpdesk/*.py`, `api/routes/annual_dec/*.py`, `services/*.py`, `storage/storage_ops.py` and `utils/email_*.py`. Where behavior could not be confirmed from code alone it is called out inline as a note.
