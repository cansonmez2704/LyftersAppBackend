"""
Celery tasks for the common app.
- Counter reconciliation: recomputes all denormalized counters from source-of-truth rows.
"""
import logging

from celery import shared_task
from django.db.models import Count, Q, Value
from django.db.models.functions import Coalesce

logger = logging.getLogger(__name__)


@shared_task
def reconcile_counters():
    """Recount all denormalized counters from actual rows.
    
    Fixes any drift caused by failed transactions, race conditions,
    or bugs in the F() expression counter updates.
    
    Runs every 6 hours via Celery Beat.
    """
    results = {}

    # ------------------------------------------------------------------
    # 1. UserProfile: followers_count, following_count
    # ------------------------------------------------------------------
    from users.models import UserProfile, UserFollower

    profiles = UserProfile.objects.all()
    profile_fixes = 0

    for profile in profiles.select_related("user"):
        actual_followers = UserFollower.objects.filter(
            to_user=profile.user,
            status=UserFollower.FollowStatus.ACCEPTED,
        ).count()

        actual_following = UserFollower.objects.filter(
            from_user=profile.user,
            status=UserFollower.FollowStatus.ACCEPTED,
        ).count()

        updates = {}
        if profile.followers_count != actual_followers:
            updates["followers_count"] = actual_followers
        if profile.following_count != actual_following:
            updates["following_count"] = actual_following

        if updates:
            UserProfile.objects.filter(pk=profile.pk).update(**updates)
            profile_fixes += 1

    results["profile_fixes"] = profile_fixes

    # ------------------------------------------------------------------
    # 2. Post: likes_count, dislikes_count, comments_count
    # ------------------------------------------------------------------
    from community.models import Post, PostReaction, Comment

    posts = Post.objects.filter(is_deleted=False)
    post_fixes = 0

    for post in posts:
        actual_likes = PostReaction.objects.filter(
            post=post, reaction_type="like"
        ).count()
        actual_dislikes = PostReaction.objects.filter(
            post=post, reaction_type="dislike"
        ).count()
        actual_comments = Comment.objects.filter(
            post=post, is_deleted=False
        ).count()

        updates = {}
        if post.likes_count != actual_likes:
            updates["likes_count"] = actual_likes
        if post.dislikes_count != actual_dislikes:
            updates["dislikes_count"] = actual_dislikes
        if post.comments_count != actual_comments:
            updates["comments_count"] = actual_comments

        if updates:
            Post.objects.filter(pk=post.pk).update(**updates)
            post_fixes += 1

    results["post_fixes"] = post_fixes

    # ------------------------------------------------------------------
    # 3. Comment: likes_count, dislikes_count
    # ------------------------------------------------------------------
    from community.models import CommentReaction

    comments = Comment.objects.filter(is_deleted=False)
    comment_fixes = 0

    for comment in comments:
        actual_likes = CommentReaction.objects.filter(
            comment=comment, reaction_type="like"
        ).count()
        actual_dislikes = CommentReaction.objects.filter(
            comment=comment, reaction_type="dislike"
        ).count()

        updates = {}
        if comment.likes_count != actual_likes:
            updates["likes_count"] = actual_likes
        if comment.dislikes_count != actual_dislikes:
            updates["dislikes_count"] = actual_dislikes

        if updates:
            Comment.objects.filter(pk=comment.pk).update(**updates)
            comment_fixes += 1

    results["comment_fixes"] = comment_fixes

    summary = (
        f"Reconciled counters — "
        f"profiles: {profile_fixes}, posts: {post_fixes}, comments: {comment_fixes}"
    )
    logger.info(summary)
    return summary
