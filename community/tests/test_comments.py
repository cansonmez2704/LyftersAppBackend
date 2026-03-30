from rest_framework import status
from rest_framework.test import APITestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from community.models import Post,PostMedia,PostReaction,Comment,CommentReaction
from users.models import UserFollower , UserProfile


User = get_user_model()

class CommentViewSetTest(APITestCase):

    def setUp(self):
        
        self.stranger = User.objects.create_user(username="stranger", email="stranger@gmail.com", password="stranger123")
        self.user = User.objects.create_user(username="cnmsz", email="cnmssz@gmail.com", password="cnmsz123")
        self.staff = User.objects.create_superuser(username="Can", email="cansonmez06@outlook.com.tr", password="123456")
        
        
        self.post_private = Post.objects.create(
            author=self.user,
            title="My Secret Workout",
            description="This is a private post description.",
            visibility=Post.Visibility.PRIVATE
        )

        self.post_public = Post.objects.create(
            author=self.user, 
            title="My Public Update",
            description="Everyone can see this post.",
            visibility=Post.Visibility.PUBLIC
        )

        
        self.comment_to_public = Comment.objects.create(
            post=self.post_public, 
            author=self.user,
            body="First comment on public post"
        )

    
        self.comment_to_private = Comment.objects.create(
            post=self.post_private,
            author=self.user,
            body="First comment on private post"
        )

       
        self.nested_comment = Comment.objects.create(
            post=self.post_public,
            author=self.staff,          
            parent=self.comment_to_public, 
            body="This is a reply to the first comment"
        )

        self.comments_list_url = reverse("comments-list")
        self.private_comment_url = reverse("comments-detail",kwargs={"pk":self.comment_to_private.pk})
        self.public_comment_url = reverse("comments-detail",kwargs={"pk":self.comment_to_public.pk})
    
    def test_staff_can_read_all_and_delete_but_not_edit(self):

        self.client.force_authenticate(user=self.staff)

        get_private_comments = self.client.get(self.private_comment_url)
        self.assertEqual(get_private_comments.status_code, status.HTTP_200_OK)

        patch_data = {"body": "changed the comment"}
        edit_private_comments = self.client.patch(self.private_comment_url, patch_data)
        self.assertEqual(edit_private_comments.status_code, status.HTTP_403_FORBIDDEN)

        delete_comment = self.client.delete(self.private_comment_url)
        self.assertEqual(delete_comment.status_code, status.HTTP_204_NO_CONTENT)
    
    def test_stranger_cannot_comment_on_private_post(self):
        self.client.force_authenticate(user=self.stranger)
        comment_data = {
            "post": self.post_private.id,  
            "body": "I am a stranger trying to sneak a comment in!"
        }
        comment_response = self.client.post(self.comments_list_url, comment_data)
        self.assertEqual(comment_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_follower_can_comment_but_stranger_cannot_on_followers_only_post(self):
        post_followers = Post.objects.create(
            author=self.user,
            title="Followers Only Post",
            description="Only my followers can see this.",
            visibility=Post.Visibility.FOLLOWERS,
        )

        # Stranger (not a follower) is blocked
        self.client.force_authenticate(user=self.stranger)
        response = self.client.post(
            self.comments_list_url,
            {"post": post_followers.id, "body": "I'm sneaking in!"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Create a user with an accepted follow relationship
        follower = User.objects.create_user(
            username="follower", email="follower@test.com", password="follower123"
        )
        UserFollower.objects.create(
            from_user=follower,
            to_user=self.user,
            status=UserFollower.FollowStatus.ACCEPTED,
        )

        # Follower is allowed
        self.client.force_authenticate(user=follower)
        response = self.client.post(
            self.comments_list_url,
            {"post": post_followers.id, "body": "Nice post!"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_empty_or_whitespace_body_is_rejected(self):
        self.client.force_authenticate(user=self.user)

        # Completely empty body
        response = self.client.post(
            self.comments_list_url,
            {"post": self.post_public.id, "body": ""},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Whitespace-only body
        response = self.client.post(
            self.comments_list_url,
            {"post": self.post_public.id, "body": "   "},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_comment_on_deleted_post(self):
        self.post_public.is_deleted = True
        self.post_public.save(update_fields=["is_deleted"])

        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.comments_list_url,
            {"post": self.post_public.id, "body": "This post is gone!"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CommentReactionTest(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="reactor", email="reactor@test.com", password="pass123")
        self.other = User.objects.create_user(username="other", email="other@test.com", password="pass123")

        self.post = Post.objects.create(
            author=self.user,
            title="Reaction Test Post",
            description="Post for reaction tests.",
            visibility=Post.Visibility.PUBLIC,
        )
        self.comment = Comment.objects.create(
            post=self.post,
            author=self.user,
            body="Comment to react to",
        )
        self.react_url = reverse("comments-react-to-comments", kwargs={"pk": self.comment.pk})

    def _fresh_comment(self):
        """Return the comment with up-to-date DB values."""
        return Comment.objects.get(pk=self.comment.pk)

    # ------------------------------------------------------------------ like
    def test_like_a_comment_returns_201_and_increments_count(self):
        self.client.force_authenticate(user=self.other)
        response = self.client.post(self.react_url, {"reaction_type": "like"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._fresh_comment().likes_count, 1)
        self.assertEqual(self._fresh_comment().dislikes_count, 0)

    # --------------------------------------------------------------- dislike
    def test_dislike_a_comment_returns_201_and_increments_count(self):
        self.client.force_authenticate(user=self.other)
        response = self.client.post(self.react_url, {"reaction_type": "dislike"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._fresh_comment().dislikes_count, 1)
        self.assertEqual(self._fresh_comment().likes_count, 0)

    # --------------------------------------------------------- toggle off
    def test_same_reaction_twice_removes_it(self):
        self.client.force_authenticate(user=self.other)
        self.client.post(self.react_url, {"reaction_type": "like"})   # add
        response = self.client.post(self.react_url, {"reaction_type": "like"})  # remove

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._fresh_comment().likes_count, 0)
        self.assertFalse(
            CommentReaction.objects.filter(user=self.other, comment=self.comment).exists()
        )

    # --------------------------------------------------------- switch
    def test_switching_from_like_to_dislike_updates_both_counts(self):
        self.client.force_authenticate(user=self.other)
        self.client.post(self.react_url, {"reaction_type": "like"})
        response = self.client.post(self.react_url, {"reaction_type": "dislike"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        comment = self._fresh_comment()
        self.assertEqual(comment.likes_count, 0)
        self.assertEqual(comment.dislikes_count, 1)
        self.assertEqual(
            CommentReaction.objects.get(user=self.other, comment=self.comment).reaction_type,
            "dislike",
        )

    def test_switching_from_dislike_to_like_updates_both_counts(self):
        self.client.force_authenticate(user=self.other)
        self.client.post(self.react_url, {"reaction_type": "dislike"})
        response = self.client.post(self.react_url, {"reaction_type": "like"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        comment = self._fresh_comment()
        self.assertEqual(comment.dislikes_count, 0)
        self.assertEqual(comment.likes_count, 1)

    # ------------------------------------------------- multiple users
    def test_multiple_users_reactions_are_independent(self):
        third = User.objects.create_user(username="third", email="third@test.com", password="pass123")

        self.client.force_authenticate(user=self.other)
        self.client.post(self.react_url, {"reaction_type": "like"})

        self.client.force_authenticate(user=third)
        self.client.post(self.react_url, {"reaction_type": "like"})

        self.assertEqual(self._fresh_comment().likes_count, 2)

    # ------------------------------------------------- validation
    def test_invalid_reaction_type_returns_400(self):
        self.client.force_authenticate(user=self.other)
        response = self.client.post(self.react_url, {"reaction_type": "love"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_reaction_type_returns_400(self):
        self.client.force_authenticate(user=self.other)
        response = self.client.post(self.react_url, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_user_cannot_react(self):
        response = self.client.post(self.react_url, {"reaction_type": "like"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class CommentsCountDenormalizationTest(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="counter", email="counter@test.com", password="pass123")
        self.post = Post.objects.create(
            author=self.user,
            title="Count Test Post",
            description="Post for count tests.",
            visibility=Post.Visibility.PUBLIC,
        )
        self.comments_list_url = reverse("comments-list")

    def _fresh_post(self):
        return Post.objects.get(pk=self.post.pk)

    def test_comments_count_increments_when_comment_is_created(self):
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self._fresh_post().comments_count, 0)

        self.client.post(self.comments_list_url, {"post": self.post.id, "body": "First!"})
        self.assertEqual(self._fresh_post().comments_count, 1)

        self.client.post(self.comments_list_url, {"post": self.post.id, "body": "Second!"})
        self.assertEqual(self._fresh_post().comments_count, 2)

    def test_comments_count_decrements_when_comment_is_deleted(self):
        self.client.force_authenticate(user=self.user)
        self.client.post(self.comments_list_url, {"post": self.post.id, "body": "To be deleted"})
        self.assertEqual(self._fresh_post().comments_count, 1)

        comment = Comment.objects.filter(post=self.post).first()
        delete_url = reverse("comments-detail", kwargs={"pk": comment.pk})
        self.client.delete(delete_url)

        self.assertEqual(self._fresh_post().comments_count, 0)

    def test_comments_count_never_goes_below_zero(self):
        """Deleting a comment whose count is already 0 must not produce a negative value."""
        # Manually create a comment bypassing the API (no increment)
        comment = Comment.objects.create(post=self.post, author=self.user, body="Raw insert")
        self.assertEqual(self._fresh_post().comments_count, 0)

        self.client.force_authenticate(user=self.user)
        delete_url = reverse("comments-detail", kwargs={"pk": comment.pk})
        self.client.delete(delete_url)

        self.assertEqual(self._fresh_post().comments_count, 0)

    def test_replies_also_increment_and_decrement_count(self):
        self.client.force_authenticate(user=self.user)
        # Top-level comment via API
        resp = self.client.post(self.comments_list_url, {"post": self.post.id, "body": "Parent"})
        parent_id = resp.data["id"]
        self.assertEqual(self._fresh_post().comments_count, 1)

        # Reply via API
        resp = self.client.post(
            self.comments_list_url,
            {"post": self.post.id, "parent": parent_id, "body": "Reply"},
        )
        reply_id = resp.data["id"]
        self.assertEqual(self._fresh_post().comments_count, 2)

        # Delete the reply
        self.client.delete(reverse("comments-detail", kwargs={"pk": reply_id}))
        self.assertEqual(self._fresh_post().comments_count, 1)