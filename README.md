# GymHub — Backend Development Roadmap

A production-grade Django REST API for a fitness social platform. This document serves as the active development guide covering current project state, upcoming work, security hardening, background tasks, scalability, and a concrete daily plan.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Current State](#2-current-state)
3. [Completing API Test Cases](#3-completing-api-test-cases)
4. [Security Hardening](#4-security-hardening)
5. [Background Tasks with Celery](#5-background-tasks-with-celery)
6. [Scalability](#6-scalability)
7. [One-Week Daily Plan](#7-one-week-daily-plan)

---

## 1. Project Overview

**Stack:** Django 5, Django REST Framework, PostgreSQL, Redis, JWT (SimpleJWT)

**Apps:**
| App | Responsibility |
|---|---|
| `users` | Registration, JWT auth, profiles, follow system |
| `workouts` | Exercises (admin-managed), user workouts with nested sets |
| `community` | Posts, comments (nested 3 levels), reactions, feed |
| `common` | Global search (FTS + trigram), pagination, shared permissions, follow/reaction toggle logic |

**Key technical choices already in place:**
- PostgreSQL full-text search with trigram similarity fallback
- Soft deletes on posts and comments
- Denormalized like/dislike/comment counts updated atomically (`select_for_update`)
- Cursor pagination on the feed
- UUID public keys on User, Workout, Post
- JWT token blacklist on logout and password change
- Redis as cache backend and session store

---

## 2. Current State

### What Is Done

| Area | Status |
|---|---|
| All models (15+ across 4 apps) | Complete |
| All views / viewsets (20+ endpoints) | Complete |
| Serializers (read + write, nested) | Complete |
| JWT auth, token blacklist | Complete |
| Follow system (pending/accepted states) | Complete |
| Post & comment reactions | Complete |
| Feed with visibility filtering | Complete |
| Global search endpoint | Complete |
| Production security flags (HTTPS, HSTS, secure cookies) | Complete (env-gated) |
| User auth tests | Complete |
| User profile tests | Complete |
| Social (follow) tests | Complete |
| Workout tests | Complete |
| Post tests | Complete |

### What Is Missing

| Area | Status |
|---|---|
| `community/tests/test_comments.py` | **Empty — needs full coverage** |
| `common/tests.py` (GlobalSearchView) | **Empty — needs full coverage** |
| Media upload validation tests | Missing |
| Nested serializer edge case tests | Missing |
| Background tasks | Not implemented |
| Celery setup | Not implemented |
| Advanced caching strategy | Partial (Redis configured, not fully utilized) |
| N+1 query audit | Not done |
| Security audit (brute force, rate limit review, IDOR check) | Not done |
| Docker / docker-compose | Not done |

---

## 3. Completing API Test Cases

### 3.1 Comment Tests (`community/tests/test_comments.py`)

The comment system is the most complex untested part of the codebase. Cover these scenarios in order:

**Basic CRUD**
- Authenticated user creates a top-level comment on a public post
- Author updates own comment
- Author soft-deletes own comment (body replaced, `is_deleted=True`)
- Staff can delete any comment
- Stranger cannot update or delete another user's comment

**Nested Replies (depth)**
- Create a reply to a comment (depth=1)
- Create a reply to a reply (depth=2)
- Attempt to create a 4th level reply — expect `400`
- Verify `depth` field is correct at each level

**Soft Delete Promotion Logic**
- Delete a parent comment that has children → children should be "promoted" (parent becomes None or the grandparent)
- Verify the children are still accessible after parent deletion
- Verify the deleted parent's body is masked (e.g., `"[deleted]"`) but the record is not removed

**Comment Count Denormalization**
- Create a comment → `post.comments_count` increments
- Delete a comment → `post.comments_count` decrements
- Verify count is correct after multiple creates/deletes

**Comment Reactions**
- Like a comment → `likes_count` increments
- Dislike a comment → `dislikes_count` increments
- Toggle the same reaction off → count decrements
- Switch from like to dislike → counts both update correctly
- Two users react to the same comment independently

**Visibility / Access Control**
- User cannot comment on a post they cannot see (private post, not follower)
- Follower-only post: follower can comment, stranger cannot
- Unauthenticated request → `401`

**Filtering**
- `GET /community/comments/?post=<uuid>` returns only comments for that post
- Deleted comments are excluded from list responses

---

### 3.2 Search Tests (`common/tests.py`)

**Full-Text Search**
- Search users by username and bio — returns matching profiles
- Public profiles appear in results; private profiles of other users do not
- Own private profile appears in your own search results

**Exercise Search**
- Search exercises by name — returns matching exercises
- Search by description/muscles (if indexed)

**Workout Search**
- Search public workouts — appear in results
- Own private workout appears when you search; stranger's private does not

**Type Filtering**
- `?q=test&type=users` returns only user results
- `?q=test&type=exercises` returns only exercise results
- `?q=test&type=workouts` returns only workout results
- `?q=test&type=all` returns results from all three

**Edge Cases**
- Empty query `?q=` → expect graceful response (empty or 400)
- Very short query (1 character) — verify it does not crash
- Query with special characters

**Rate Limiting**
- Exceed 30 requests/minute → expect `429 Too Many Requests`
- This is tricky to test in unit tests; use `override_settings` to lower the throttle limit or mock the cache

---

### 3.3 Media Upload Tests (add to `community/tests/test_posts.py`)

- Upload a valid image file (JPEG < 10MB) → success
- Upload a file exceeding 10MB → expect `400`
- Upload a video exceeding 100MB → expect `400`
- Upload an invalid extension (e.g., `.exe`) → expect `400`
- Upload more than 10 media items per post → expect `400`

---

## 4. Security Hardening

Security work falls into four categories: **authentication hardening**, **input & output validation**, **access control audit**, and **infrastructure headers**.

### 4.1 Authentication Hardening

**Brute Force Protection**
- Install `django-axes`. It tracks failed login attempts by IP and username.
- Configure to lock after N failures (e.g., 5 within 10 minutes).
- Add `axes.backends.AxesStandaloneBackend` to `AUTHENTICATION_BACKENDS`.
- Add `axes.middleware.AxesMiddleware` to `MIDDLEWARE` (before `AuthenticationMiddleware`).
- Write a test: make 6 failed login attempts → expect `403` on the 6th.

**JWT Token Hardening**
- Current access token TTL is 30 minutes — this is reasonable. Keep it.
- Verify the blacklist check is happening on every protected request (it is, since `JWTAuthentication` checks the blacklist automatically if `rest_framework_simplejwt.token_blacklist` is installed).
- Add `ROTATE_REFRESH_TOKENS = True` and `BLACKLIST_AFTER_ROTATION = True` to `SIMPLE_JWT` settings. This means every token refresh invalidates the old refresh token, preventing refresh token replay.
- Consider lowering refresh token TTL from 1 hour for a social fitness app (1-7 days is typical; 1 hour is very short and will frustrate users).

**Password Policy**
- Add Django's built-in password validators to `AUTH_PASSWORD_VALIDATORS`:
  - `UserAttributeSimilarityValidator`
  - `MinimumLengthValidator` (min 8)
  - `CommonPasswordValidator`
  - `NumericPasswordValidator`
- These are not in `settings.py` currently.

### 4.2 Input & Output Validation

**File Upload Security**
- The `PostMedia` model has file extension validation and size limits — good.
- Ensure the file content is also validated (not just the extension). A file named `evil.jpg` could still contain malicious content. Use Pillow's `Image.verify()` in the validator to confirm the file is actually an image.
- Store uploaded files outside the web root or use a CDN (S3/Cloudflare R2 in production). Never serve user-uploaded files from Django in production.

**Serializer Input Validation**
- Audit all `CharField` fields for max_length. Unlimited text fields are a DoS vector.
- `Post.title` — add max_length if not already set on the serializer.
- `Comment.body` — add max_length (e.g., 2000 chars).
- `Workout.name`, `Exercise.name` — verify max_length constraints exist at model level.

**IDOR (Insecure Direct Object Reference) Audit**
- The project uses UUIDs on User, Workout, and Post — this prevents sequential enumeration.
- Audit `WorkoutSet`, `WorkoutExercise`, `Comment` — these use integer PKs. Verify that the `get_queryset()` on their viewsets filters by ownership or visibility before returning results, so a user cannot access another user's private workout set by guessing an integer ID.

### 4.3 Rate Limiting Review

Current throttles (from settings):
- Anon: 100/day
- Auth user: 2000/day
- Search: 30/min

**Improvements:**
- Add a dedicated throttle for `RegisterView` (e.g., 10/hour per IP) to prevent account spam.
- Add a throttle for `LogoutView` and `ChangePasswordView` (e.g., 20/hour).
- Consider `ScopedRateThrottle` for fine-grained control per endpoint.

```python
# In the view:
throttle_scope = 'register'

# In settings:
'DEFAULT_THROTTLE_RATES': {
    'anon': '100/day',
    'user': '2000/day',
    'search': '30/min',
    'register': '10/hour',
    'auth_sensitive': '20/hour',
}
```

### 4.4 HTTP Security Headers

Django's `SecurityMiddleware` (already in MIDDLEWARE) covers most of these when `IS_PRODUCTION=True`. Verify the following are active:

| Header | Django Setting | Current Status |
|---|---|---|
| `HTTPS only` | `SECURE_SSL_REDIRECT = True` | Env-gated ✓ |
| `HSTS` | `SECURE_HSTS_SECONDS = 31536000` | Env-gated ✓ |
| `X-Content-Type-Options: nosniff` | `SECURE_CONTENT_TYPE_NOSNIFF = True` | Check |
| `X-Frame-Options: DENY` | `X_FRAME_OPTIONS = 'DENY'` | Check |
| `Referrer-Policy` | `SECURE_REFERRER_POLICY = 'strict-origin'` | Likely missing |
| `Permissions-Policy` | Not built into Django — add via middleware | Missing |

Add these to `settings.py` unconditionally (they are safe in development too):

```python
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
```

### 4.5 CORS Tightening

Current allowed origins include `gymhub-frontend.vercel.app`. Ensure:
- `CORS_ALLOW_ALL_ORIGINS = False` (it should be — you have an explicit list).
- `CORS_ALLOW_CREDENTIALS = True` only if you use cookies (you use JWT in headers, so this is probably not needed — set to `False`).
- `CORS_ALLOWED_METHODS` — restrict to only what the API needs (`GET, POST, PUT, PATCH, DELETE, OPTIONS`).

---

## 5. Background Tasks with Celery

### 5.1 Why Celery?

Your current sync operations that should become async tasks:
- **Search vector updates** — currently via Django signals (synchronous, blocking the request)
- **Follow/unfollow notifications** — no notifications exist yet, but they will need async delivery
- **Email sending** — registration confirmation, password change alerts
- **Cleanup jobs** — purge soft-deleted posts/comments older than 30 days
- **Analytics** — aggregate workout stats, leaderboard calculations

### 5.2 Setup

**Install:**
```bash
pip install celery redis django-celery-beat django-celery-results
```

**Add to `requirements.txt`:**
```
celery>=5.3.0
django-celery-beat>=2.6.0
django-celery-results>=2.5.0
```

**Create `core/celery.py`:**
```python
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

app = Celery('gymhub')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

**Update `core/__init__.py`:**
```python
from .celery import app as celery_app
__all__ = ('celery_app',)
```

**Add to `settings.py`:**
```python
CELERY_BROKER_URL = env('REDIS_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = 'django-db'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'

INSTALLED_APPS += [
    'django_celery_beat',
    'django_celery_results',
]
```

### 5.3 Tasks to Implement

**`users/tasks.py` — User Tasks**
```python
# Send welcome email after registration
@shared_task(bind=True, max_retries=3)
def send_welcome_email(self, user_id): ...

# Notify user of new follower
@shared_task
def send_follow_notification(follower_id, target_id): ...

# Update user search vector (move from signal)
@shared_task
def update_user_search_vector(profile_id): ...
```

**`community/tasks.py` — Community Tasks**
```python
# Purge soft-deleted posts older than 30 days
@shared_task
def purge_old_deleted_posts(): ...

# Notify post author of new comment
@shared_task
def send_comment_notification(comment_id): ...
```

**`workouts/tasks.py` — Workout Tasks**
```python
# Update workout search vector (move from signal)
@shared_task
def update_workout_search_vector(workout_id): ...
```

### 5.4 Periodic Tasks (Scheduled Jobs)

Use `django-celery-beat` to schedule:

| Task | Schedule |
|---|---|
| `purge_old_deleted_posts` | Every day at 2 AM UTC |
| `update_all_search_vectors` | Every hour (catch missed updates) |
| `generate_daily_stats` | Every day at midnight UTC |

Configure via Django admin (CeleryBeat periodic tasks) or in code via `CELERY_BEAT_SCHEDULE` in settings.

### 5.5 Running in Development

```bash
# Terminal 1 — Django dev server
python manage.py runserver

# Terminal 2 — Celery worker
celery -A core worker --loglevel=info

# Terminal 3 — Celery beat (periodic tasks)
celery -A core beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

### 5.6 Testing Celery Tasks

Use `CELERY_TASK_ALWAYS_EAGER = True` in test settings to run tasks synchronously during tests (no broker needed):

```python
# In test settings or conftest.py
@pytest.fixture
def celery_settings(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
```

---

## 6. Scalability

### 6.1 Database: Fix N+1 Queries First

N+1 is the most impactful quick win. Audit these endpoints:

**Feed (`/community/feed/`)**
- Post queryset should `select_related('author', 'author__profile')` and `prefetch_related('media')`.
- Verify this is already in `get_queryset()` — if not, add it.

**Comment list (`/community/comments/?post=<uuid>`)**
- `select_related('author', 'author__profile', 'parent')` is needed.

**Following/Follower lists**
- `select_related('from_user__profile', 'to_user__profile')`.

**Workout detail**
- Already prefetches exercises and sets — verify it also fetches `owner__profile`.

**How to detect N+1 in development:**
```bash
pip install django-debug-toolbar nplusone
```
Add `nplusone` to MIDDLEWARE in dev settings — it raises warnings or errors on N+1 queries automatically.

### 6.2 Caching Strategy

Redis is already configured. Use it:

**Cache exercise list** — Exercises change only when an admin updates them. Cache the full list for 1 hour:
```python
from django.core.cache import cache

def get_queryset(self):
    cached = cache.get('exercises_list')
    if cached:
        return cached
    qs = Exercise.objects.prefetch_related('muscles').all()
    cache.set('exercises_list', qs, timeout=3600)
    return qs
```
Invalidate in the admin action or `post_save` signal.

**Cache user profiles** — Profile data is read far more than it is written. Cache per UUID with a 5-minute TTL. Invalidate on profile update.

**Cache feed** — The feed query is the most expensive (joins, ordering, filtering). Consider caching per user with a short TTL (30-60 seconds). Alternatively, use Django's `cache_page` decorator only for anonymous endpoints.

**Cache the search index warm-up** — Search vector fields help, but trigram similarity on large datasets can be slow. Consider caching search results for common queries.

### 6.3 Database Indexes Audit

Check that the following are indexed (review migrations):

| Table | Columns | Reason |
|---|---|---|
| `users_userfollower` | `(from_user, status)` | Feed query filters by this |
| `users_userfollower` | `(to_user, status)` | Follower list query |
| `community_post` | `(is_deleted, is_archived, created_at)` | Feed + list query |
| `community_post` | `(author, created_at)` | Profile post list |
| `community_comment` | `(post, is_deleted)` | Comment list per post |
| `workouts_workout` | `(owner, visibility)` | Workout list query |
| `community_postreaction` | `(user, post)` | Reaction lookup |

Most of these are already in the models. Verify in the migrations.

### 6.4 Pagination Strategy

| Endpoint | Pagination Type | Why |
|---|---|---|
| Feed | Cursor | Correct — stable ordering, no offset drift |
| Comments | Limit/Offset | Acceptable for per-post comments |
| Followers/Following | Page Number | Acceptable — bounded by real-world follow counts |
| Search | Page Number | Acceptable |
| Workouts/Exercises | Page Number | Acceptable |

Consider moving all list endpoints to cursor pagination for consistency and performance at scale. Offset pagination becomes slow as offsets grow (DB must count all preceding rows).

### 6.5 Database Connection Pooling

In production, configure `PgBouncer` (connection pooler) in front of PostgreSQL. Django opens a new DB connection per request thread by default — connection pooling reduces PostgreSQL max_connections pressure dramatically.

Alternatively, use `django-db-geventpool` or `psycopg3`'s built-in pooling.

```python
# settings.py — production
DATABASES = {
    'default': {
        ...
        'CONN_MAX_AGE': 60,  # Reuse connections for 60 seconds
    }
}
```

### 6.6 Async Views (Optional, Future)

Django 5 supports fully async views. Your project uses Uvicorn (ASGI), which can serve async views. For now this is not a priority, but endpoints that do I/O-heavy work (file uploads, external API calls) would benefit from being `async def`.

### 6.7 Horizontal Scaling Readiness

Your app is already mostly stateless — JWT auth means no session stickiness needed. Checklist for horizontal scaling (multiple server instances):

- [x] Sessions stored in Redis (not local memory)
- [x] Cache in Redis (not local memory)
- [x] Static files served by WhiteNoise or CDN
- [ ] Media files — currently local filesystem. **Must move to S3 or equivalent** before running multiple instances (each instance would have a different local filesystem). Use `django-storages` + S3/R2.
- [ ] Celery workers can run on separate machines — broker (Redis) is already network-accessible.

---

## 7. One-Week Daily Plan

**Commitment:** 4–6 hours per day. Tasks are ordered by dependency — each day builds on the previous.

---

### Day 1 — Complete Comment Tests

**Goal:** Full coverage of `community/tests/test_comments.py`

**Morning (2h):**
- Set up test fixtures (helpers for creating users, posts, comments at different depths)
- Write tests for comment CRUD: create, update, delete (soft), staff override

**Afternoon (2–3h):**
- Write tests for nested replies and depth limit enforcement
- Write tests for soft delete promotion logic
- Write tests for comment visibility (respects post visibility)

**Evening (1h):**
- Write tests for comment reactions (like, dislike, toggle, switch)
- Write test for `comments_count` denormalization on Post
- Run full test suite, fix any failures

**Done when:** `test_comments.py` has at minimum 15–20 test methods covering all the scenarios in Section 3.1. `pytest` passes with no failures.

---

### Day 2 — Search Tests + Edge Cases

**Goal:** Full coverage of `common/tests.py` and media upload tests

**Morning (2h):**
- Write search tests: user search, exercise search, workout search
- Write type filtering tests (`?type=users`, etc.)
- Write access control tests (private profiles don't appear in others' search)

**Afternoon (2h):**
- Write edge cases: empty query, special characters, very long query strings
- Write rate limiting test (use `override_settings` to set `search` throttle to `2/min`, then make 3 requests)

**Evening (1–2h):**
- Write media upload validation tests (valid file, too large, bad extension)
- Run full test suite
- Commit: `test: complete comment, search, and media upload test coverage`

**Done when:** `common/tests.py` has search coverage. `pytest` passes cleanly.

---

### Day 3 — Security Part 1: Auth Hardening

**Goal:** Strengthen authentication and add password policy

**Morning (2h):**
- Add `django-axes` to `requirements.txt`
- Configure `AXES_FAILURE_LIMIT`, `AXES_COOLOFF_TIME` in settings
- Add `AxesMiddleware` and `AxesStandaloneBackend`
- Write test: 5 failed login attempts → 6th returns `403`

**Afternoon (2h):**
- Add `AUTH_PASSWORD_VALIDATORS` to settings (all 4 built-in validators)
- Add `ROTATE_REFRESH_TOKENS = True` and `BLACKLIST_AFTER_ROTATION = True` to `SIMPLE_JWT`
- Review refresh token TTL — extend to something user-friendly (e.g., `timedelta(days=7)`)
- Write test: weak password on registration returns `400` with validation error

**Evening (1–2h):**
- Add per-endpoint throttles for `RegisterView` and `ChangePasswordView` (Section 4.3)
- Write throttle tests
- Commit: `security: brute force protection, password validators, JWT hardening`

**Done when:** `django-axes` is installed and configured, password validators are active, throttles are tightened on sensitive endpoints.

---

### Day 4 — Security Part 2: Validation, Headers, IDOR Audit

**Goal:** Input validation, HTTP headers, access control audit

**Morning (2h):**
- Audit all `CharField` and `TextField` fields for `max_length` in serializers
- Add `max_length` where missing (`Comment.body`, `Post.title`, etc.)
- Add Pillow image content verification in `PostMedia` validator

**Afternoon (2h):**
- Add missing HTTP security headers to `settings.py`:
  - `SECURE_CONTENT_TYPE_NOSNIFF = True`
  - `X_FRAME_OPTIONS = 'DENY'`
  - `SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'`
- Review `CORS_ALLOW_CREDENTIALS` — set to `False` if not using cookies
- Review `WorkoutSet` and `WorkoutExercise` viewsets for IDOR: ensure `get_queryset` scopes by owner

**Evening (1–2h):**
- Write security-focused tests:
  - User A cannot access User B's private `WorkoutSet` by integer ID
  - Request with oversized `Comment.body` (over max_length) returns `400`
- Commit: `security: input validation, HTTP headers, IDOR audit`

**Done when:** All serializers have explicit max_length, headers are set, IDOR audit is done with tests.

---

### Day 5 — Background Tasks: Celery Setup

**Goal:** Celery is installed, configured, and first tasks are working

**Morning (2–3h):**
- Install `celery`, `django-celery-beat`, `django-celery-results`
- Create `core/celery.py` and update `core/__init__.py`
- Add Celery settings to `settings.py`
- Run migrations for `django_celery_results` and `django_celery_beat`
- Verify Celery worker starts: `celery -A core worker --loglevel=info`

**Afternoon (2h):**
- Move `UserProfile` search vector update from synchronous signal to Celery task (`users/tasks.py`)
- Move `Workout` search vector update to Celery task (`workouts/tasks.py`)
- Create `purge_old_deleted_posts` periodic task (`community/tasks.py`)
- Register periodic task in `CELERY_BEAT_SCHEDULE`

**Evening (1h):**
- Write tests for tasks using `CELERY_TASK_ALWAYS_EAGER = True`
- Verify that disabling the signal and switching to tasks does not break existing tests
- Commit: `feat(celery): async tasks for search vector updates and cleanup jobs`

**Done when:** Celery worker runs, two search vector tasks are async, cleanup task is periodic, tests pass.

---

### Day 6 — Scalability: N+1 Audit + Caching

**Goal:** Eliminate N+1 queries, implement caching on hot endpoints

**Morning (2h):**
- Install `django-debug-toolbar` and `nplusone` for dev
- Run the feed endpoint and exercise list in the shell/browser with query logging
- Audit `get_queryset` on `FeedView`, `CommentViewSet`, `FollowerListView`, `WorkoutViewSet`
- Add missing `select_related` and `prefetch_related` calls

**Afternoon (2h):**
- Implement cache on `ExerciseViewSet` list (1 hour TTL, invalidate on admin save)
- Set `CONN_MAX_AGE = 60` in database settings
- Review all `Page Number` paginated endpoints — document which ones should be migrated to cursor pagination eventually

**Evening (1–2h):**
- Add `django-storages` and document S3 configuration (do not configure yet — just add the settings scaffold with `USE_S3 = False` env gate)
- Write a quick performance note: measure response time of feed before and after N+1 fix using `time curl`
- Commit: `perf: eliminate N+1 queries, add exercise list cache, connection pooling`

**Done when:** No obvious N+1 queries in hot endpoints, exercise list is cached, connection age is configured.

---

### Day 7 — Docker, Documentation, Final Polish

**Goal:** Containerize the app, finalize API docs, write deployment checklist

**Morning (2h):**
- Write `Dockerfile` (multi-stage: builder + slim runtime)
- Write `docker-compose.yml` with services: `web`, `db` (PostgreSQL), `redis`, `celery_worker`, `celery_beat`
- Add `.env.example` with all required environment variables documented
- Verify `docker-compose up` starts all services without errors

**Afternoon (2h):**
- Review `drf-spectacular` schema output at `/api/docs/`
- Add missing `@extend_schema` decorators to views that have unclear auto-generated docs
- Document the 5 most complex endpoints (Feed, Search, Post reactions, Follow, Workout create) with request/response examples

**Evening (1–2h):**
- Run the full test suite one final time: `pytest --tb=short`
- Write a deployment checklist in this README (Section below)
- Commit: `chore: Docker setup, API documentation, deployment checklist`

**Done when:** `docker-compose up` runs the full stack, API docs are clean, all tests pass.

---

## Deployment Checklist (fill in on Day 7)

- [ ] All environment variables set (SECRET_KEY, DATABASE_URL, REDIS_URL, IS_PRODUCTION)
- [ ] `DEBUG = False`
- [ ] `ALLOWED_HOSTS` set to production domain
- [ ] `SECURE_SSL_REDIRECT = True`
- [ ] HSTS enabled
- [ ] Static files collected (`manage.py collectstatic`)
- [ ] Media files on S3 (not local filesystem)
- [ ] Database migrations applied
- [ ] Celery worker and beat running as systemd services or Docker containers
- [ ] Redis accessible from all app instances
- [ ] `django-axes` lockout alerts monitored
- [ ] Error tracking configured (Sentry or equivalent)

---

## Quick Reference

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=. --cov-report=term-missing

# Start Celery worker (after Day 5)
celery -A core worker --loglevel=info

# Start Celery beat (after Day 5)
celery -A core beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler

# Generate API schema
python manage.py spectacular --file schema.yml

# Start full stack with Docker (after Day 7)
docker-compose up --build
```
