# GymHubBackend

Backend API for GymHub — a fitness-oriented social platform. Users build an exercise library, compose workouts, share posts tied to their training, follow each other, and interact through comments and reactions.

Built with Django 5 + DRF, backed by PostgreSQL and Redis, with Celery for background work and S3-compatible storage for media in production.

---

## Tech Stack

**Core**
- Python 3.11+
- Django 5.0–5.2 / Django REST Framework 3.15+
- PostgreSQL 14+ (with `pg_trgm` + built-in full-text search)
- Redis 7+ (cache, session store, Celery broker/result backend)

**Authentication**
- `djangorestframework-simplejwt` — JWT access + refresh with rotation and blacklist
- `django-allauth` + `dj-rest-auth` — Google OAuth2 (PKCE enabled)

**Async / background**
- Celery 5.4+ with Redis broker
- `django-celery-beat` for scheduled maintenance (counter reconciliation, soft-delete purges)

**Storage & media**
- `django-storages` + `boto3` → S3 in production (signed URLs, 1h expiry, no public ACLs)
- `Pillow` for image processing (avatar resize, EXIF stripping, WebP encoding)
- `python-magic` for MIME sniffing on uploads

**API tooling**
- `drf-spectacular` for OpenAPI 3 schema + Swagger UI (dev only)
- `django-filter` for filter backends
- `django-cors-headers` for CORS

**Ops**
- `gunicorn` (WSGI) / `uvicorn` (ASGI, available for future async endpoints)
- `whitenoise` for static files in the Django process

See `requirements.txt` for exact versions.

---

## Architecture Overview

The project is organized into five Django apps with clear domain boundaries.

```
GymHubBackend/
├── core/         # Project settings, URL root, Celery config, exception handling
├── common/       # Shared helpers: permissions, pagination, reactions, follow,
│                 # search, validators, locking utilities, counter reconciliation
├── users/        # Auth (JWT + Google OAuth), profiles, follow graph
├── community/    # Posts, post media, threaded comments, reactions, feed
├── workouts/     # Exercises, muscle groups, workouts (with ordered exercises and sets)
└── tests/        # Cross-cutting tests
```

### Design highlights

**Thin views, reusable helpers.** Business logic lives in `common/` rather than in view methods. For example, `common/reactions.py::toggle_reaction` handles the like/dislike toggle for both post and comment reactions — atomic transaction, counter update via `F()` expressions with `Greatest(..., Value(0))` to prevent negative counts, and deadlock-safe parent locking.

**Deadlock prevention.** Operations that touch two profiles (follow/accept/reject) go through `common/utils.py::lock_profiles_for_update`, which sorts primary keys before `select_for_update()` to eliminate circular-wait deadlocks.

**Denormalized counters + scheduled reconciliation.** `Post.likes_count`, `Comment.comments_count`, etc. are mutated atomically on every event. A Celery beat job (`common/tasks.py::reconcile_counters`) runs every 6 hours and re-aggregates counters from the source of truth, so any drift from concurrent writes is self-healing.

**Hybrid search.** Users, workouts, and exercises are indexed with PostgreSQL full-text search (GIN-indexed `search_vector`) plus trigram similarity fallback for typo tolerance. Search vectors are rebuilt asynchronously via Celery on save (`rebuild_*_search_vector` tasks scheduled via `transaction.on_commit`, so they never run on rolled-back transactions).

**Cursor pagination for feeds.** `FeedCursorPagination` is ordered by `-created_at`; `PopularFeedCursorPagination` uses a composite cursor `(-likes_count, -created_at)`. Comments use limit/offset capped at 40 per page. Feed queries are backed by composite indexes including a dedicated `(is_deleted, visibility, -likes_count, -created_at)` index for the popular feed.

**Media pipeline.** Avatars are validated (extension + MIME sniff + size), EXIF-stripped, resized to max 500px, re-encoded as WebP (quality 85), and uploaded to a randomized path (`avatars/{uuid}/{hex}{ext}`) to prevent enumeration. Post media uses a similar validation pipeline with per-type size limits (10 MB images, 50 MB videos).

**Soft delete + nightly purge.** Posts and comments carry an `is_deleted` flag and stay readable by moderators; daily Celery beat jobs hard-delete records past the retention window.

**Throttling by scope.** Distinct throttle scopes for auth (`strict_auth`, 5/min), reactions (`reaction_spam`, 20/min), search (30/min), and social writes (60/min) — not a single global limit.

**Production hardening** is gated behind `USE_SECURE_PROXY=True`: HSTS (1 year), SSL redirect, secure cookies, S3 media storage, CORS narrowed to the production origin, and `X-Forwarded-Proto` trust.

---

## Local Setup Instructions

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Redis 7+
- `libmagic` (required by `python-magic`):
  - macOS: `brew install libmagic`
  - Debian/Ubuntu: `sudo apt-get install libmagic1`

### 1. Clone and create a virtualenv

```bash
git clone <repo-url>
cd GymHubBackend
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create the database

```bash
createdb gym_hub
# or from psql:
# CREATE DATABASE gym_hub;
```

The default config expects a local PostgreSQL with database `gym_hub`, user `postgres`, host `localhost`, port `5432`. Adjust `core/settings.py::DATABASES` if your setup differs.

### 3. Configure environment variables

```bash
cp .env.example .env
# open .env and fill in SECRET_KEY and DB_PASSWORD at minimum
```

See [Environment Variables](#environment-variables) below for the full list.

### 4. Start Redis

```bash
redis-server
```

### 5. Apply migrations and seed

```bash
python manage.py migrate
python manage.py createsuperuser
```

The `workouts` app ships a data migration that seeds the base `MuscleGroup` taxonomy (chest, lats, glutes, etc.) — no manual fixture loading needed.

### 6. Run the development server

```bash
python manage.py runserver
```

The API is now available at `http://localhost:8000/api/v1/`.

With `DEBUG=True`, the following dev-only routes are also mounted:
- `/api/docs/` — Swagger UI
- `/api/schema/` — OpenAPI schema
- `/accounts/` — allauth HTML flows (only useful for Google OAuth dev setup)
- `/admin/` — Django admin

### 7. Start Celery (in separate terminals)

```bash
# Worker
celery -A core worker -l info -Q default,media,maintenance --concurrency=4

# Beat scheduler (for periodic jobs: counter reconciliation, soft-delete purges)
celery -A core beat -l info
```

### 8. Running the tests

```bash
python manage.py test
```

### 9. Google OAuth (optional, for dev)

Google OAuth credentials are configured via the Django admin as an allauth `SocialApp` record (not via environment variables, despite the placeholder keys in `.env.example`). Visit `/admin/socialaccount/socialapp/add/` after creating a superuser.

---

## Environment Variables

All environment variables are read from `.env` at the repo root via `python-dotenv`. `.env` is gitignored; use `.env.example` as the template.

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | **Yes** | — | Django secret key. Use a long random string; the app refuses to start without it. |
| `DEBUG` | No | `False` | `True` enables debug mode, Swagger UI, allauth HTML routes, and local media serving. |
| `ALLOWED_HOSTS` | No | empty | Comma-separated list (e.g., `localhost,127.0.0.1,api.example.com`). |
| `DB_PASSWORD` | **Yes** | — | Password for the PostgreSQL `postgres` user. |
| `USE_PGBOUNCER` | No | `False` | Set to `True` when running behind pgBouncer in transaction-pooling mode; disables server-side cursors. |
| `REDIS_URL` | **Yes** | — | Redis connection URL used for cache and as the Celery broker (e.g., `redis://127.0.0.1:6379/1`). |
| `REDIS_RESULT_URL` | No | `redis://localhost:6379/1` | Celery result backend. Use a different DB number than `REDIS_URL` to isolate results from cache. |
| `USE_SECURE_PROXY` | No | `False` | **Production gate.** Enables HSTS, SSL redirect, secure cookies, S3 storage, and proxy-header trust. |
| `AWS_ACCESS_KEY_ID` | Prod only | — | Only read when `USE_SECURE_PROXY=True`. |
| `AWS_SECRET_ACCESS_KEY` | Prod only | — | Only read when `USE_SECURE_PROXY=True`. |
| `AWS_STORAGE_BUCKET_NAME` | Prod only | — | S3 bucket for media (and static, if configured). |
| `AWS_S3_REGION_NAME` | Prod only | — | e.g., `eu-north-1`. |

---

## API Overview

All endpoints are prefixed with `/api/v1/`. Authenticated endpoints expect an `Authorization: Bearer <access_token>` header.

### Authentication (`/api/v1/users/` and `/api/v1/auth/`)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/users/sign-up/` | Register a new user (email + password). |
| `POST` | `/users/token/refresh/` | Exchange a refresh token for a new access token (rotation + blacklist enabled). |
| `POST` | `/users/token/verify/` | Verify an access token is still valid. |
| `POST` | `/users/log-out/` | Blacklist the current refresh token. |
| `POST` | `/users/change-password/` | Change password; blacklists all active refresh tokens for the user. |
| `POST` | `/users/auth/google/` | Google OAuth2 login (accepts Google ID token). |
| `GET` | `/users/auth/google/client-id/` | Returns the configured Google OAuth client ID for the frontend. |
| `*` | `/auth/*` | `dj-rest-auth` built-in routes (password reset, etc.). |

Access tokens live 15 minutes; refresh tokens live 7 days and rotate on every refresh. Previous refresh tokens are blacklisted on rotation.

### Profiles & follow graph (`/api/v1/users/`)

| Method | Path | Purpose |
|---|---|---|
| `GET / PATCH` | `/my-profile/` | The authenticated user's own profile. |
| `GET` | `/profiles/<uuid>/` | Another user's profile (enforces public/followers-only visibility). |
| `POST / DELETE` | `/profiles/<uuid>/follow/` | Follow or unfollow a user. For private accounts this creates a `PENDING` request. |
| `POST` | `/follow-requests/<uuid>/accept/` | Accept an incoming follow request. |
| `POST` | `/follow-requests/<uuid>/reject/` | Reject an incoming follow request. |
| `GET` | `/follow-requests/` | List incoming pending follow requests (for private accounts). |
| `GET` | `/profiles/<uuid>/followers/` | Paginated follower list. |
| `GET` | `/profiles/<uuid>/following/` | Paginated following list. |
| `GET` | `/suggestions/` | Profile suggestions for the authenticated user. |

Profiles are addressed by UUID publicly — database integer PKs are never exposed.

### Workouts (`/api/v1/workouts/`)

Standard DRF viewset routes:

| Method | Path | Purpose |
|---|---|---|
| `GET / POST` | `/` | List workouts (filtered by visibility and the caller's access) / create. |
| `GET / PATCH / DELETE` | `/<id>/` | Workout detail. |
| `GET / POST` | `/exercises/` | Exercise library (list + create). |
| `GET / PATCH / DELETE` | `/exercises/<id>/` | Exercise detail. |

Workouts contain ordered `WorkoutExercise` rows, each with nested `WorkoutSet` rows (reps/weight/duration). List endpoints use a lightweight serializer; detail endpoints return the full nested structure with `prefetch_related` to avoid N+1.

### Community (`/api/v1/community/`)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/feed/` | Personalized feed (cursor-paginated, ordered by `-created_at`). |
| `GET / POST` | `/posts/` | List / create posts. Supports ordering by `popular` for the `(-likes_count, -created_at)` cursor. |
| `GET / PATCH / DELETE` | `/posts/<uuid>/` | Post detail. Delete is a soft delete. |
| `POST` | `/posts/<uuid>/react/` | Like or dislike a post. Idempotent toggle. |
| `GET / POST` | `/posts/<uuid>/comments/` | Top-level comments on a post. |
| `GET / PATCH / DELETE` | `/comments/<uuid>/` | Single comment detail (soft delete). |
| `GET` | `/comments/<uuid>/replies/` | Paginated replies to a comment (max 3 levels deep). |
| `POST` | `/comments/<uuid>/react/` | Like or dislike a comment. |

Post visibility is one of `public`, `followers`, `private`. Visibility is enforced both at the queryset level (for list endpoints) and at the permission level (for detail/comment endpoints) via `common.permissions.CanCommentOnPost`.

### Search (`/api/v1/search/`)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/search/?q=<query>&type=<users\|workouts\|exercises\|posts>` | Global search across domain entities. Throttled to 30 requests/min. Uses PostgreSQL FTS + trigram similarity with ranked scoring. |

### API documentation

When `DEBUG=True`:
- `GET /api/docs/` — Swagger UI
- `GET /api/schema/` — OpenAPI 3 schema (JSON)

---

## Periodic Tasks

Managed by Celery Beat (`celery -A core beat`).

| Task | Schedule | Purpose |
|---|---|---|
| `reconcile_counters` | Every 6 hours | Recomputes denormalized counters (likes, dislikes, comments) from source of truth via GROUP BY aggregates. Self-heals any drift from concurrent writes. |
| `purge_soft_deleted_posts` | Daily, 03:00 | Hard-deletes posts past their soft-delete retention window. |
| `purge_soft_deleted_comments` | Daily, 03:15 | Hard-deletes comments past their soft-delete retention window. |

Search vector rebuilds (`rebuild_profile_search_vector`, `rebuild_workout_search_vector`, `rebuild_exercise_search_vector`) are enqueued on model save via `transaction.on_commit`, not on a schedule.

---

## Project Layout Reference

```
core/
├── settings.py       Single-file settings, env-gated production hardening
├── urls.py           API root + dev-only doc routes
├── celery.py         Celery app, queue routing, beat schedule
└── exception.py      Custom DRF exception handler

common/
├── permissions.py    IsOwnerOrReadOnly, IsAuthorOnly, CanCommentOnPost, ...
├── pagination.py     FeedCursorPagination, PopularFeedCursorPagination, ...
├── reactions.py      toggle_reaction — atomic like/dislike helper
├── follow.py         toggle_follow — follow request lifecycle
├── search.py         GlobalSearchView — hybrid FTS + trigram search
├── validators.py     validate_real_content_type, validate_media_size
├── utils.py          lock_profiles_for_update — deadlock-safe locking
└── tasks.py          reconcile_counters (Celery beat)

users/, community/, workouts/
├── models.py         Domain models + managers + indexes
├── serializers.py    List vs detail, read vs write splits
├── views.py          Viewsets / APIViews delegating to common helpers
├── urls.py           App-scoped routes
├── tasks.py          Async work (search vector rebuilds, purges)
├── signals.py        post_save hooks → on_commit → Celery enqueue
└── tests/            Integration tests via APITestCase
```
