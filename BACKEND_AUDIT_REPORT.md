# GymHub Backend — Deep Audit Report
> Date: 2026-04-16 (original) · **Re-audited: 2026-04-17** · **HIGH + MEDIUM sweep: 2026-04-17 (evening)**
> Scope: API surface, security (OWASP), performance (N+1), stability, database health

This report tracks every finding from the original audit against the working tree. The **2026-04-17 evening sweep** closes all HIGH items and the MEDIUM items that were real correctness bugs; a handful of MEDIUMs were deliberately left open because fixing them would be premature optimization (justified per item below).

Every finding is classified by severity:
- `CRITICAL` — Must fix immediately. Security, data loss, or outage risk.
- `HIGH` — Fix before next production deploy.
- `MEDIUM` — Should fix soon; harms quality, performance, or DX.
- `LOW` — Nice-to-have / polish.

…and by status (added 2026-04-17):
- `[FIXED]` — addressed and verified in code.
- `[PARTIAL]` — partially addressed; remaining work or bug introduced.
- `[OPEN]` — no code change yet.
- `[DEFERRED]` — intentionally left as-is (premature, speculative, or requires architectural choice).

---

## 0. Progress Snapshot — 2026-04-17 evening sweep

### Fully closed after the sweep
- **CRITICAL** — all five closed in the morning pass; no regressions remain.
- **HIGH** — all sixteen items closed (API-1, API-2, API-4, SEC-1, SEC-2, SEC-3, PERF-1, PERF-2, PERF-3, PERF-4, PERF-5, STAB-1, STAB-2, STAB-3, STAB-4, DB-1).
- **MEDIUM correctness fixes** — API-3, SEC-4, SEC-5, SEC-6, PERF-9, STAB-5, STAB-6, DB-3, DB-4 and the actionable slice of API-5 (`is_public` toggle).
- **LOW** — all nine closed in the earlier pass (tracked in § 8).

### Deliberately deferred as premature optimization or out-of-scope
- **API-5** — broad new feature endpoints (account deletion, block list, follow-requests list). These are product features, not fixes. Only the `is_public` toggle gap was addressed.
- **API-6** — bulk endpoints. No identified pain point in the current single-object flow; speculative.
- **PERF-6** — Redis caching layer. Classic premature optimization; requires invalidation design and would change data-freshness semantics before any measured hotspot exists.
- **PERF-7** — parallel search queries. Three sequential FTS queries is fine; making them concurrent requires async views.
- **PERF-8** — `FullUserProfileSerializer.get_follow` N+1. The audit warns about lists, but no list endpoint currently uses this serializer (lists go through `MiniUserProfileSerializer`). Speculative preventive fix.
- **STAB-7** — Redis circuit breaker / graceful degradation. Adds fallback logic for scenarios that may never occur; also conflicts with the project rule against adding error handling for hypothetical failures.
- **DB-2** — partial index on `is_deleted=False` for feed queries. The composite index on `["is_deleted", "is_archived", "-created_at"]` already exists; swapping it for a partial index is an optimization without load data showing it's a hotspot.
- **DB-9** — sentinel user for post/comment authorship after account deletion. Requires a product decision (who owns orphaned content? what does moderation look like?).
- **ARC-4** — dependency pinning (`>=` vs `==`). Low-risk and better solved with `pip-compile` / a lockfile than by manually editing `requirements.txt`.

### Migrations generated & applied in this pass
- `community/0005_commentreaction_commentreaction_user_idx_and_more.py` — leading-user indexes on both reaction tables.

Run-level verification: `python manage.py check` → 0 issues.

---

## Table of Contents

1. [Critical Vulnerabilities](#1-critical-vulnerabilities)
2. [API Surface & Functional Gaps](#2-api-surface--functional-gaps)
3. [Security & OWASP Findings](#3-security--owasp-findings)
4. [Performance Anti-Patterns (N+1, Caching)](#4-performance-anti-patterns-n1-caching)
5. [Stability & Resilience](#5-stability--resilience)
6. [Database & Schema Health](#6-database--schema-health)
7. [Architectural Recommendations](#7-architectural-recommendations)
8. [Summary Checklist](#8-summary-checklist)

---

## 1. Critical Vulnerabilities

All five CRITICAL items and the three regressions that surfaced during the first fix pass are closed. Details for each are preserved in git history (commit `b8de595` and the subsequent evening sweep). Summary:

- `CRITICAL-A1` `[FIXED]` — PII split via `OwnProfileSerializer` / `FullUserProfileSerializer`.
- `CRITICAL-A2` `[FIXED]` — `validate_password` + `confirm_password` equality check.
- `CRITICAL-A3` `[FIXED]` — JWT lifetimes 15m/7d with rotation + blacklist + algorithm pin.
- `CRITICAL-A4` `[FIXED]` — `Comment.uuid` and `Exercise.uuid` are now `unique+non-null+indexed`; every viewset routes on `uuid`.
- `CRITICAL-A5` `[FIXED]` — comment creation resolves `post` from the nested URL kwarg; no writable `post` FK on the serializer.

---

## 2. API Surface & Functional Gaps

### `API-1` `[FIXED]` HIGH — Inconsistent URL conventions
The `/api/v1/workouts/workouts/` double prefix is gone. `workouts/urls.py` now registers `WorkoutViewSet` directly at the app root and nests `exercises` under the same prefix, so the canonical URLs are `/api/v1/workouts/`, `/api/v1/workouts/<uuid>/`, `/api/v1/workouts/exercises/`, `/api/v1/workouts/exercises/<uuid>/`. Remaining cosmetic inconsistencies (kebab vs word case on `/sign-up/` etc.) were left in place; renaming them is client-breaking churn with no functional payoff.

### `API-2` `[FIXED]` HIGH — Auth endpoints not versioned
`dj_rest_auth` now mounts at `/api/v1/auth/` rather than `/api/auth/`. The allauth HTML routes (`/accounts/`) only register when `DEBUG=True` — production traffic uses the JWT endpoints under `/api/v1/users/` and `/api/v1/auth/`.

### `API-3` `[FIXED]` MEDIUM — Logout now returns `204 No Content`
`LogoutView` returns `204` with no body instead of `205 Reset Content`.

### `API-4` `[FIXED]` HIGH — Missing RESTful nested routes
Added `GET /api/v1/community/comments/<uuid:parent_uuid>/replies/` so clients can paginate reply threads without a query-param filter. `CommentViewSet.get_queryset` now scopes by `parent_uuid` when the replies route is hit, and returns only top-level comments when the `/posts/<uuid>/comments/` list route is hit. Reactions remain RPC-style (`POST /posts/<uuid>/react/`, `POST /comments/<uuid>/react/`) — splitting into `POST`/`DELETE` resource operations is an API-breaking redesign with no correctness payoff, and the toggle API is already in use. Marked closed; a future `v2` can resource-ify reactions cleanly.

### `API-5` `[PARTIAL][DEFERRED]` MEDIUM — Missing / broken CRUD endpoints
- `is_public` is now exposed on `OwnProfileSerializer`, so users can toggle their privacy via `PATCH /my-profile/`. That was the one clear bug.
- The remaining items (`DELETE /my-account/`, follow-requests list, blocks, duplicate-workout, muscle-groups endpoint, password-reset, email-verification) are new features rather than fixes. Deferred until product scope is defined.

### `API-6` `[DEFERRED]` MEDIUM — No bulk operations
Premature. No measured pain point in the current single-object API; the nested `PostMedia` serializer already accepts multiple items per post create. Revisit when a concrete client request exists.

### `API-7` `[FIXED]` LOW — `/feed/` vs `/posts/` overlap
Class docstrings on `PostViewSet` and `FeedView` now explain the distinction.

---

## 3. Security & OWASP Findings

### `SEC-1` `[FIXED]` HIGH — `/posts/{uuid}/reactions/` now always paginates
The `reactions` action explicitly paginates via `self.paginator.paginate_queryset(...)` with `FeedCursorPagination`. The previous code fell back to an unpaginated JSON blob when `paginate_queryset` returned `None`, which could happen on the first page for a viral post.

### `SEC-2` `[FIXED]` HIGH — `PostDetailSerializer` no longer embeds all comments
`get_comments` is deleted. `PostDetailSerializer` exposes `comments_url` (absolute link to `/posts/<uuid>/comments/`) instead. Clients fetch comments with pagination on a dedicated endpoint.

### `SEC-3` `[FIXED]` HIGH — Queryset row duplication
`PostViewSet.get_queryset` and `CommentViewSet.get_queryset` now use a subquery (`author_id__in=_visible_author_ids(user)`) instead of joining through `author__incoming_followers__...`. Row count is bounded by the source table, not the M2M join width.

### `SEC-4` `[FIXED]` MEDIUM — `print()` in `core/celery.py`
`debug_task` uses `logger.debug(...)` instead of `print(...)`.

### `SEC-5` `[FIXED]` MEDIUM — `ALLOWED_HOSTS` strips empties
`ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]` — typos like `a,,b` no longer produce ghost empty-string hosts.

### `SEC-6` `[FIXED]` MEDIUM — `SECRET_KEY` must be non-empty
`core/settings.py` raises `ImproperlyConfigured` at import time if `SECRET_KEY` is missing or empty. Deployments that forget to set it fail fast.

### `SEC-7` `[FIXED]` LOW — DRF `authtoken` removed.
### `SEC-8` `[FIXED]` LOW — libmagic sniff window raised to 8 KiB.
### `SEC-9 / DB-6` `[FIXED]` LOW — `Post.description` capped at 5000 chars.

---

## 4. Performance Anti-Patterns

### `PERF-1` `[FIXED]` HIGH — `reconcile_counters` now uses grouped aggregation
Replaced the per-profile/per-post/per-comment loop with one `GROUP BY` query per counter. Runtime is bounded by the number of counter groups, not the number of rows. Includes a `_bulk_sync_counter` helper that only updates rows whose stored value diverges.

### `PERF-2` `[FIXED]` HIGH — `bulk_blacklist_tokens` uses bulk_create
Extracted `blacklist_user_tokens(user_id)` as a sync function: one `SELECT` for outstanding tokens, one filter against existing blacklist rows, one `bulk_create(..., ignore_conflicts=True)`. The Celery wrapper now just calls the sync helper.

### `PERF-3` `[FIXED]` HIGH — `UserProfile` signal is gated
`update_profile_search_vector` inspects `update_fields` and only re-queues the FTS rebuild when a search-relevant field (`bio`) changes. Counter bumps, avatar resizes, and other non-text updates skip the task.

### `PERF-4` `[FIXED]` HIGH — `PostWriteSerializer.create` no longer calls `full_clean`
Validation already runs inside `PostMediaWriteSerializer.validate`, which calls `instance.clean()` on the in-memory `PostMedia`. Dropping `full_clean()` from `create()` eliminates the per-file S3 `HEAD` request that `FileField.size` would trigger for remote storage.

### `PERF-5` `[FIXED]` HIGH — Post retrieve no longer prefetches comments/reactions
`PostViewSet.get_queryset` now prefetches only `media` on retrieve. Comments are a separate endpoint; reactions are fetched on demand.

### `PERF-6` `[DEFERRED]` MEDIUM — No caching layer
Premature optimization. Redis is in place but no view currently has measured latency that warrants cache invalidation complexity. Revisit after load testing.

### `PERF-7` `[DEFERRED]` MEDIUM — `GlobalSearchView` sequential queries
Premature. Three FTS queries per search is acceptable; concurrency requires async view support that we haven't adopted.

### `PERF-8` `[DEFERRED]` MEDIUM — `get_follow` N+1
Preventive-only. No list endpoint currently uses `FullUserProfileSerializer`; lists go through `MiniUserProfileSerializer`, which doesn't include `follow`. Revisit if a profile-list view ever adopts the full serializer.

### `PERF-9` `[FIXED]` MEDIUM — Workout list split
Added `WorkoutListSerializer` (no exercise tree); `WorkoutViewSet.get_queryset` only prefetches `workout_exercises__exercise__muscles` and `workout_exercises__sets` on retrieve/update actions. List pages stop pulling ~2400 related rows per workout.

### `PERF-10` `[FIXED]` LOW — `DISABLE_SERVER_SIDE_CURSORS` is gated by `USE_PGBOUNCER`.

---

## 5. Stability & Resilience

### `STAB-1` `[FIXED]` HIGH — `process_post_media` is dispatched
`PostWriteSerializer.create` and `update` now iterate the `PostMedia` rows returned by `bulk_create` and enqueue `process_post_media.delay(pk)` inside `transaction.on_commit(...)` for each image. Videos and missing PKs are skipped.

### `STAB-2` `[FIXED]` HIGH — Avatar validation in serializer
`OwnProfileSerializer.validate_avatar` and `FullUserProfileSerializer.validate_avatar` both check size before the model's `upload_to` callable runs. The model-level extension check remains as defense-in-depth.

### `STAB-3` `[FIXED]` HIGH — Conditional soft-delete
`CommentViewSet.perform_destroy` and `PostViewSet.perform_destroy` both use `UPDATE ... WHERE is_deleted=False` and only run counter decrements when `updated == 1`. Two concurrent DELETEs no longer double-decrement.

### `STAB-4` `[FIXED]` HIGH — `toggle_reaction` locks parent first
Rewritten to take `SELECT FOR UPDATE` on the parent (Post/Comment) as the first statement inside the atomic block, *before* reading or mutating the reaction row. Deadlock-prone lock ordering inversion is eliminated.

### `STAB-5` `[FIXED]` MEDIUM — Global DRF exception handler
`core.exceptions.custom_exception_handler` returns a consistent `{"error": {"code", "message", "details"}}` envelope for every error path, maps Django's `Http404` and `PermissionDenied` into DRF's flow, and logs unhandled exceptions before responding 500 with a generic message. Wired into `REST_FRAMEWORK["EXCEPTION_HANDLER"]`.

### `STAB-6` `[FIXED]` MEDIUM — `ChangePasswordView` revokes tokens synchronously
`ChangePasswordView` calls the new sync `blacklist_user_tokens(user.id)` before returning. The async Celery wrapper still exists for periodic cleanup, but the security-critical path no longer relies on a worker picking up the job.

### `STAB-7` `[DEFERRED]` MEDIUM — No Redis circuit breaker
Adds fallback logic for scenarios that may not occur, and conflicts with the project rule against speculative error handling. Revisit if we see a real Redis outage, or add a dedicated resiliency layer as part of production readiness.

### `STAB-8` `[FIXED]` LOW — Upload-size settings pinned.

---

## 6. Database & Schema Health

### `DB-1` `[FIXED]` HIGH — Leading-user indexes on reactions
`PostReaction` and `CommentReaction` each gained `Index(fields=["user", "-created_at"])`. Migration `community/0005` applied.

### `DB-2` `[DEFERRED]` MEDIUM — Partial index on `is_deleted=False`
The existing composite index on `("is_deleted", "is_archived", "-created_at")` already covers the feed filter. A partial-index swap is an optimization without load data showing the composite is the bottleneck.

### `DB-3` `[FIXED]` MEDIUM — Comment subtree depth preserved
`CommentViewSet.perform_destroy` no longer resets `parent=None, depth=0` on the deleted comment's direct children. The tree structure is preserved and the UI greys out the deleted node via `is_deleted=True` (Reddit-style).

### `DB-4` `[FIXED]` MEDIUM — `Post.slug` collision surface shrunk
`Post.save` now uses the first 12 hex chars of the UUID (~2.8e14 combinations) instead of 8 (~4.3e9). Collision risk drops below `UniqueConstraint` failure probability at any realistic row count.

### `DB-5` `[FIXED]` LOW — `Post.cover_image` validators.
### `DB-6` `[FIXED]` LOW — `Post.description` length cap.
### `DB-7` `[FIXED]` LOW — `WorkoutSet` reps-OR-duration constraint.
### `DB-8` `[FIXED]` LOW — Partial index on `UserProfile(is_public=True)`.
### `DB-9` `[DEFERRED]` INFO — Cascade vs sentinel user for account deletion requires product-level decision.

---

## 7. Architectural Recommendations

### `ARC-1` `[OPEN]` — Counters to a single source of truth
Unchanged. Triggers or on-read aggregation remain compelling, but the reconcile task is now cheap enough (one query per counter group) that this is no longer urgent.

### `ARC-2` `[PARTIAL]` — Split write and read models
`WorkoutListSerializer` vs `WorkoutSerializer` landed in this sweep. Profile serializers (`OwnProfileSerializer` vs `FullUserProfileSerializer`) split earlier. Post serializers already split.

### `ARC-3`, `ARC-5`, `ARC-6`, `ARC-7` — Unchanged, deferred as architectural work.

### `ARC-4` `[DEFERRED]` — Dependency pinning
See snapshot rationale above.

---

## 8. Summary Checklist — updated 2026-04-17 (evening)

Legend: `[x]` fixed · `[~]` partial · `[d]` deferred (with rationale) · `[ ]` open

```
REGRESSIONS (all resolved)
 [x] REGRESSION-1 / 2 / 3  — confirm-password, lookup_url_kwargs, perform_create

CRITICAL (all closed)
 [x] CRITICAL-A1 / A2 / A3 / A4 / A5

HIGH (all closed)
 [x] API-1        URL conventions — /workouts/workouts/ removed
 [x] API-2        auth endpoints under /api/v1/auth/; allauth gated by DEBUG
 [x] API-4        /comments/<uuid>/replies/ route added; reactions kept RPC-style by design
 [x] SEC-1        /posts/<uuid>/reactions/ always paginates via explicit paginator
 [x] SEC-2        PostDetailSerializer returns comments_url instead of embedded list
 [x] SEC-3        visibility filter uses subquery; no M2M row duplication
 [x] PERF-1       reconcile_counters rewritten as GROUP BY aggregation
 [x] PERF-2       bulk_blacklist_tokens uses bulk_create
 [x] PERF-3       UserProfile signal gated on update_fields
 [x] PERF-4       PostWriteSerializer.create skips full_clean (no S3 HEAD per file)
 [x] PERF-5       retrieve prefetch trimmed to media only
 [x] STAB-1       process_post_media enqueued on_commit after bulk_create
 [x] STAB-2       validate_avatar moved into serializers
 [x] STAB-3       atomic conditional soft-delete on Comment and Post
 [x] STAB-4       toggle_reaction locks parent first
 [x] DB-1         user-leading index on PostReaction and CommentReaction

MEDIUM
 [x] API-3        logout returns 204
 [~] API-5        is_public toggle fixed; new feature items deferred (product scope)
 [d] API-6        bulk endpoints — premature (no concrete client pain)
 [x] SEC-4        celery debug_task uses logger.debug
 [x] SEC-5        ALLOWED_HOSTS strips empties
 [x] SEC-6        SECRET_KEY validated at import time
 [d] PERF-6       no caching layer — premature without profiling data
 [d] PERF-7       sequential search queries — premature; needs async
 [d] PERF-8       get_follow N+1 — no list endpoint currently uses FullUserProfileSerializer
 [x] PERF-9       WorkoutListSerializer split; retrieve-only prefetch
 [x] STAB-5       global DRF exception handler with consistent envelope
 [x] STAB-6       ChangePasswordView revokes tokens synchronously
 [d] STAB-7       Redis circuit breaker — premature; also violates no-speculative-error-handling rule
 [d] DB-2         partial is_deleted index — optimization without load data
 [x] DB-3         Comment.depth tree preserved on soft-delete
 [x] DB-4         slug suffix expanded to 12 hex chars

LOW (all closed)
 [x] API-7        feed/posts distinction documented
 [x] SEC-7        authtoken removed
 [x] SEC-8        8 KiB sniff window
 [x] SEC-9        description cap
 [x] PERF-10      DISABLE_SERVER_SIDE_CURSORS gated
 [x] STAB-8       upload sizes pinned
 [x] DB-5         cover_image validators
 [x] DB-6         description bounded
 [x] DB-7         WorkoutSet constraint
 [x] DB-8         UserProfile partial index
 [d] DB-9         cascade vs sentinel — INFO, product decision

ARCHITECTURE
 [~] ARC-2        list/detail split (partial — done for Workout, Profile, Post)
 [d] ARC-4        dependency pinning — better solved with pip-compile
 [ ] ARC-1, 3, 5, 6, 7   — architectural, not in this sweep's scope
```

### Tally
- **5 CRITICAL** closed (morning + follow-up pass).
- **16 HIGH** closed (this evening sweep).
- **10 MEDIUM** closed, **6 MEDIUM** deliberately deferred as premature or product-scope.
- **9 LOW** closed, **1 LOW** deferred as INFO.

Migrations applied locally this pass: `community/0005`. `python manage.py check` → 0 issues.

---

### Reading order suggestion for anyone picking this up

1. The only item that directly blocks a production deploy and hasn't been touched is **none** — every severity-gated finding is either closed or explicitly deferred with rationale.
2. Before a real launch, the deferred items worth a one-time review are `PERF-6` (add caching after measuring), `DB-9` (sentinel user policy), and `ARC-4` (introduce `requirements.in` + `pip-compile`).
3. Architectural work (`ARC-1` counters, `ARC-7` notifications) remains on the backlog; none is a correctness bug.
