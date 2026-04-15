# GymHub — Audit Fix Tasks
> Date: 2026-04-15
> Based on: Senior Backend / Security Audit (2026-04-14)

---

## CRITICAL — Fix These First

---

### [ ] CRITICAL-1: OAuth Redirects to Admin Panel
**File:** `core/settings.py:84`

Problem: `LOGIN_REDIRECT_URL = '/admin/'` — Google OAuth sends users to the Django admin after login.

Fix:
- Change `LOGIN_REDIRECT_URL` to point to the frontend OAuth callback URL.
- Change `LOGOUT_REDIRECT_URL` to point to the frontend home.
- Read the values from `.env` so they differ between dev and prod.

```python
LOGIN_REDIRECT_URL = os.getenv("FRONTEND_URL", "http://localhost:3000") + "/oauth/callback"
LOGOUT_REDIRECT_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
```

---

### [x] CRITICAL-2: All S3 Files Are World-Readable
**File:** `core/settings.py:292` (production block)

Problem: `AWS_DEFAULT_ACL = 'public-read'` — every avatar and media upload is a public S3 URL with no auth.

Fix:
- Remove `AWS_DEFAULT_ACL = 'public-read'`.
- Set `AWS_DEFAULT_ACL = None` (let bucket policy control access, not per-object ACLs).
- Set `AWS_QUERYSTRING_AUTH = True` so django-storages generates pre-signed URLs.
- Set `AWS_QUERYSTRING_EXPIRE = 3600` (1-hour link expiry).
- Confirm your S3 bucket has Block Public Access enabled.

```python
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = True
AWS_QUERYSTRING_EXPIRE = 3600
AWS_S3_FILE_OVERWRITE = False
```

---

### [x] CRITICAL-3: Custom Throttle Scopes Are Dead Code
**Files:** `core/settings.py:120-126`, `community/views.py`, `users/views.py`

Problem: `reaction_spam`, `search`, and `strict_auth` rates are defined in settings but no throttle class references them — zero rate limiting on reactions and auth endpoints.

Fix:
1. Create `common/throttles.py` with three throttle classes referencing those scopes.
2. Apply `ReactionSpamThrottle` to `react_to_posts` and `react_to_comments` actions.
3. Apply `StrictAuthThrottle` to login and registration views.
4. Apply `SearchThrottle` to `GlobalSearchView`.

```python
# common/throttles.py
from rest_framework.throttling import UserRateThrottle, AnonRateThrottle

class ReactionSpamThrottle(UserRateThrottle):
    scope = 'reaction_spam'

class SearchThrottle(AnonRateThrottle):
    scope = 'search'

class StrictAuthThrottle(AnonRateThrottle):
    scope = 'strict_auth'
```

---

### [x] CRITICAL-4: API Docs Exposed in Production
**File:** `core/urls.py:31-32`

Problem: `/api/docs/` and `/api/schema/` are publicly accessible — full API structure exposed to anyone.

Fix:
- Wrap both routes in a `DEBUG` guard so they only appear in development.
- If you need them in production for internal use, gate them behind `IsAdminUser`.

```python
# core/urls.py
if settings.DEBUG:
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    ]
```

---

### [x] CRITICAL-5: `avatar_upload_path` Raises `ValueError` → HTTP 500
**File:** `users/models.py:54-56`

Problem: Invalid file extension raises `ValueError`, which propagates as an unhandled exception and returns HTTP 500 instead of a validation error.

Fix: Replace `ValueError` with `django.core.exceptions.ValidationError`.

```python
from django.core.exceptions import ValidationError

def avatar_upload_path(instance, filename: str) -> str:
    ext = pathlib.Path(filename).suffix.lower().strip(".")
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        raise ValidationError(
            f"Invalid file type '.{ext}'. Allowed: {', '.join(ALLOWED_AVATAR_EXTENSIONS)}"
        )
    return f"avatars/user_{instance.user_id}/avatar.{ext}"
```

---

## HIGH — Fix Before Any PR Review

---

### [x] HIGH-1: `Comment.save()` Duplicates and Fights `Comment.clean()`
**File:** `community/models.py:249-254`

Problems:
- `save()` recalculates and overwrites `depth` that `clean()` already set correctly.
- `save()` raises `ValidationError` — wrong layer, will crash in Celery/migrations.
- The max depth constant `3` is hardcoded in two places.

Fix:
- Promote `MAX_COMMENT_DEPTH = 3` to a module-level constant.
- Move ALL depth logic into `clean()` only.
- Make `save()` a clean pass-through with no business logic.

```python
MAX_COMMENT_DEPTH = 3  # top of models.py

class Comment(models.Model):
    def clean(self):
        super().clean()
        if not self.body or not self.body.strip():
            raise ValidationError("Comment body cannot be empty.")
        if self.parent:
            if self.parent.post != self.post:
                raise ValidationError("Reply must belong to the same post as its parent.")
            if self.parent.is_deleted:
                raise ValidationError("Cannot reply to a deleted comment.")
            self.depth = self.parent.depth + 1
            if self.depth > MAX_COMMENT_DEPTH:
                raise ValidationError(f"Maximum reply depth is {MAX_COMMENT_DEPTH}.")
        else:
            self.depth = 0

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)  # depth is set by clean(), nothing else here
```

---

### [x] HIGH-2: Video Size Limit Is Inconsistent (50 MB vs 100 MB)
**Files:** `community/models.py:169`, `common/validators.py:47`, `core/settings.py:242`

Problem: `validate_media_size` enforces 50 MB for videos (from `settings.MAX_VIDEO_UPLOAD_SIZE`), but `PostMedia.clean()` uses a hardcoded 100 MB. The effective limit is 50 MB but the model says 100 MB in its error message — confusing and wrong.

Fix: Delete the hardcoded limits in `PostMedia.clean()` and reference `settings` as the single source of truth.

```python
# community/models.py — inside PostMedia.clean()
from django.conf import settings

if self.media_type == self.MediaType.IMAGE:
    limit_bytes = settings.MAX_IMAGE_UPLOAD_SIZE
else:
    limit_bytes = settings.MAX_VIDEO_UPLOAD_SIZE

if self.file.size > limit_bytes:
    limit_mb = limit_bytes / (1024 * 1024)
    raise ValidationError(
        {"file": f"Maximum file size is {limit_mb:.0f} MB. "
                 f"Your file is {self.file.size / (1024 * 1024):.1f} MB."}
    )
```

---

### [x] HIGH-3: Signal Fires `rebuild_profile_search_vector` on Every User Save
**File:** `users/models.py:125-136`

Problem: The `post_save` signal on `User` enqueues a Celery task on **every** save — including Django's internal `last_login` update on each login. The search vector only needs rebuilding when `username` changes.

Fix: Check `update_fields`. If `update_fields` is provided and doesn't include a search-relevant field, skip the task.

```python
SEARCH_RELEVANT_USER_FIELDS = frozenset({"username"})

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, update_fields, **kwargs):
    if created:
        transaction.on_commit(
            lambda: UserProfile.objects.get_or_create(user=instance)
        )
        return

    changed = set(update_fields or [])
    # update_fields=None means all fields saved — rebuild to be safe
    if not update_fields or changed & SEARCH_RELEVANT_USER_FIELDS:
        from users.tasks import rebuild_profile_search_vector
        transaction.on_commit(
            lambda: rebuild_profile_search_vector.delay(instance.pk)
        )
```

---

### [x] HIGH-4: `IS_IN_PRODUCTION` Defined Twice
**File:** `core/settings.py:240` and `core/settings.py:281`

Problem: Identical line appears twice — copy-paste artifact.

Fix: Delete line 240. Keep only the single definition at line 281 (directly above the `if IS_IN_PRODUCTION:` block where it's used).

---

## MEDIUM — Fix Before Calling It Production-Ready

---

### [x] MEDIUM-1: Authorization Logic Leaking Into `perform_create`
**File:** `community/views.py:143-163`

Problem: `CommentViewSet.perform_create()` contains 15 lines of visibility/follower permission checks. This is business logic in the view layer — hard to test in isolation, violates DRF's permission architecture.

Fix: Extract into a `CanCommentOnPost` permission class in `common/permissions.py`. The class should override `has_object_permission` and receive the post as the object. Apply it to the `create` action in `get_permissions()`.

---

### [x] MEDIUM-2: Celery Broker and Result Backend Share the Same Redis DB
**File:** `core/settings.py:249-250`

Problem: Both `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` point to the same Redis database (`/0`). Under load, task result keys pollute the broker's message space. Most of your tasks are fire-and-forget — results are never read.

Fix:
1. Use separate Redis databases: broker on `/0`, results on `/1`.
2. Add `task_ignore_result = True` to tasks that produce no meaningful return value (purge tasks, search vector rebuilds).

```python
CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("REDIS_RESULT_URL", "redis://localhost:6379/1")
CELERY_TASK_IGNORE_RESULT = True  # override per-task if you need the result
```

---

### [x] MEDIUM-3: No Hard Time Limit on Celery Tasks
**File:** `core/settings.py:255`

Problem: `CELERY_TASK_SOFT_TIME_LIMIT = 300` sends `SoftTimeLimitExceeded` but a task that catches all exceptions will run forever. No `CELERY_TASK_TIME_LIMIT` (hard kill) is set.

Fix: Add a hard limit ~30 seconds above the soft limit. The worker will SIGKILL the task process if the hard limit is breached regardless of exception handling.

```python
CELERY_TASK_SOFT_TIME_LIMIT = 300   # 5 min — raises SoftTimeLimitExceeded
CELERY_TASK_TIME_LIMIT = 330        # 5.5 min — hard SIGKILL
```

---

### [x] MEDIUM-4: No Celery Task Routing (CPU vs I/O Tasks Share Workers)
**File:** `core/settings.py` / `core/celery.py`

Problem: Image resizing (`process_post_media`) is CPU-bound. Search vector rebuilds and purge tasks are I/O-bound. They all run on the same worker pool, so a burst of image uploads can starve database tasks.

Fix: Define two queues and route tasks accordingly. Run separate workers per queue in production.

```python
# core/settings.py
CELERY_TASK_ROUTES = {
    'community.tasks.process_post_media': {'queue': 'media'},
    'users.tasks.resize_avatar':          {'queue': 'media'},
    'community.tasks.purge_*':            {'queue': 'maintenance'},
    'common.tasks.reconcile_counters':    {'queue': 'maintenance'},
    '*':                                   {'queue': 'default'},
}
```

---

### [x] MEDIUM-5: Session Backend Has No Database Fallback
**File:** `core/settings.py:139`

Problem: `SESSION_ENGINE = "django.contrib.sessions.backends.cache"` — if Redis goes down, every active session (Django admin, OAuth flow) is immediately lost. JWTs are stateless so the API itself survives, but the admin panel becomes completely unusable.

Fix: Use `cached_db` which reads from Redis first and falls back to the database on a miss.

```python
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
```

---

## Checklist Summary

```
CRITICAL
 [ ] CRITICAL-1  OAuth LOGIN_REDIRECT_URL → /admin/                          ← settings.py:84 still '/admin/'
 [x] CRITICAL-2  AWS_DEFAULT_ACL = 'public-read'
 [x] CRITICAL-3  Dead throttle scopes (reaction_spam, search, strict_auth)
 [x] CRITICAL-4  /api/docs/ and /api/schema/ unprotected in production
 [x] CRITICAL-5  avatar_upload_path raises ValueError → HTTP 500

HIGH
 [x] HIGH-1      Comment.save() duplicates and overrides Comment.clean()
 [x] HIGH-2      Video size limit 50 MB vs 100 MB inconsistency
 [x] HIGH-3      Signal fires rebuild_profile_search_vector on every User save
 [x] HIGH-4      IS_IN_PRODUCTION defined twice in settings.py

MEDIUM
 [x] MEDIUM-1    Authorization logic in perform_create (move to permission class)
 [x] MEDIUM-2    Celery broker and result backend on same Redis DB
 [x] MEDIUM-3    No hard Celery task time limit (CELERY_TASK_TIME_LIMIT)
 [x] MEDIUM-4    No task routing (CPU-bound and I/O-bound tasks share workers)
 [x] MEDIUM-5    Session backend has no database fallback
```
