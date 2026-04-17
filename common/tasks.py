"""
Celery tasks for the common app.
- Counter reconciliation: recomputes all denormalized counters from source-of-truth rows.
"""
import logging

from celery import shared_task
from django.db.models import Case, Count, IntegerField, Sum, Value, When

logger = logging.getLogger(__name__)


def _bulk_sync_counter(model, field_name, computed_values):
    """Update `model.<field_name>` for every pk in `computed_values` where
    the stored value diverges. Returns the number of rows updated.

    `computed_values` is an iterable of (pk, actual_value) tuples.
    """
    computed = dict(computed_values)
    existing = dict(
        model.objects.filter(pk__in=computed.keys())
        .values_list("pk", field_name)
    )
    fixes = 0
    for pk, actual in computed.items():
        if existing.get(pk, 0) != actual:
            model.objects.filter(pk=pk).update(**{field_name: actual})
            fixes += 1
    return fixes


@shared_task
def reconcile_counters():
    """Recount all denormalized counters from actual rows.

    Fixes any drift caused by failed transactions, race conditions, or bugs in
    the F() expression counter updates. Runs every 6 hours via Celery Beat.

    Uses one GROUP BY query per counter instead of an N+1 loop so the runtime
    is bounded by counter groups, not total rows.
    """
    from users.models import UserProfile, UserFollower
    from community.models import Post, PostReaction, Comment, CommentReaction, ReactionType

    results = {}
    accepted = UserFollower.FollowStatus.ACCEPTED

    # -- UserProfile ----------------------------------------------------------
    followers_by_user = (
        UserFollower.objects.filter(status=accepted)
        .values("to_user_id")
        .annotate(c=Count("id"))
        .values_list("to_user_id", "c")
    )
    following_by_user = (
        UserFollower.objects.filter(status=accepted)
        .values("from_user_id")
        .annotate(c=Count("id"))
        .values_list("from_user_id", "c")
    )

    followers_map = dict(followers_by_user)
    following_map = dict(following_by_user)

    profile_ids = list(UserProfile.objects.values_list("pk", "user_id"))
    profile_fixes = _bulk_sync_counter(
        UserProfile,
        "followers_count",
        ((pk, followers_map.get(user_id, 0)) for pk, user_id in profile_ids),
    )
    profile_fixes += _bulk_sync_counter(
        UserProfile,
        "following_count",
        ((pk, following_map.get(user_id, 0)) for pk, user_id in profile_ids),
    )
    results["profile_fixes"] = profile_fixes

    # -- Post -----------------------------------------------------------------
    post_reaction_counts = (
        PostReaction.objects.values("post_id")
        .annotate(
            likes=Sum(Case(
                When(reaction_type=ReactionType.LIKE, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )),
            dislikes=Sum(Case(
                When(reaction_type=ReactionType.DISLIKE, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )),
        )
        .values_list("post_id", "likes", "dislikes")
    )
    likes_map = {pid: (likes or 0) for pid, likes, _ in post_reaction_counts}
    dislikes_map = {pid: (dislikes or 0) for pid, _, dislikes in post_reaction_counts}

    comments_map = dict(
        Comment.objects.filter(is_deleted=False)
        .values("post_id")
        .annotate(c=Count("id"))
        .values_list("post_id", "c")
    )

    active_post_ids = list(
        Post.objects.filter(is_deleted=False).values_list("pk", flat=True)
    )
    post_fixes = _bulk_sync_counter(
        Post,
        "likes_count",
        ((pk, likes_map.get(pk, 0)) for pk in active_post_ids),
    )
    post_fixes += _bulk_sync_counter(
        Post,
        "dislikes_count",
        ((pk, dislikes_map.get(pk, 0)) for pk in active_post_ids),
    )
    post_fixes += _bulk_sync_counter(
        Post,
        "comments_count",
        ((pk, comments_map.get(pk, 0)) for pk in active_post_ids),
    )
    results["post_fixes"] = post_fixes

    # -- Comment --------------------------------------------------------------
    comment_reaction_counts = (
        CommentReaction.objects.values("comment_id")
        .annotate(
            likes=Sum(Case(
                When(reaction_type=ReactionType.LIKE, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )),
            dislikes=Sum(Case(
                When(reaction_type=ReactionType.DISLIKE, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )),
        )
        .values_list("comment_id", "likes", "dislikes")
    )
    c_likes_map = {cid: (likes or 0) for cid, likes, _ in comment_reaction_counts}
    c_dislikes_map = {cid: (dislikes or 0) for cid, _, dislikes in comment_reaction_counts}

    active_comment_ids = list(
        Comment.objects.filter(is_deleted=False).values_list("pk", flat=True)
    )
    comment_fixes = _bulk_sync_counter(
        Comment,
        "likes_count",
        ((pk, c_likes_map.get(pk, 0)) for pk in active_comment_ids),
    )
    comment_fixes += _bulk_sync_counter(
        Comment,
        "dislikes_count",
        ((pk, c_dislikes_map.get(pk, 0)) for pk in active_comment_ids),
    )
    results["comment_fixes"] = comment_fixes

    summary = (
        f"Reconciled counters — "
        f"profiles: {profile_fixes}, posts: {post_fixes}, comments: {comment_fixes}"
    )
    logger.info(summary)
    return summary
