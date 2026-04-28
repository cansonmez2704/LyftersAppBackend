"""Comprehensive tests for the content moderation system.

Covers:
  - moderate_content Celery task (allow, block, empty-text, target-missing,
    fail-open, fail-closed, debounce)
  - Visibility filters (author sees own pending/rejected; stranger does not)
  - Post text-edit re-moderation
  - Comment body-edit re-moderation
  - Rejection / pending notifications via moderation_message
  - escalate_manual_review periodic task
"""

import time
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from common.moderation import ModerationDecision, ModerationResult, ModerationStatus
from common.groq_client import ModerationResponse
from community.models import Comment, Post
from community.tasks import moderate_content, dispatch_moderation
from users.models import UserProfile

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_moderation_response(*, flagged=False, categories=None, scores=None):
    """Shortcut to build a ModerationResponse without touching the real API."""
    return ModerationResponse(
        flagged=flagged,
        categories=categories or {},
        category_scores=scores or {},
        model="text-moderation-test",
        raw={},
    )


# ===========================================================================
# Task unit tests
# ===========================================================================


class ModerationTaskTest(TestCase):
    """Unit tests for the ``moderate_content`` Celery task."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="taskuser", email="task@test.com", password="pass123"
        )
        self.post = Post.objects.create(
            author=self.user,
            title="Test Post",
            description="Some description to moderate",
            visibility=Post.Visibility.PUBLIC,
        )
        self.ct_id = ContentType.objects.get_for_model(Post).id

    # ---------------------------------------------------------------- allow
    @patch("common.groq_client.moderate_text")
    def test_allowed_content_published(self, mock_mod):
        mock_mod.return_value = _make_moderation_response(flagged=False)

        result = moderate_content.apply(args=[self.ct_id, self.post.pk]).result

        self.post.refresh_from_db()
        self.assertEqual(result, ModerationDecision.ALLOW)
        self.assertEqual(self.post.moderation_status, ModerationStatus.PUBLISHED)
        self.assertIsNotNone(self.post.moderated_at)

        # Audit row recorded
        self.assertTrue(
            ModerationResult.objects.filter(
                object_id=self.post.pk, decision=ModerationDecision.ALLOW
            ).exists()
        )

    # ---------------------------------------------------------------- block
    @patch("common.groq_client.moderate_text")
    def test_flagged_content_rejected(self, mock_mod):
        mock_mod.return_value = _make_moderation_response(
            flagged=True,
            categories={"hate": True},
            scores={"hate": 0.97},
        )

        result = moderate_content.apply(args=[self.ct_id, self.post.pk]).result

        self.post.refresh_from_db()
        self.assertEqual(result, ModerationDecision.BLOCK)
        self.assertEqual(self.post.moderation_status, ModerationStatus.REJECTED)

        audit = ModerationResult.objects.get(object_id=self.post.pk)
        self.assertTrue(audit.flagged)
        self.assertEqual(audit.categories, {"hate": True})
        self.assertIn("hate", audit.category_scores)

    # --------------------------------------------------------- empty text
    @patch("common.groq_client.moderate_text")
    def test_empty_text_auto_allows(self, mock_mod):
        self.post.title = ""
        self.post.description = ""
        self.post.save(update_fields=["title", "description"])

        result = moderate_content.apply(args=[self.ct_id, self.post.pk]).result

        self.post.refresh_from_db()
        self.assertEqual(result, "empty_text")
        self.assertEqual(self.post.moderation_status, ModerationStatus.PUBLISHED)
        mock_mod.assert_not_called()

    # ------------------------------------------------------ target missing
    def test_missing_target_returns_target_missing(self):
        fake_id = 999999
        result = moderate_content.apply(args=[self.ct_id, fake_id]).result
        self.assertEqual(result, "target_missing")

    # ------------------------------------------------- retry exhaustion: fail-open
    @patch("common.groq_client.moderate_text")
    @override_settings(MODERATION_FAIL_OPEN=True)
    def test_fail_open_publishes_with_manual_review(self, mock_mod):
        mock_mod.side_effect = TimeoutError("API down")

        # Simulate being on the last retry (retries == max_retries)
        moderate_content.push_request(retries=3)
        try:
            result = moderate_content.run(self.ct_id, self.post.pk)
        finally:
            moderate_content.pop_request()

        self.assertEqual(result, "fail_open")
        self.post.refresh_from_db()
        self.assertEqual(self.post.moderation_status, ModerationStatus.PUBLISHED)
        self.assertTrue(self.post.requires_manual_review)

        # Audit row recorded with MANUAL_REVIEW decision
        self.assertTrue(
            ModerationResult.objects.filter(
                object_id=self.post.pk, decision=ModerationDecision.MANUAL_REVIEW
            ).exists()
        )

    # ------------------------------------------------- retry exhaustion: fail-closed
    @patch("common.groq_client.moderate_text")
    @override_settings(MODERATION_FAIL_OPEN=False)
    def test_fail_closed_sets_error_status(self, mock_mod):
        mock_mod.side_effect = TimeoutError("API down")

        moderate_content.push_request(retries=3)
        try:
            result = moderate_content.run(self.ct_id, self.post.pk)
        finally:
            moderate_content.pop_request()

        self.assertEqual(result, "fail_open")  # return value name is same
        self.post.refresh_from_db()
        self.assertEqual(self.post.moderation_status, ModerationStatus.ERROR)
        self.assertFalse(self.post.requires_manual_review)

    # ------------------------------------------------------- debounce
    @patch("common.groq_client.moderate_text")
    def test_debounced_task_skips_when_superseded(self, mock_mod):
        """When a newer dispatch_ts exists in cache, older tasks skip."""
        from django.core.cache import cache

        future_ts = time.time() + 1000
        cache.set(f"mod_dispatch:{self.ct_id}:{self.post.pk}", str(future_ts), timeout=60)

        result = moderate_content.apply(
            args=[self.ct_id, self.post.pk],
            kwargs={"dispatch_ts": 1.0},  # very old timestamp
        ).result

        self.assertEqual(result, "debounced")
        mock_mod.assert_not_called()

    @patch("common.groq_client.moderate_text")
    def test_task_runs_normally_without_dispatch_ts(self, mock_mod):
        """Backward compat: tasks dispatched without dispatch_ts run normally."""
        mock_mod.return_value = _make_moderation_response(flagged=False)

        result = moderate_content.apply(args=[self.ct_id, self.post.pk]).result

        self.assertEqual(result, ModerationDecision.ALLOW)
        mock_mod.assert_called_once()

    # --------------------------------------------------- comment moderation
    @patch("common.groq_client.moderate_text")
    def test_comment_moderation_allowed(self, mock_mod):
        mock_mod.return_value = _make_moderation_response(flagged=False)
        comment = Comment.objects.create(
            post=self.post, author=self.user, body="Nice workout!"
        )
        ct_id = ContentType.objects.get_for_model(Comment).id

        result = moderate_content.apply(args=[ct_id, comment.pk]).result

        comment.refresh_from_db()
        self.assertEqual(result, ModerationDecision.ALLOW)
        self.assertEqual(comment.moderation_status, ModerationStatus.PUBLISHED)

    @patch("common.groq_client.moderate_text")
    def test_comment_moderation_rejected(self, mock_mod):
        mock_mod.return_value = _make_moderation_response(flagged=True)
        comment = Comment.objects.create(
            post=self.post, author=self.user, body="Offensive content"
        )
        ct_id = ContentType.objects.get_for_model(Comment).id

        result = moderate_content.apply(args=[ct_id, comment.pk]).result

        comment.refresh_from_db()
        self.assertEqual(result, ModerationDecision.BLOCK)
        self.assertEqual(comment.moderation_status, ModerationStatus.REJECTED)


# ===========================================================================
# Visibility filter tests
# ===========================================================================


class ModerationVisibilityTest(APITestCase):
    """The author sees their own content in any moderation state;
    everyone else only sees PUBLISHED rows (Twitter/Instagram pattern)."""

    def setUp(self):
        self.author = User.objects.create_user(
            username="author", email="author@test.com", password="pass123"
        )
        self.stranger = User.objects.create_user(
            username="stranger", email="stranger@test.com", password="pass123"
        )
        UserProfile.objects.get_or_create(user=self.author)
        UserProfile.objects.get_or_create(user=self.stranger)

        self.pending_post = Post.objects.create(
            author=self.author,
            title="Pending Post",
            description="Waiting for moderation",
            visibility=Post.Visibility.PUBLIC,
            # moderation_status defaults to PENDING from the model
        )
        self.published_post = Post.objects.create(
            author=self.author,
            title="Published Post",
            description="Already approved",
            visibility=Post.Visibility.PUBLIC,
            moderation_status=ModerationStatus.PUBLISHED,
        )
        self.rejected_post = Post.objects.create(
            author=self.author,
            title="Rejected Post",
            description="Violated policy",
            visibility=Post.Visibility.PUBLIC,
            moderation_status=ModerationStatus.REJECTED,
        )

    # ------------------------------------------------- Post detail
    def test_author_sees_own_pending_post(self):
        self.client.force_authenticate(user=self.author)
        url = reverse("posts-detail", kwargs={"uuid": self.pending_post.uuid})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_stranger_cannot_see_pending_post(self):
        self.client.force_authenticate(user=self.stranger)
        url = reverse("posts-detail", kwargs={"uuid": self.pending_post.uuid})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_stranger_sees_published_post(self):
        self.client.force_authenticate(user=self.stranger)
        url = reverse("posts-detail", kwargs={"uuid": self.published_post.uuid})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_author_sees_own_rejected_post(self):
        self.client.force_authenticate(user=self.author)
        url = reverse("posts-detail", kwargs={"uuid": self.rejected_post.uuid})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_stranger_cannot_see_rejected_post(self):
        self.client.force_authenticate(user=self.stranger)
        url = reverse("posts-detail", kwargs={"uuid": self.rejected_post.uuid})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ------------------------------------------------- Feed
    def test_feed_excludes_pending_and_rejected_for_stranger(self):
        self.client.force_authenticate(user=self.stranger)
        response = self.client.get(reverse("feed"))
        uuids = [str(p["uuid"]) for p in response.data["results"]]

        self.assertIn(str(self.published_post.uuid), uuids)
        self.assertNotIn(str(self.pending_post.uuid), uuids)
        self.assertNotIn(str(self.rejected_post.uuid), uuids)

    def test_feed_includes_own_pending_for_author(self):
        self.client.force_authenticate(user=self.author)
        response = self.client.get(reverse("feed"))
        uuids = [str(p["uuid"]) for p in response.data["results"]]

        self.assertIn(str(self.pending_post.uuid), uuids)
        self.assertIn(str(self.rejected_post.uuid), uuids)

    # ------------------------------------------------- Comment visibility
    def test_stranger_cannot_see_pending_comment(self):
        """Pending comments are hidden from everyone except their author."""
        Post.objects.filter(pk=self.published_post.pk).update(
            moderation_status=ModerationStatus.PUBLISHED,
        )
        comment = Comment.objects.create(
            post=self.published_post,
            author=self.author,
            body="Pending comment",
            # defaults to PENDING
        )

        self.client.force_authenticate(user=self.stranger)
        url = reverse("comment-detail", kwargs={"comment_uuid": comment.uuid})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_author_sees_own_pending_comment(self):
        Post.objects.filter(pk=self.published_post.pk).update(
            moderation_status=ModerationStatus.PUBLISHED,
        )
        comment = Comment.objects.create(
            post=self.published_post,
            author=self.author,
            body="My pending comment",
        )

        self.client.force_authenticate(user=self.author)
        url = reverse("comment-detail", kwargs={"comment_uuid": comment.uuid})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ===========================================================================
# Re-moderation on edit
# ===========================================================================


class PostEditReModerationTest(APITestCase):
    """When post text is edited, moderation_status resets to PENDING and
    a new moderation task is dispatched."""

    def setUp(self):
        self.author = User.objects.create_user(
            username="editor", email="editor@test.com", password="pass123"
        )
        UserProfile.objects.get_or_create(user=self.author)
        self.post = Post.objects.create(
            author=self.author,
            title="Original Title",
            description="Original description",
            visibility=Post.Visibility.PUBLIC,
            moderation_status=ModerationStatus.PUBLISHED,
        )

    @patch("community.tasks.moderate_content.apply_async")
    def test_text_edit_resets_to_pending(self, mock_dispatch):
        self.client.force_authenticate(user=self.author)
        url = reverse("posts-detail", kwargs={"uuid": self.post.uuid})
        response = self.client.patch(url, {"description": "Edited description"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.post.refresh_from_db()
        self.assertEqual(self.post.moderation_status, ModerationStatus.PENDING)
        self.assertIsNone(self.post.moderated_at)

    @patch("community.tasks.moderate_content.apply_async")
    def test_non_text_edit_keeps_published(self, mock_dispatch):
        """Changing visibility (non-text field) should not trigger re-moderation."""
        self.client.force_authenticate(user=self.author)
        url = reverse("posts-detail", kwargs={"uuid": self.post.uuid})
        response = self.client.patch(url, {"visibility": "private"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.post.refresh_from_db()
        self.assertEqual(self.post.moderation_status, ModerationStatus.PUBLISHED)
        mock_dispatch.assert_not_called()


class CommentEditReModerationTest(APITestCase):
    """When a comment body is edited, moderation_status resets to PENDING
    and a new moderation task is dispatched."""

    def setUp(self):
        self.author = User.objects.create_user(
            username="commentor", email="commentor@test.com", password="pass123"
        )
        UserProfile.objects.get_or_create(user=self.author)
        self.post = Post.objects.create(
            author=self.author,
            title="Test Post",
            description="Test",
            visibility=Post.Visibility.PUBLIC,
            moderation_status=ModerationStatus.PUBLISHED,
        )
        self.comment = Comment.objects.create(
            post=self.post,
            author=self.author,
            body="Original comment body",
            moderation_status=ModerationStatus.PUBLISHED,
        )

    @patch("community.tasks.moderate_content.apply_async")
    def test_body_edit_resets_to_pending(self, mock_dispatch):
        self.client.force_authenticate(user=self.author)
        url = reverse("comment-detail", kwargs={"comment_uuid": self.comment.uuid})
        response = self.client.patch(url, {"body": "Edited comment body"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.moderation_status, ModerationStatus.PENDING)
        self.assertIsNone(self.comment.moderated_at)

    @patch("community.tasks.moderate_content.apply_async")
    def test_same_body_does_not_re_moderate(self, mock_dispatch):
        """Patching with the same body shouldn't trigger re-moderation."""
        self.client.force_authenticate(user=self.author)
        url = reverse("comment-detail", kwargs={"comment_uuid": self.comment.uuid})
        response = self.client.patch(url, {"body": "Original comment body"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.moderation_status, ModerationStatus.PUBLISHED)
        mock_dispatch.assert_not_called()


# ===========================================================================
# Rejection / pending notification message
# ===========================================================================


class ModerationMessageTest(APITestCase):
    """The ``moderation_message`` field shows context to the content author."""

    def setUp(self):
        self.author = User.objects.create_user(
            username="msguser", email="msg@test.com", password="pass123"
        )
        self.stranger = User.objects.create_user(
            username="msgstranger", email="msgs@test.com", password="pass123"
        )
        UserProfile.objects.get_or_create(user=self.author)
        UserProfile.objects.get_or_create(user=self.stranger)

    # ------------------------------------------------- Posts
    def test_author_sees_rejection_message_on_post(self):
        post = Post.objects.create(
            author=self.author,
            title="Bad Post",
            description="Violated policy",
            visibility=Post.Visibility.PUBLIC,
            moderation_status=ModerationStatus.REJECTED,
        )
        self.client.force_authenticate(user=self.author)
        url = reverse("posts-detail", kwargs={"uuid": post.uuid})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data.get("moderation_message"))
        self.assertIn("community guidelines", response.data["moderation_message"])

    def test_author_sees_pending_message_on_post(self):
        post = Post.objects.create(
            author=self.author,
            title="New Post",
            description="Under review",
            visibility=Post.Visibility.PUBLIC,
            # defaults to PENDING
        )
        self.client.force_authenticate(user=self.author)
        url = reverse("posts-detail", kwargs={"uuid": post.uuid})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data.get("moderation_message"))
        self.assertIn("being reviewed", response.data["moderation_message"])

    def test_published_post_has_no_message(self):
        post = Post.objects.create(
            author=self.author,
            title="Good Post",
            description="Clean content",
            visibility=Post.Visibility.PUBLIC,
            moderation_status=ModerationStatus.PUBLISHED,
        )
        self.client.force_authenticate(user=self.author)
        url = reverse("posts-detail", kwargs={"uuid": post.uuid})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data.get("moderation_message"))

    # ------------------------------------------------- Comments
    def test_author_sees_rejection_message_on_comment(self):
        post = Post.objects.create(
            author=self.author,
            title="P",
            description="P",
            visibility=Post.Visibility.PUBLIC,
            moderation_status=ModerationStatus.PUBLISHED,
        )
        comment = Comment.objects.create(
            post=post,
            author=self.author,
            body="Bad comment",
            moderation_status=ModerationStatus.REJECTED,
        )
        self.client.force_authenticate(user=self.author)
        url = reverse("comment-detail", kwargs={"comment_uuid": comment.uuid})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data.get("moderation_message"))
        self.assertIn("community guidelines", response.data["moderation_message"])

    def test_stranger_does_not_see_moderation_message(self):
        """moderation_message is only visible to the content author."""
        post = Post.objects.create(
            author=self.author,
            title="test",
            description="test",
            visibility=Post.Visibility.PUBLIC,
            moderation_status=ModerationStatus.PUBLISHED,
        )
        self.client.force_authenticate(user=self.stranger)
        url = reverse("posts-detail", kwargs={"uuid": post.uuid})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data.get("moderation_message"))


# ===========================================================================
# Dispatch helper debounce
# ===========================================================================


class DispatchModerationTest(TestCase):
    """Tests for the ``dispatch_moderation`` debounce helper."""

    @patch("community.tasks.moderate_content.apply_async")
    def test_dispatch_sets_cache_key_and_calls_apply_async(self, mock_apply):
        from django.core.cache import cache

        ct_id = 99
        obj_id = 42
        dispatch_moderation(ct_id, obj_id)

        # Cache key was set
        cached = cache.get(f"mod_dispatch:{ct_id}:{obj_id}")
        self.assertIsNotNone(cached)

        # apply_async was called with countdown
        mock_apply.assert_called_once()
        call_kwargs = mock_apply.call_args
        self.assertEqual(call_kwargs.kwargs.get("countdown") or call_kwargs[1].get("countdown"), 3)


# ===========================================================================
# Escalation task
# ===========================================================================


class EscalateManualReviewTest(TestCase):
    """Tests for the ``escalate_manual_review`` periodic task."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="escuser", email="esc@test.com", password="pass123"
        )

    def test_no_stuck_items_returns_zero(self):
        from common.tasks import escalate_manual_review

        result = escalate_manual_review.apply().result
        self.assertIn("0 posts", result)
        self.assertIn("0 comments", result)

    def test_stuck_items_counted(self):
        from common.tasks import escalate_manual_review

        post = Post.objects.create(
            author=self.user,
            title="Stuck",
            description="Stuck post",
            visibility=Post.Visibility.PUBLIC,
            moderation_status=ModerationStatus.PUBLISHED,
            requires_manual_review=True,
        )
        # Backdate moderated_at to >24h ago
        Post.objects.filter(pk=post.pk).update(
            moderated_at=timezone.now() - timedelta(hours=25)
        )

        result = escalate_manual_review.apply().result
        self.assertIn("1 posts", result)

    def test_recent_items_not_escalated(self):
        from common.tasks import escalate_manual_review

        post = Post.objects.create(
            author=self.user,
            title="Recent",
            description="Recent post",
            visibility=Post.Visibility.PUBLIC,
            moderation_status=ModerationStatus.PUBLISHED,
            requires_manual_review=True,
        )
        # moderated_at within 24h — should NOT be counted
        Post.objects.filter(pk=post.pk).update(
            moderated_at=timezone.now() - timedelta(hours=1)
        )

        result = escalate_manual_review.apply().result
        self.assertIn("0 posts", result)
