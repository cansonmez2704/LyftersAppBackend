# GymHub — Project Documentation

> **Last updated:** March 2026  
> **Stack:** Django 5.2 · Django REST Framework · PostgreSQL · Redis · JWT Auth  
> **Purpose:** REST API backend for a fitness-focused social network

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture & App Structure](#2-architecture--app-structure)
3. [Configuration & Environment](#3-configuration--environment)
4. [API Endpoints Reference](#4-api-endpoints-reference)
5. [Data Models](#5-data-models)
6. [Key Shared Utilities (common/)](#6-key-shared-utilities-common)
7. [Authentication & Security](#7-authentication--security)
8. [Search System](#8-search-system)
9. [Rate Limiting](#9-rate-limiting)
10. [Running the Project](#10-running-the-project)
11. [Testing](#11-testing)
12. [Design Notes & Gotchas](#12-design-notes--gotchas)

---

## 1. Project Overview

GymHub is a Django REST API backend for a fitness social network. Users can:

- Create accounts, manage profiles, and follow each other
- Build workout plans composed of ordered exercises and sets
- Share posts (linked to workouts if desired) with the community
- React to and comment on posts and comments
- Search across users, exercises, and workouts using full-text + trigram search

The API is consumed by a separate frontend (referenced as `gymhub-frontend.vercel.app`). There is no server-rendered UI — Django is purely a JSON API.

---

## 2. Architecture & App Structure

```
GymHub-main/
├── core/               # Django project settings, root URLs, WSGI/ASGI
├── common/             # Shared utilities: reactions, follow logic, search, pagination, permissions
├── users/              # User model, profiles, followers, authentication views
├── workouts/           # Exercises, muscle groups, workouts, workout sets
├── community/          # Posts, comments, post media, reactions
├── manage.py
├── requirements.txt
└── pytest.ini
```

**Django apps and their responsibilities:**

| App | Responsibility |
|---|---|
| `core` | Settings, root URL config |
| `common` | Reusable logic: `toggle_reaction`, `toggle_follow`, `GlobalSearchView`, `FeedCursorPagination`, `IsOwnerOrReadOnly` permission |
| `users` | Custom `User` model, `UserProfile`, `UserFollower`, auth views |
| `workouts` | `MuscleGroup`, `Exercise`, `Workout`, `WorkoutExercise`, `WorkoutSet` |
| `community` | `Post`, `PostMedia`, `Comment`, `PostReaction`, `CommentReaction` |

---

## 3. Configuration & Environment

Settings live in `core/settings.py` and are driven by a `.env` file at the project root.

### Required `.env` variables

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | `True` or `False` |
| `DB_PASSWORD` | PostgreSQL password |
| `REDIS_URL` | Redis connection string, e.g. `redis://localhost:6379/0` |
| `IS_PRODUCTION` | `True` enables HTTPS-only security headers |

### Notable settings

- **Database:** PostgreSQL (`gym_hub` database, `postgres` user, port `5432`)
- **Cache:** Redis via `django-redis`. Sessions are also stored in Redis.
- **Auth:** JWT via `djangorestframework-simplejwt`. Access tokens expire in **30 minutes**, refresh tokens in **1 hour**.
- **Pagination:** Default page size is **10** records.
- **Media files:** Uploaded to `MEDIA_ROOT` (`/media/` URL prefix). Avatars go to `avatars/user_<id>/avatar.<ext>`, workout covers to `workout_covers/`, post media to `community/posts/<uuid>/`.
- **CORS:** Allowed origins are `localhost:3000` and `gymhub-frontend.vercel.app`.
- **API Docs:** Auto-generated OpenAPI schema at `/api/schema/`, Swagger UI at `/api/docs/`.

---

## 4. API Endpoints Reference

All endpoints are prefixed with `/api/v1/`.

### Auth & Users — `/api/v1/users/`

| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `sign-up/` | Register a new user. Returns tokens + user data. | Public |
| POST | `log-out/` | Blacklist the refresh token. | Required |
| PUT | `change-password/` | Change password; blacklists all existing tokens. | Required |
| POST | `token/refresh/` | Get new access token using refresh token. | Public |
| POST | `token/verify/` | Verify an access token is valid. | Public |
| GET/PATCH | `my-profile/` | View or update the authenticated user's own profile. | Required |
| GET | `profiles/<uuid>/` | View another user's profile. Returns full or mini data based on visibility. | Required |
| POST | `profiles/<uuid>/follow/` | Follow or unfollow a user (or send/cancel a follow request for private accounts). | Required |
| POST | `follow-requests/<uuid>/accept/` | Accept a pending follow request. | Required |
| POST | `follow-requests/<uuid>/reject/` | Reject/delete a pending follow request. | Required |
| GET | `profiles/<uuid>/followers/` | List a user's accepted followers. | Required |
| GET | `profiles/<uuid>/following/` | List users a profile is following. | Required |

### Workouts — `/api/v1/workouts/`

Routed through a DRF `DefaultRouter`.

| Resource | Endpoints generated | Notes |
|---|---|---|
| `workouts/` | List, Create, Retrieve, Update, Destroy | Owner-only write access |
| `exercises/` | List, Create, Retrieve, Update, Destroy | Likely admin-managed |

### Community — `/api/v1/community/`

| Resource | Endpoints generated | Notes |
|---|---|---|
| `posts/` | List, Create, Retrieve, Update, Destroy | Includes reaction and media sub-actions |
| `comments/` | List, Create, Retrieve, Update, Destroy | Threaded (max depth 3) |
| `feed/` | GET | Personalised feed view |

### Search — `/api/v1/search/`

| Method | Path | Query params | Description |
|---|---|---|---|
| GET | `search/` | `q` (required, min 2 chars), `type` (`all`/`users`/`workouts`/`exercises`) | Global hybrid full-text + trigram search |

---

## 5. Data Models

### users app

**`User`** (extends `AbstractUser`)
- Adds a `uuid` (UUIDField) as the public-facing identifier. The integer `pk` is never exposed in the API.
- Email is required (enforced by `CustomUserManager`).

**`UserProfile`** (OneToOne with `User`, auto-created on user save)
- `avatar` — uploaded image; falls back to `/static/images/default-avatar.png`
- `is_public` — controls follower visibility and follow request flow
- `bio`, `height` (cm, 50–300), `weight` (kg, 20–500), `gender`, `birth_date`
- `followers_count`, `following_count` — denormalised counters, updated atomically
- `search_vector` — PostgreSQL `SearchVectorField` indexed with GIN; built from `username` (weight A) + `bio` (weight B)

**`UserFollower`**
- `from_user` → `to_user` with a `status` of `PENDING` or `ACCEPTED`
- Constraints: unique pair, no self-following
- Database indexes on `(from_user, status)`, `(to_user, status)`, `(to_user, created_at)`

### workouts app

**`MuscleGroup`** — `name`, `slug`, `description`. Ordered by name.

**`Exercise`**
- `exercise_type`: `cardio`, `calisthenics`, `weightlifting`
- `movement_type`: `compound`, `isometric`, `isolation`
- `difficulty`: `beginner`, `intermediate`, `advanced`
- `muscles`: M2M to `MuscleGroup`
- `instructions`, `video_url`, `equipment_needed`
- `search_vector` — GIN indexed; rebuilt on save and when muscles change

**`Workout`**
- Owned by a `User`
- `visibility`: `private` or `public`
- `is_template` — marks the workout as a reusable template
- `exercises`: M2M through `WorkoutExercise`
- `search_vector` — GIN indexed

**`WorkoutExercise`** (through table)
- `order` (0-indexed display order), `notes`
- Constraint: unique `(workout, exercise, order)`

**`WorkoutSet`**
- Belongs to `WorkoutExercise`
- `reps`, `weight` + `weight_unit` (`KG` / `LBS`), `duration_seconds`
- Ordered by `set_number`; unique `(workout_exercise, set_number)`

### community app

**`Post`**
- `post_type`: `general`, `workout`, `progress`, `question`, `review`
- `visibility`: `public`, `followers`, `private`
- `linked_workout`: optional FK to `Workout`
- `slug`: auto-generated from `title + uuid[:8]`
- Denormalised: `likes_count`, `dislikes_count`, `comments_count`
- Soft-delete via `is_deleted`; archiving via `is_archived`
- `reaction_score` property: `likes_count - dislikes_count`

**`PostMedia`**
- Attached to a post; supports images (max 10 MB) and videos (max 100 MB)
- `clean()` validates extension matches `media_type`
- `order` for display sequence

**`Comment`**
- Self-referential via `parent` (for replies)
- Max nesting depth: **3 levels**
- Soft-deleted via `is_deleted`
- Denormalised `likes_count`, `dislikes_count`

**`PostReaction` / `CommentReaction`**
- `reaction_type`: `like` or `dislike`
- One reaction per user per post/comment (unique constraint)

---

## 6. Key Shared Utilities (common/)

### `common/reactions.py` — `toggle_reaction()`

Generic function used by both post and comment reaction views. Handles three cases atomically inside a database transaction:

1. **No existing reaction** → create it, increment the counter
2. **Same reaction exists** → delete it (toggle off), decrement the counter
3. **Different reaction exists** → switch it, decrement old counter, increment new counter

Uses `Greatest(F(...) - 1, Value(0))` to prevent counters going negative.

### `common/follow.py` — `toggle_follow()`

Generic follow/unfollow function. Behaviour depends on target profile visibility:

- **Public profile:** immediate follow, counters updated atomically
- **Private profile:** creates a `PENDING` follow request
- **Existing accepted follow:** unfollows, decrements counters
- **Existing pending request:** cancels the request

Uses `select_for_update()` with deterministic lock ordering (sorted PKs) to prevent deadlocks.

### `common/permissions.py` — `IsOwnerOrReadOnly`

Custom DRF permission. Write access requires the requesting user to be the object owner (checked via `owner`, `author`, or `user` attribute) or a staff member. Safe HTTP methods (GET, HEAD, OPTIONS) are always allowed.

### `common/pagination.py` — `FeedCursorPagination`

Cursor-based pagination used on feed and follower/following list views (more stable than page-number pagination for real-time feeds).

### `common/search.py` — `GlobalSearchView`

See [Section 8](#8-search-system).

---

## 7. Authentication & Security

- **JWT authentication** via `djangorestframework-simplejwt`
- **Token blacklisting** is enabled — logout and password change both invalidate tokens server-side
- **Public identifier:** All user-facing lookups use `uuid` (UUIDField), never the database integer PK
- **Avatar upload validation:** Only `jpg`, `jpeg`, `png`, `webp` extensions accepted at the model level
- **CORS:** Restricted to localhost dev and the known Vercel frontend origin
- **Production hardening** (when `IS_PRODUCTION=True`): SSL redirect, secure cookies, HSTS (1 year, with subdomains + preload), `X-Content-Type-Options`

---

## 8. Search System

`GET /api/v1/search/?q=<term>&type=<all|users|workouts|exercises>`

Implemented in `common/search.py` as a **hybrid search** combining:

1. **PostgreSQL Full-Text Search (FTS)** using `SearchRank` against pre-built `search_vector` fields (GIN indexed). Threshold: rank ≥ 0.05.
2. **Trigram Similarity** (`TrigramSimilarity`) for typo tolerance against the primary name field. Threshold: similarity ≥ 0.15.

The final `rank` annotation is `Greatest(fts_rank, trigram_sim)`. Results are ordered by this rank descending, capped at **10 per type**.

**Search vectors are built asynchronously** via Django signals (`post_save`, `m2m_changed`) using `transaction.on_commit()` to avoid blocking the save operation.

**Visibility rules in search:**
- Users: only public profiles (or the requester's own)
- Workouts: only public workouts (or the owner's own)
- Exercises: all (no visibility restriction)

**Rate limit:** 30 requests/minute per authenticated user.

---

## 9. Rate Limiting

Configured in `REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']`:

| Throttle | Rate | Applied to |
|---|---|---|
| `anon` | 100/day | Unauthenticated requests |
| `user` | 2000/day | Authenticated requests (default) |
| `reaction_spam` | 20/min | Reaction endpoints |
| `search` | 30/min | Global search endpoint |

---

## 10. Running the Project

### Prerequisites

- Python 3.11+
- PostgreSQL (database name: `gym_hub`)
- Redis

### Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create .env file at project root (see Section 3 for required variables)

# 3. Apply migrations
python manage.py migrate

# 4. Create a superuser
python manage.py createsuperuser

# 5. Run development server
python manage.py runserver
```

### Production

Use `gunicorn` (WSGI) or `uvicorn` (ASGI) — both are in `requirements.txt`.

```bash
gunicorn core.wsgi:application --bind 0.0.0.0:8000
# or
uvicorn core.asgi:application --host 0.0.0.0 --port 8000
```

Static files are served via `whitenoise`.

---

## 11. Testing

Tests use `pytest` (configured in `pytest.ini`) with `pytest-django`.

```bash
pytest
```

Test files:

| File | Covers |
|---|---|
| `users/tests/test_auth.py` | Registration, login, logout, token refresh |
| `users/tests/test_profile.py` | Profile retrieval and update |
| `users/tests/test_social.py` | Follow, unfollow, accept/reject, follower lists |
| `community/tests/test_posts.py` | Post CRUD, visibility, reactions |
| `community/tests/test_comments.py` | Comment creation, threading, reactions |
| `workouts/tests.py` | Workout and exercise CRUD |

---

## 12. Design Notes & Gotchas

**Denormalised counters** — `likes_count`, `dislikes_count`, `comments_count`, `followers_count`, `following_count` are all stored directly on the model rather than computed via `COUNT()` queries. They are updated atomically using `F()` expressions and `select_for_update()`. This improves read performance but means counters can theoretically drift if updates fail mid-transaction. `Greatest(..., Value(0))` guards against negative values.

**Deadlock prevention** — The follow and reaction utilities lock multiple rows using `select_for_update()` in sorted PK order, which is the standard pattern for avoiding deadlocks in concurrent transactions.

**Search vector updates are deferred** — All `search_vector` rebuilds happen inside `transaction.on_commit()` callbacks. This means a newly created record won't be searchable until after the transaction commits. There can be a brief lag if the signal handler fails.

**Avatar resizing is a TODO** — The `UserProfile` model includes a note that avatar resizing should be done asynchronously (e.g., via Celery) rather than blocking the request. This is not currently implemented.

**Comment depth is enforced twice** — Max depth of 3 is checked in both `clean()` and `save()`. The `save()` check is the safety net since `clean()` isn't always called (e.g., via the ORM directly).

**Private profile follow flow** — Following a private profile creates a `PENDING` `UserFollower` record. Counters are only updated when the target user explicitly accepts. Rejecting deletes the record entirely.

**UUID as public ID** — The integer database PK is never exposed. All public API URLs use `uuid` fields. This prevents enumeration attacks and makes IDs non-sequential.

**OpenAPI docs** — Auto-generated via `drf-spectacular`. Available at `/api/docs/` in development.
