# GymHub Backend — Deep Audit Report
> Date: 2026-04-16 (original) · **Re-audited: 2026-04-17** · **Follow-up patch pass: 2026-04-17 (same day)**
> Scope: API surface, security (OWASP), performance (N+1), stability, database health

This report complements `AUDIT_FIXES.md` (the previous pass). The **2026-04-17 revision** re-walks every finding against the working tree and tags each one with its current state.

Every finding is classified by severity:
- `CRITICAL` — Must fix immediately. Security, data loss, or outage risk.
- `HIGH` — Fix before next production deploy.
- `MEDIUM` — Should fix soon; harms quality, performance, or DX.
- `LOW` — Nice-to-have / polish.

…and by status (added 2026-04-17):
- `[FIXED]` — addressed and verified in code.
- `[PARTIAL]` — partially addressed; remaining work or bug introduced.
- `[OPEN]` — no code change yet.
- `[REGRESSION]` — the fix introduced a new defect.

---



## 2. API Surface & Functional Gaps

### `API-1` `[OPEN]` HIGH — Inconsistent URL Conventions
**Files:** `users/urls.py`, `community/urls.py`, `workouts/urls.py`

Mixed casing and separators:

| Endpoint | Style |
|---|---|
| `/sign-up/` | kebab-case |
| `/log-out/` | kebab-case |
| `/my-profile/` | kebab-case |
| `/token/refresh/` | slash-separated |
| `/posts/` | single-word |
| `/workouts/workouts/` | double path segment (`/workouts/` include + `/workouts/` router) |
| `/api/auth/` | not under `/api/v1/` (skips versioning) |
| `/accounts/` | allauth, outside both `/api/` and `/api/v1/` |

Pick **one** convention (recommend lowercase, hyphen-separated REST nouns) and normalize everything.

**Notable:** `/api/v1/workouts/workouts/` is a URL smell — the outer prefix already scopes the app; the router shouldn't re-register a nested `workouts` path. Either drop the router prefix or restructure the include.

---

### `API-2` `[OPEN]` HIGH — Auth Endpoints Not Versioned
**File:** `core/urls.py:26-32`

```python
path('api/auth/',  include('dj_rest_auth.urls')),
path('accounts/',  include('allauth.urls')),
path("api/v1/",    include("common.urls")),
...
```

Auth is unversioned. When you bump the mobile client to v2 and change the token contract, you cannot deprecate `/api/auth/` independently.

**Fix:** move under `/api/v1/auth/` and gate allauth HTML routes behind DEBUG (or an admin-only subdomain).

---

### `API-3` `[OPEN]` MEDIUM — HTTP 205 on Logout Is Non-Idiomatic
**File:** `users/views.py:57-60`

```python
return Response({"message": "Successfully logged out."},
                status=status.HTTP_205_RESET_CONTENT)
```

`205 Reset Content` is defined for form resets in the browser. Most API clients treat non-`2xx` statuses uniformly but some libraries interpret 205 as "re-submit empty form", which is wrong here. Use `204 No Content` (preferred for logout) or `200 OK`.

---

### `API-4` `[PARTIAL]` HIGH — Missing RESTful Nested Routes for Comments & Reactions

**Status (2026-04-17):** Comments moved to the nested pattern `POST/GET /posts/<uuid>/comments/` and flat POST-to-comments removed from the router. Reactions are still RPC-style via `/posts/{uuid}/react/`; comment `replies` route still missing.

Currently:
- Comments: `GET /comments/?post=<uuid>` ← query-param filter
- Post reactions: `POST /posts/{uuid}/react/` ← RPC-style action

Conventional REST:
- `GET  /posts/{uuid}/comments/` — list
- `POST /posts/{uuid}/comments/` — create
- `GET  /comments/{uuid}/replies/` — list replies
- `POST /posts/{uuid}/reactions/` + body `{"type":"like"}`, `DELETE /posts/{uuid}/reactions/me/` — reaction lifecycle

The `/react/` endpoint combines create, update, and delete into a single toggle. That makes clients guess the result: did I like, unlike, or switch? Recommend splitting by HTTP verb and letting 2xx disambiguate.

---

### `API-5` `[OPEN]` MEDIUM — Missing / Broken CRUD Endpoints

| Missing / Incomplete | Reason |
|---|---|
| `DELETE /api/v1/users/my-account/` | GDPR "right to be forgotten" — no way to delete an account |
| `GET  /api/v1/users/follow-requests/` | No way to list *incoming pending* requests; user is supposed to accept/reject them but there's no list endpoint |
| `GET  /api/v1/users/blocked/` | No block feature at all (community app with zero moderation) |
| `PATCH /my-profile/` `is_public` | `FullUserProfileSerializer` does not include `is_public`, so users cannot toggle their privacy via the API |
| `POST /api/v1/workouts/workouts/{uuid}/duplicate/` | Workouts are templates but there is no copy/clone action |
| `GET  /api/v1/workouts/muscle-groups/` | `MuscleGroup` is a core model, yet has no endpoint |
| Password reset flow | `dj_rest_auth` provides it but no explicit URL is registered |
| Email verification | Google OAuth is wired; local-email-signup verification path is unclear |

---

### `API-6` `[OPEN]` MEDIUM — No Bulk Operations

Every client request creates one object at a time. Common pain points:
- Uploading a post with 10 images → 10 individual `POST` validations (the nested `PostWriteSerializer.create` does bulk-create internally, but many clients work around this by uploading per file).
- Reordering media (`PostMedia.order`) requires one `PATCH` per media object.
- Deleting multiple comments at moderation time — no batch endpoint.
- Marking multiple notifications read — no notifications app exists, but anticipate.

Suggested bulk additions:
- `POST /posts/{uuid}/media/bulk/` — upload N media at once (already possible via nested serializer, document it).
- `PATCH /posts/{uuid}/media/reorder/` — body `[{"id":1,"order":0}, …]`.
- `POST /comments/bulk-delete/` — admin-only.

---

### `API-7` `[FIXED]` LOW — `GET /api/v1/community/feed/` and `GET /api/v1/community/posts/` Overlap

Both return a list of posts with visibility filtering. The distinction (`feed/` filters to "posts by people I follow") isn't documented anywhere. Consider merging into `GET /posts/?filter=following|public|mine`.

---

## 3. Security & OWASP Findings

### `SEC-1` `[OPEN]` HIGH — `PostReaction` / `CommentReaction` List Leaks Full Reactor Profiles
**File:** `community/views.py:99-113`, `community/serializers.py:14-18`

`GET /posts/{uuid}/reactions/` returns every reacting user's username, UUID, and avatar. That is arguably public information on a social app, **but** the response is not paginated-by-default (uses `self.paginate_queryset(reaction_qs)` only if `paginate_queryset` returns non-None — depends on `pagination_class`). Combined with a viral post (10k likes), this is an unbounded JSON payload and a PII scraping vector.

Also, this endpoint doesn't respect the reactor's profile privacy — a reactor with `is_public=False` still has their profile emitted.

---

### `SEC-2` `[OPEN]` HIGH — `PostDetailSerializer.get_comments` Is Unpaginated
**File:** `community/serializers.py:100-101`

```python
def get_comments(self, obj):
    return CommentSerializer(obj.comments.all(), many=True, context=self.context).data
```

Fetching a single post returns **all** of its comments. A post with 5k comments returns 5k serialized objects in one payload. This is both a DoS vector (slow / OOM) and a bandwidth cost.

**Recommendation:** return the first N (e.g. 20) plus a `comments_url` link. Full list fetched via `GET /posts/{uuid}/comments/`.

---

### `SEC-3` `[OPEN]` MEDIUM — `CommentViewSet` Queryset Produces Duplicate Rows
**File:** `community/views.py:136-144`

The joined `Q(post__visibility=FOLLOWERS, post__author__incoming_followers__from_user=...)` clause joins `Comment → Post → User → UserFollower`. Without `.distinct()`, a user who follows the author of a post returns every comment **once per row matched on the join**. In practice, because the inner join is on `from_user=<self>`, duplication is limited, but any change to the follower graph (multiple rows per (from_user, to_user)? currently unique constraint prevents) could silently multiply rows.

Same issue in `PostViewSet.get_queryset()` and `FollowerListView.get_queryset()`.

**Before:**
```python
queryset = queryset.filter(
    Q(post__visibility=Post.Visibility.PUBLIC) | Q(post__author=self.request.user)
    | Q(post__visibility=Post.Visibility.FOLLOWERS,
        post__author__incoming_followers__from_user=self.request.user,
        post__author__incoming_followers__status=ACCEPTED)
)
```

**After (subquery-based, no joins in Q, safer and faster on Postgres):**
```python
followed_author_ids = UserFollower.objects.filter(
    from_user=self.request.user,
    status=UserFollower.FollowStatus.ACCEPTED,
).values_list("to_user_id", flat=True)

queryset = queryset.filter(
    Q(post__visibility=Post.Visibility.PUBLIC)
    | Q(post__author=self.request.user)
    | Q(post__visibility=Post.Visibility.FOLLOWERS,
        post__author_id__in=followed_author_ids)
)
```

---

### `SEC-4` `[OPEN]` MEDIUM — `print()` in `core/celery.py`
**File:** `core/celery.py:16`

```python
print(f'Request: {self.request!r}')
```

This is the default `debug_task` from `celery init`; on production it writes task metadata to stdout every time it runs. Low-value leak, but should be removed (or replaced with `logger.debug`).

---

### `SEC-5` `[OPEN]` MEDIUM — `ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(",")` Produces `[""]` on Missing Env
**File:** `core/settings.py:25`

If `ALLOWED_HOSTS` is unset, `.split(",")` on empty string returns `[""]`. Django will reject every request with a 400 *DisallowedHost* — that's actually a fail-safe, but the error is confusing. Worse: a typo such as `ALLOWED_HOSTS=localhost,,example.com` silently creates an empty-string host entry that is ignored.

```python
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]
```

---

### `SEC-6` `[OPEN]` MEDIUM — `SECRET_KEY` Allowed to Be Empty
**File:** `core/settings.py:22`

`SECRET_KEY = os.getenv("SECRET_KEY")` — if the env var is missing, Django starts with `SECRET_KEY = None`, which leads to cryptic errors on first use of signing. Worse, if `SECRET_KEY=""` it will silently accept an empty key.

```python
SECRET_KEY = os.environ["SECRET_KEY"]  # KeyError at import time if missing
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY must be a non-empty string.")
```

---

### `SEC-7` `[FIXED]` LOW — DRF Token Auth Still Installed
**File:** `core/settings.py:54`

```python
"rest_framework.authtoken",   # <-- ADD THIS (Needed for dj-rest-auth)
```

Project uses JWT (`rest_framework_simplejwt`) but `authtoken` is enabled. `dj_rest_auth` can be configured with JWT-only mode, making authtoken unnecessary. Two auth mechanisms in parallel = double attack surface.

---

### `SEC-8` `[FIXED]` LOW — `validate_real_content_type` Only Reads First 2 KiB
**File:** `common/validators.py:22-25`

Reads the first 2048 bytes to detect MIME via libmagic. This is usually enough for images, but polyglot files (a file that is valid as both a JPEG and an HTML page, for example) can evade detection. For a fitness-social app the residual risk is small, but consider:
- Re-encoding all uploaded images server-side (already done partially in `process_post_media`).
- Blocking uploads that *also* match a script/executable signature.

---

### `SEC-9` `[FIXED]` INFO — Self-DoS via Unlimited Post `description`
**File:** `community/models.py:55`

```python
description = models.TextField(help_text="Main body / caption of the post.")
```

Postgres TEXT is unbounded. A client can push a 500 MB description. Django's `DATA_UPLOAD_MAX_MEMORY_SIZE` defaults to 2.5 MB, which provides a practical ceiling — but the default value is not pinned in your `settings.py`. Consider adding `max_length=5000` (or whatever your product requires) both in the model and serializer.

---

## 4. Performance Anti-Patterns (N+1, Caching)

### `PERF-1` `[OPEN]` CRITICAL — `reconcile_counters` Is Quadratic
**File:** `common/tasks.py:30-115`

Runs every 6 hours. For every profile, for every post, for every comment:

```python
for profile in profiles.select_related("user"):
    actual_followers = UserFollower.objects.filter(to_user=profile.user, status=ACCEPTED).count()
    actual_following = UserFollower.objects.filter(from_user=profile.user, status=ACCEPTED).count()
    ...
```

If you have **10 000 profiles**, that's `10 000 × 2 = 20 000` follower queries. Same for posts (3 queries each) and comments (2 queries each). On a platform with 100k posts this is **300 000 database round-trips** every 6 hours — the task will likely blow through `CELERY_TASK_TIME_LIMIT = 330` seconds.

**Before:**
```python
for profile in profiles.select_related("user"):
    actual_followers = UserFollower.objects.filter(to_user=profile.user, status="A").count()
    actual_following = UserFollower.objects.filter(from_user=profile.user, status="A").count()
```

**After — one query per counter:**
```python
from django.db.models import Count, Q

followers = dict(
    UserFollower.objects
    .filter(status="A")
    .values("to_user")
    .annotate(c=Count("id"))
    .values_list("to_user", "c")
)
following = dict(
    UserFollower.objects
    .filter(status="A")
    .values("from_user")
    .annotate(c=Count("id"))
    .values_list("from_user", "c")
)

for profile in UserProfile.objects.all():
    actual_followers = followers.get(profile.user_id, 0)
    actual_following = following.get(profile.user_id, 0)
    ...
```

Or better: do it in SQL with a single `UPDATE ... FROM (SELECT ...) sub`.

---

### `PERF-2` `[OPEN]` HIGH — `bulk_blacklist_tokens` Uses N+1 `get_or_create`
**File:** `users/tasks.py:86-91`

```python
for token in tokens:
    _, created = BlacklistedToken.objects.get_or_create(token=token)
```

One `SELECT` + one `INSERT` per outstanding token. A user with 50 refresh tokens (common for mobile + web + multi-device) generates 100 queries.

**After:**
```python
existing_ids = set(BlacklistedToken.objects.filter(token__in=tokens).values_list("token_id", flat=True))
to_create = [BlacklistedToken(token=t) for t in tokens if t.pk not in existing_ids]
BlacklistedToken.objects.bulk_create(to_create, ignore_conflicts=True)
```

---

### `PERF-3` `[OPEN]` HIGH — `UserProfile post_save` Signal Re-Enqueues Vector Rebuild on Every Counter Bump
**File:** `users/models.py:142-148`

```python
@receiver(post_save, sender=UserProfile)
def update_profile_search_vector(sender, instance, **kwargs):
    from users.tasks import rebuild_profile_search_vector
    transaction.on_commit(
        lambda: rebuild_profile_search_vector.delay(instance.user_id)
    )
```

Every `followers_count` / `following_count` / `avatar_url` update fires this task. The search vector depends on `username` and `bio`, neither of which changes on a follow action. This is the exact bug that `HIGH-3` fixed for the `User` model — the same pattern needs repeating here.

**After:**
```python
SEARCH_RELEVANT_PROFILE_FIELDS = frozenset({"bio"})

@receiver(post_save, sender=UserProfile)
def update_profile_search_vector(sender, instance, created, update_fields, **kwargs):
    changed = set(update_fields or [])
    if not update_fields or changed & SEARCH_RELEVANT_PROFILE_FIELDS:
        from users.tasks import rebuild_profile_search_vector
        transaction.on_commit(
            lambda: rebuild_profile_search_vector.delay(instance.user_id)
        )
```

Additionally, `resize_avatar` calls `profile.avatar.save(...)` which will re-fire this signal. Consider passing `update_fields=["avatar"]` in the task to short-circuit it.

---

### `PERF-4` `[OPEN]` HIGH — N+1 in `PostWriteSerializer.create` Full-Clean
**File:** `community/serializers.py:124-141`

```python
for obj in media_objs:
    obj.full_clean()
```

Each `full_clean()` reads `obj.file.size` — for S3 storage, that's an HTTP `HEAD` request per file. Uploading 10 images = 10 sequential S3 HEADs.

`file.size` should already be populated on the incoming `UploadedFile` in memory. Call `validate_media_size(obj.file)` directly without going through `full_clean` — or skip server-side size validation (it's duplicated in the field `validators=[validate_media_size]`).

---

### `PERF-5` `[OPEN]` HIGH — Comments Eager-Loaded for Post Retrieve
**File:** `community/views.py:61-71`

```python
if self.action == 'retrieve':
    return base_queryset.prefetch_related(
        Prefetch("comments",
                 queryset=Comment.objects.filter(is_deleted=False)
                              .select_related("author__profile")
                              .prefetch_related("reactions__user__profile")),
        "media",
        "reactions__user__profile",
    )
```

This prefetches **every** comment, **every** comment reaction, **every** reactor's profile on a single post retrieve. One post with 5k comments × 20 avg reactions = 100 000 objects pulled on every page view. Coupled with `SEC-2`, this is the main scaling cliff.

**Fix:** remove `comments` from the Prefetch entirely. Let the client call `GET /posts/{uuid}/comments/` separately with pagination. Same for reactions.

---

### `PERF-6` `[OPEN]` MEDIUM — No Caching Anywhere
**File:** project-wide

Redis is configured as the Django cache backend but no view or queryset uses it. Candidates:

| Target | Reason | Key / TTL |
|---|---|---|
| `ExerciseViewSet.list` | Exercises change rarely; pure reference data | `cache_page(60*60)` or custom invalidation on save |
| `MuscleGroup` endpoints (once added) | Static | 1h+ |
| `GlobalSearchView` | Search is expensive (FTS + trigram) | `(term, type)` key, 5 min TTL |
| `FeedView` | Per-user feed | `feed:{user_id}:{cursor}` 1 min TTL, invalidated on new follow / new post |
| `UserProfileView` followers_count / posts_count | Denormalized counters rarely need DB hit | `profile:{uuid}` 30 s TTL |

---

### `PERF-7` `[OPEN]` MEDIUM — `GlobalSearchView` Runs 3 Queries Sequentially
**File:** `common/search.py:85-145`

Each search does FTS + trigram per type. For `search_type="all"` that's 3 independent queries; they could run concurrently via `asyncio.gather` under async views, or you can pre-union the search vectors into a single table.

Also, `.exclude(search_vector=None)` forces a seq scan unless you add a partial index:

```python
GinIndex(fields=["search_vector"], name="exercise_search_gin",
         condition=Q(search_vector__isnull=False))
```

---

### `PERF-8` `[OPEN]` MEDIUM — `FullUserProfileSerializer` Fires 2 Extra Sub-Queries in `get_follow`
**File:** `users/serializers.py:76-90`

Every profile retrieve runs:
```python
UserFollower.objects.filter(from_user=request.user, to_user=obj.user).first()
```

That's an extra query per profile retrieval. When listing profiles (search results, follower list), this becomes N+1. Prefetch the relationship into the queryset or use `Exists()` annotation.

---

### `PERF-9` `[OPEN]` MEDIUM — `WorkoutViewSet` Prefetches Sets Even for List
**File:** `workouts/views.py:28-29`

```python
queryset = Workout.objects.select_related("owner__profile").prefetch_related(
    "workout_exercises__exercise__muscles",
    "workout_exercises__sets",
)
```

The list view returns every `WorkoutExercise` + every `Exercise` + every `MuscleGroup` + every `WorkoutSet` per workout. For a user with 50 workouts averaging 6 exercises × 4 sets × 2 muscles, that's **~2 400 related rows** on a list page. Split into `WorkoutListSerializer` (minimal) vs `WorkoutDetailSerializer` (full), and only prefetch on retrieve.

---

### `PERF-10` `[FIXED]` LOW — `DISABLE_SERVER_SIDE_CURSORS = True`
**File:** `core/settings.py:173`

This is typically set when using pgBouncer in transaction pooling mode. Confirm your deploy actually needs it — if you run `gunicorn` against Postgres directly, it disables server-side cursors unnecessarily, hurting large-result-set performance (the exact case `FeedCursorPagination` uses).

---

## 5. Stability & Resilience

### `STAB-1` `[OPEN]` HIGH — `process_post_media` Is Never Triggered
**File:** `community/serializers.py:118-141`, `community/tasks.py:20-60`

The task exists, is routed to the `media` queue, and retries. But **nothing ever calls `process_post_media.delay(media.pk)`** after a `PostMedia` is created. Uploaded images are never resized; they stay at the full original dimensions forever.

**Fix:** after `PostMedia.objects.bulk_create(media_objs)` in `PostWriteSerializer.create`, iterate the created IDs and enqueue:

```python
for media in media_objs:
    if media.media_type == PostMedia.MediaType.IMAGE:
        transaction.on_commit(
            lambda mid=media.pk: process_post_media.delay(mid)
        )
```

---

### `STAB-2` `[OPEN]` HIGH — `avatar_upload_path` Raises `ValidationError` Inside Storage Path Calculation
**File:** `users/models.py:53-59`

Django calls `upload_to` *during model `save()`*, not during serializer validation. If the extension is invalid, a `ValidationError` is raised at save time, which DRF will convert — but only if the serializer translates it. The previous fix (`CRITICAL-5` in `AUDIT_FIXES.md`) addresses the symptom; however, the *correct* layer for that check is a serializer-level validator on the avatar field:

```python
# in serializers.py
def validate_avatar(self, value):
    if value:
        ext = pathlib.Path(value.name).suffix.lower().strip(".")
        if ext not in ALLOWED_AVATAR_EXTENSIONS:
            raise serializers.ValidationError(f"Invalid extension '{ext}'")
        ...
```

The model-level check becomes a defense-in-depth fallback.

---

### `STAB-3` `[OPEN]` HIGH — Race Condition in `CommentViewSet.perform_destroy`
**File:** `community/views.py:152-165`

```python
def perform_destroy(self, instance):
    if instance.is_deleted:
        return
    with transaction.atomic():
        Comment.objects.filter(parent=instance).update(parent=None, depth=0)
        instance.is_deleted = True
        instance.save(update_fields=['is_deleted'])
        Post.objects.filter(uuid=instance.post.uuid).update(
            comments_count=Greatest(F("comments_count") - 1, Value(0))
        )
```

Two simultaneous DELETEs both pass the `is_deleted` check (read before the transaction), both decrement `comments_count`. Counter drifts negative (caught by `Greatest` at 0, but still wrong by one).

**Fix:** make the soft-delete atomic and conditional:

```python
updated = Comment.objects.filter(pk=instance.pk, is_deleted=False).update(is_deleted=True)
if not updated:
    return   # someone else deleted it first
Post.objects.filter(uuid=instance.post.uuid).update(
    comments_count=Greatest(F("comments_count") - 1, Value(0))
)
```

Same pattern applies to `PostViewSet.perform_destroy`.

---

### `STAB-4` `[OPEN]` HIGH — `toggle_reaction` Has a Lock-Ordering Inversion
**File:** `common/reactions.py:26-58`

Sequence:
1. `existing = reaction_model.objects.filter(...).first()` — no lock
2. If not existing: `create()` (takes row lock on new row)
3. Then `select_for_update().update(...)` on the parent — takes parent lock

This grabs the reaction lock first, then the parent lock. Elsewhere (e.g. `perform_destroy`, `reconcile_counters`) locks may be acquired in the opposite order. Classic deadlock recipe.

**Fix:** always lock the *parent* first (it's the coarser resource), then read/write reactions. Additionally, the initial `.first()` should be inside `.select_for_update(of=("self",))` on the reaction row to prevent two concurrent "add reaction" calls from both taking the "does not exist → create" branch (the unique constraint does save you via IntegrityError, which the code handles — so this is a latency concern, not correctness).

---

### `STAB-5` `[OPEN]` MEDIUM — No Global Exception Handler
**File:** `core/settings.py` — `REST_FRAMEWORK` dict has no `EXCEPTION_HANDLER`

When a view raises `KeyError`, `IntegrityError`, or any non-DRF exception, DRF returns `500 Internal Server Error` with Django's stack trace (when `DEBUG=True`) or a generic 500 page (when `DEBUG=False`). There is no consistent error envelope:

```json
// Expected, consistent across the API:
{"error": {"code": "post_not_found", "message": "…"}}

// What you currently return:
{"detail": "Not found."}              // DRF's default
{"error": "…"}                        // handwritten in some views
{"status": "Unfollowed"}              // mixed "status" field
{"message": "Successfully logged out."}
```

**Fix:** implement a custom `exception_handler` and standardize the error envelope. Bonus: strip traceback data and report to Sentry / equivalent.

---

### `STAB-6` `[OPEN]` MEDIUM — `ChangePasswordView` Does Not Invalidate Current Session Synchronously
**File:** `users/views.py:68-93`

```python
user.set_password(...)
user.save()
bulk_blacklist_tokens.delay(user.id)   # async — window of vulnerability
```

Between `user.save()` and the Celery task actually running, **all outstanding tokens remain valid**. If a password is changed because the account was compromised, the attacker can keep using the access token for up to 30 minutes (the access token lifetime).

**Fix:** run the blacklisting synchronously (it's typically fast — one UPDATE), *then* return. Keep Celery only for cleanup of expired blacklist rows.

---

### `STAB-7` `[OPEN]` MEDIUM — No Circuit Breaker / Graceful Degradation for Redis
**File:** project-wide

`CACHES`, `SESSION_ENGINE`, and `CELERY_BROKER_URL` all depend on a single Redis. If Redis is unreachable:
- Cache reads raise `ConnectionError` (current code does not `try` anything).
- `transaction.on_commit(lambda: task.delay(...))` will raise when the broker is down, causing the transaction to still succeed but the `on_commit` handler to blow up after commit → inconsistency.
- Session lookups on the Django admin fail.

**Recommendation:** wrap cache usage with a helper that logs + returns None on failure. Use Celery's `task.apply_async(..., retry=True)` with a fallback to a sync path for critical operations.

---

### `STAB-8` `[FIXED]` LOW — No Request Size Ceiling in Settings
**File:** `core/settings.py`

`DATA_UPLOAD_MAX_MEMORY_SIZE` (default 2.5 MB) and `FILE_UPLOAD_MAX_MEMORY_SIZE` (default 2.5 MB) are not pinned. A client can upload a 50 MB JSON body and all of it is buffered. Set explicit ceilings slightly below your nginx/ALB limit.

---

## 6. Database & Schema Health

### `DB-1` `[OPEN]` HIGH — Missing Index on `PostReaction(user_id)` and `CommentReaction(user_id)`
**File:** `community/models.py:261-300`

```python
constraints = [
    models.UniqueConstraint(fields=["user", "post"], name="unique_post_reaction_per_user"),
]
indexes = [
    models.Index(fields=["post", "reaction_type"]),
]
```

The unique constraint creates an index on `(user, post)` with leading column `user` — OK for that direction.

But: when computing `PostDetailSerializer.get_user_reaction`, you iterate `obj.reactions.all()` client-side, which is fine with prefetch. However, "all reactions by a given user" (e.g. "did I react to this post?" at scale, or "show me all my liked posts") is a common query with no covering index unless you rely on the unique constraint.

More importantly, `CommentReaction` has **no** leading-`user` index — the unique constraint is `(user, comment)` and `indexes=[(comment, reaction_type)]`. Same recommendation: ensure `user` is a leading column somewhere.

---

### `DB-2` `[OPEN]` MEDIUM — No Partial Index on `is_deleted=False` for Feed Queries
**Files:** `community/models.py` (Post, Comment)

Every feed / list query filters on `is_deleted=False`. Most rows satisfy that (deletion is rare). A partial index keeps the index tiny and faster:

```python
indexes = [
    models.Index(
        fields=["visibility", "-created_at"],
        name="post_active_feed_idx",
        condition=Q(is_deleted=False, is_archived=False),
    ),
]
```

---

### `DB-3` `[OPEN]` MEDIUM — `Comment.depth` Reset to 0 Loses Information
**File:** `community/views.py:158`

```python
Comment.objects.filter(parent=instance).update(parent=None, depth=0)
```

When a mid-thread comment is soft-deleted, its direct children have `parent` set to `None` and `depth` to `0`. But any grandchildren still have `depth=2` and `parent=<now-orphan>`. The tree becomes inconsistent — grandchildren claim depth 2 while their new "root" says depth 0.

**Fix:** recompute depth for the entire subtree, or keep `parent` intact and rely on `is_deleted=True` to gray out the deleted node in the UI (Reddit-style).

---

### `DB-4` `[OPEN]` MEDIUM — `Post.slug` Collision Risk
**File:** `community/models.py:111-116`

```python
if self.title and not self.slug:
    base_slug = slugify(self.title)
    self.slug = f"{base_slug}-{str(self.uuid)[:8]}" if base_slug else str(self.uuid)[:8]
```

`str(uuid)[:8]` uses the first 8 hex chars of the UUID (~4 billion possibilities). The collision probability is low but nonzero, and `slug` has `unique=True` at the DB layer — on collision, `IntegrityError` bubbles up as a 500. Solution: retry with a longer suffix (`uuid[:12]`) or use the full UUID minus the timestamp.

---

### `DB-5` `[FIXED]` LOW — `Post.cover_image` Has No Size / Content-Type Validator
**File:** `community/models.py:56-61`

`cover_image` is declared with `ImageField(upload_to=post_cover_upload_path)` and **no validators** — unlike `PostMedia.file`. A user can upload a 500 MB cover image in production.

**Fix:** reuse `validate_media_size` and `validate_real_content_type`.

---

### `DB-6` `[FIXED]` LOW — `Post.description` & `UserProfile.bio` Are Unbounded
**Files:** `community/models.py:55`, `users/models.py:81`

`bio` is `CharField(max_length=2000)` — fine. `description` is `TextField` — unbounded. Set a reasonable cap in-model; the serializer also currently has none.

---

### `DB-7` `[FIXED]` LOW — `WorkoutSet` Allows Nonsensical Combinations
**File:** `workouts/models.py:185-232`

All three (`reps`, `weight`, `duration_seconds`) are nullable. A row with all three null passes DB validation. Add a `CheckConstraint`:

```python
constraints = [
    models.UniqueConstraint(...),
    models.CheckConstraint(
        check=Q(reps__isnull=False) | Q(duration_seconds__isnull=False),
        name="set_must_have_reps_or_duration",
    ),
]
```

---

### `DB-8` `[FIXED]` LOW — `UserProfile.is_public` Not Indexed
**File:** `users/models.py:78`

Public-feed queries filter by `is_public=True`. Cardinality is low (2 values) so a regular B-tree helps little — but a **partial** index on `(user_id) WHERE is_public=True` supports the "give me all public profiles" search query cheaply.

---

### `DB-9` `[OPEN]` INFO — Missing `on_delete` Policy Review for User Deletion
**Files:** all models with `settings.AUTH_USER_MODEL` FK

Everything is `on_delete=CASCADE`. When a user deletes their account, their posts, comments, reactions, and follows all vanish. That's fine for GDPR ("right to be forgotten") but destroys conversational context for other users ("who were you replying to?"). Consider `SET_NULL` with an "anonymized user" sentinel for posts and comments — keep the thread readable, lose only the identity.

---

## 7. Architectural Recommendations

### `ARC-1` Migrate Denormalized Counters to a Single Source of Truth

The app maintains `likes_count`, `dislikes_count`, `comments_count`, `followers_count`, `following_count` all by hand, with a 6-hour `reconcile_counters` job to clean up drift. This is fragile. Two alternatives:

1. **Postgres triggers** — create AFTER INSERT / AFTER DELETE triggers on `PostReaction`, `CommentReaction`, `UserFollower`. The DB guarantees consistency; no Python-side race conditions.
2. **Remove denormalized counters entirely** — compute on read with `annotate(Count(...))`. With proper indexes, Postgres handles 10k-row counts in microseconds.

Either way, remove the hand-written `.update(F("…") + 1)` sprinkled across 5 files.

---

### `ARC-2` Split "Write" and "Read" Models

You already split serializers (`PostListSerializer`, `PostDetailSerializer`, `PostWriteSerializer`). Take the same pattern further:
- `WorkoutListSerializer` (minimal) vs `WorkoutDetailSerializer` (full).
- `ProfilePublicSerializer` vs `ProfileOwnerSerializer` (see `CRITICAL-A1`).

---

### `ARC-3` Introduce a Per-Endpoint Permission Registry

Currently permissions are scattered across `get_permissions()` methods and permission classes. Consider a single `permissions.py` per app that explicitly maps `action → [permission_classes]`, so a reviewer can see the full access matrix in one file.

---

### `ARC-4` `[PARTIAL]` Add `requirements.in` / Pinned Dependencies

`requirements.txt` shows as modified — confirm it is pinned to exact versions (`==`), otherwise a Celery or DRF minor bump can break CI silently.

**Status (2026-04-17):** New packages (`dj-rest-auth`, `django-allauth`, `django-celery-beat`, `django-storages`, `boto3`, `cryptography`, `requests`) were added, but they still use `>=` floors rather than `==` pins. Risk unchanged — recommend running `pip-compile` against a `requirements.in`.

---

### `ARC-5` Adopt `drf-spectacular` Tags and Descriptions

`drf-spectacular` is already installed. Add `@extend_schema(tags=["Posts"], summary="…")` decorators so `/api/docs/` renders a useful grouped API reference.

---

### `ARC-6` Observability

No `logging` configuration in `settings.py`, no structured log format, no Sentry (or equivalent) DSN visible. For a production deploy, add:
- JSON-formatted logs via `LOGGING` dict.
- Sentry for exception aggregation (pairs well with `STAB-5` custom exception handler).
- Prometheus metrics (Celery queue depth, DB query count, cache hit ratio).

---

### `ARC-7` Add a Notifications App

Follow-requests, reactions, comments, and mentions all need user-facing notifications. The current design forces clients to poll. Plan a `notifications` app with Channels / Server-Sent-Events now before it becomes tangled with every other module.

---

## 8. Summary Checklist — updated 2026-04-17

Legend: `[x]` fixed · `[~]` partially fixed / needs follow-up · `[!]` regression introduced · `[ ]` open

```
REGRESSIONS (all resolved in the follow-up pass)
 [x] REGRESSION-1 confirm_password equality check restored in UserRegisterSerializer.validate()
 [x] REGRESSION-2 lookup_url_kwargs aligned; Comment.uuid/Exercise.uuid made unique+non-null via backfill migrations
 [x] REGRESSION-3 CommentViewSet.perform_create resolves Post from URL kwarg; serializer injects it via context

CRITICAL (all closed)
 [x] CRITICAL-A1  PII exposure on public profile — OwnProfileSerializer split, FullUserProfileSerializer trimmed
 [x] CRITICAL-A2  validate_password + confirm_password equality check both in place
 [x] CRITICAL-A3  JWT lifetimes 15m/7d, rotation + blacklist + algorithm pinned
 [x] CRITICAL-A4  Comment + Exercise UUIDs unique+indexed; Workout already had one; all viewsets use uuid lookup
 [x] CRITICAL-A5  Nested route + perform_create reads post_uuid from URL; serializer validates via context

HIGH
 [ ] API-1        Inconsistent URL conventions (kebab vs word vs double prefix)
 [ ] API-2        Auth endpoints not under /api/v1/
 [~] API-4        Comments nested under posts (good); reactions still RPC-style; replies route missing
 [ ] SEC-1        /posts/{uuid}/reactions/ leaks unpaginated reactor profiles
 [ ] SEC-2        PostDetail returns ALL comments unpaginated
 [ ] SEC-3        Post/Comment querysets missing .distinct() on M2M joins
 [ ] PERF-1       reconcile_counters is quadratic
 [ ] PERF-2       bulk_blacklist_tokens is N+1
 [ ] PERF-3       UserProfile post_save signal rebuilds search vector on counter updates
 [ ] PERF-4       PostWriteSerializer.create hits S3 once per media via full_clean
 [ ] PERF-5       Post retrieve prefetches every comment + reaction + avatar
 [ ] STAB-1       process_post_media task is never dispatched (thumbnails never generated)
 [ ] STAB-2       avatar_upload_path validation lives in storage path, not serializer
 [ ] STAB-3       CommentViewSet.perform_destroy has TOCTOU race on is_deleted flag
 [ ] STAB-4       toggle_reaction acquires locks in inverse order → deadlock risk
 [ ] DB-1         Missing single-column index on (user) for CommentReaction

MEDIUM
 [ ] API-3        Logout returns HTTP 205 (should be 204 or 200)
 [ ] API-5        Missing CRUD: account delete, follow-requests list, is_public toggle, blocks
 [ ] API-6        No bulk endpoints (media reorder, bulk delete, etc.)
 [ ] SEC-4        print() in core/celery.py debug_task
 [ ] SEC-5        ALLOWED_HOSTS='' produces ['']
 [ ] SEC-6        SECRET_KEY allowed to be empty/missing
 [ ] PERF-6       No caching layer (Redis unused by views)
 [ ] PERF-7       GlobalSearchView runs 3 sequential queries; exclude(search_vector=None) no partial idx
 [ ] PERF-8       FullUserProfileSerializer.get_follow is N+1 on profile lists
 [ ] PERF-9       WorkoutViewSet prefetches full set/exercise/muscle tree for list view
 [ ] STAB-5       No global DRF EXCEPTION_HANDLER → inconsistent error envelopes
 [ ] STAB-6       ChangePasswordView blacklists tokens async — 30 min window of exposure
 [ ] STAB-7       No circuit breaker / graceful degradation when Redis is down
 [ ] DB-2         No partial index on is_deleted=False for hot feed queries
 [ ] DB-3         Comment.depth reset-to-0 on parent delete corrupts descendant depth
 [ ] DB-4         Post.slug collision on uuid[:8] returns 500

LOW (all closed except DB-9 which is INFO-level and requires architectural choice)
 [x] API-7        /feed/ vs /posts/ distinction documented via docstrings
 [x] SEC-7        rest_framework.authtoken removed; REST_AUTH configured for JWT-only
 [x] SEC-8        content-type sniff now reads first 8 KiB instead of 2 KiB
 [x] SEC-9        Post.description capped at 5000 chars (model + serializer)
 [x] PERF-10      DISABLE_SERVER_SIDE_CURSORS gated behind USE_PGBOUNCER env flag
 [x] STAB-8       DATA_UPLOAD_MAX_MEMORY_SIZE, FILE_UPLOAD_MAX_MEMORY_SIZE, DATA_UPLOAD_MAX_NUMBER_FIELDS pinned
 [x] DB-5         Post.cover_image gets FileExtensionValidator + size + content-type validators
 [x] DB-6         Post.description bounded via MaxLengthValidator(5000)
 [x] DB-7         WorkoutSet CheckConstraint: reps OR duration_seconds must be non-null
 [x] DB-8         Partial index on UserProfile(user) WHERE is_public=True
 [ ] DB-9         User deletion = CASCADE → destroys thread context (INFO, deferred: needs sentinel user)
 [~] ARC-4        New deps added but still `>=` pinned instead of `==`
```

### Tally
- **2 CRITICALs fully closed** (A1, A3)
- **3 CRITICALs in flight** with blocking regressions (A2, A4, A5)
- **1 HIGH partially landed** (API-4)
- **0 MEDIUM / LOW touched**
- Triage priority → fix the three regressions first; they all live in files you've already edited, so the blast radius is small.

---

### Reading order suggestion (revised 2026-04-17)

1. **First:** close the three regressions (`REGRESSION-1/2/3`). Each is a small, local patch in a file you have already edited.
2. Re-run the schema plan for `CRITICAL-A4`: make `Comment.uuid` `unique=True, db_index=True, null=False` via a two-step migration (add nullable → backfill → enforce), and align `lookup_url_kwarg` with the URL patterns.
3. Bundle `DB-1`, `DB-2`, and the tightened `Comment.uuid` into one migration batch.
4. Patch performance hotspots (`PERF-1`, `PERF-2`, `PERF-3`, `PERF-5`) — biggest operational payoff for the smallest code change.
5. Everything else can be rolled in alongside normal feature work.

> 2026-04-17 revision: status tags added throughout. No new findings were introduced beyond the three regressions called out above.
