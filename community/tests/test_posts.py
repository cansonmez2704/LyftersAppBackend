from rest_framework import status
from rest_framework.test import APITestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from community.models import Post,PostMedia,PostReaction,Comment,CommentReaction
from users.models import UserFollower , UserProfile

User = get_user_model()

class PostViewSetTest(APITestCase):

    def setUp(self):
        
        self.staff = User.objects.create_superuser(username="staff1",email="staff1@gmail.com",password="staff123")
        self.author = User.objects.create_user(username="author", email="author@test.com", password="password123")
        self.follower = User.objects.create_user(username="follower", email="follower@test.com", password="password123")
        self.stranger = User.objects.create_user(username="stranger", email="stranger@test.com", password="password123")

      
        UserProfile.objects.get_or_create(user=self.author)
        UserProfile.objects.get_or_create(user=self.follower)
        UserProfile.objects.get_or_create(user=self.stranger)

        UserFollower.objects.create(
            from_user=self.follower,
            to_user=self.author,
            status=UserFollower.FollowStatus.ACCEPTED
        )

        self.public_post = Post.objects.create(
            author=self.author,
            title="Public Post",
            description="Anyone can see this",
            visibility=Post.Visibility.PUBLIC
        )
        
        self.followers_post = Post.objects.create(
            author=self.author,
            title="Followers Post",
            description="Only followers can see this",
            visibility=Post.Visibility.FOLLOWERS
        )
        
        self.private_post = Post.objects.create(
            author=self.author,
            title="Private Post",
            description="Only the author can see this",
            visibility=Post.Visibility.PRIVATE
        )

        self.post_list_url = reverse("posts-list")
        self.public_post_url = reverse("posts-detail", kwargs={"uuid": self.public_post.uuid})
        self.private_post_url = reverse("posts-detail",kwargs={"uuid":self.private_post.uuid})
        self.followers_post_url = reverse("posts-detail",kwargs={"uuid":self.followers_post.uuid})


    def test_author_can_apply_full_crud(self):

        self.client.force_authenticate(user = self.author)
        
        create_payload = {
            "title": "A Brand New Post",
            "description": "Testing create",
            "visibility": Post.Visibility.PUBLIC
        }

        create_response = self.client.post(self.post_list_url,create_payload)
        self.assertEqual(create_response.status_code,status.HTTP_201_CREATED)

        read_response = self.client.get(self.private_post_url)
        self.assertEqual(read_response.status_code, status.HTTP_200_OK)

        update_payload = {
            "title": "A Brand New Post",
            "description": "Testing create",
            "visibility": Post.Visibility.PRIVATE
        }
        update_response = self.client.patch(self.private_post_url,update_payload)
        self.assertEqual(update_response.status_code,status.HTTP_200_OK)
        self.assertEqual(update_response.data["visibility"], Post.Visibility.PRIVATE)

        delete_response = self.client.delete(self.private_post_url)
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

        
        self.private_post.refresh_from_db()
        self.assertTrue(self.private_post.is_deleted)
   
    def test_staff_can_apply_full_crud_to_any_post(self):

        self.client.force_authenticate(user=self.staff)

        read_response = self.client.get(self.private_post_url)
        self.assertEqual(read_response.status_code, status.HTTP_200_OK)
        self.assertEqual(read_response.data["title"], "Private Post")

        update_payload = {
            "title": "Staff Edited This Title"
        }
        update_response = self.client.patch(self.private_post_url, update_payload)
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.data["title"], "Staff Edited This Title")

    
        delete_response = self.client.delete(self.private_post_url)
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.private_post.refresh_from_db()
        self.assertTrue(self.private_post.is_deleted)
    
    def test_follower_can_only_view_author_post(self):
        self.client.force_authenticate(user=self.follower)

        view_response = self.client.get(self.followers_post_url)
        self.assertEqual(view_response.status_code, status.HTTP_200_OK)

        update_payload = {"title": "Follower tried to change the title"}
        update_response = self.client.patch(self.followers_post_url, update_payload)
        self.assertEqual(update_response.status_code, status.HTTP_403_FORBIDDEN)

        delete_response = self.client.delete(self.followers_post_url)
        self.assertEqual(delete_response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_follower_cannot_view_private_post(self):
        self.client.force_authenticate(user=self.follower)     
        response = self.client.get(self.private_post_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_stranger_cannot_view_posts_unless_public(self):
        self.client.force_authenticate(user = self.stranger)
        response = self.client.get(self.public_post_url)
        self.assertEqual(response.status_code,status.HTTP_200_OK)

        response = self.client.get(self.followers_post_url)
        self.assertEqual(response.status_code,status.HTTP_404_NOT_FOUND)

        response = self.client.get(self.private_post_url)
        self.assertEqual(response.status_code,status.HTTP_404_NOT_FOUND)
    
    def test_stranger_cannot_update_destroy_posts(self):
 
        self.client.force_authenticate(user=self.stranger)

        update_payload = {"title": "Stranger maliciously trying to change title"}
        update_response = self.client.patch(self.public_post_url, update_payload)
        self.assertEqual(update_response.status_code, status.HTTP_403_FORBIDDEN)

        delete_response = self.client.delete(self.public_post_url)
        self.assertEqual(delete_response.status_code, status.HTTP_403_FORBIDDEN)

    
    def test_unauth_user_gets_401(self):
        response = self.client.get(self.public_post_url)
        self.assertEqual(response.status_code,status.HTTP_401_UNAUTHORIZED)


class PostReactionTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="reactor", email="reactor@test.com", password="password123")
        self.author = User.objects.create_user(username="author", email="author@test.com", password="password123")

        UserProfile.objects.get_or_create(user=self.user)
        UserProfile.objects.get_or_create(user=self.author)

        self.post = Post.objects.create(
            author=self.author,
            title="Reaction Target",
            description="A post to react to",
            visibility=Post.Visibility.PUBLIC
        )

        self.react_url = reverse("posts-react-to-posts", kwargs={"uuid": self.post.uuid})

    def test_like_post_first_time(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.react_url, {"reaction_type": "like"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "Reaction added")

        self.post.refresh_from_db()
        self.assertEqual(self.post.likes_count, 1)
        self.assertEqual(self.post.dislikes_count, 0)

    def test_like_toggle_off(self):
        self.client.force_authenticate(user=self.user)

        self.client.post(self.react_url, {"reaction_type": "like"})
        response = self.client.post(self.react_url, {"reaction_type": "like"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "Reaction removed")

        self.post.refresh_from_db()
        self.assertEqual(self.post.likes_count, 0)
        self.assertFalse(PostReaction.objects.filter(user=self.user, post=self.post).exists())

    def test_switch_like_to_dislike(self):
        self.client.force_authenticate(user=self.user)

        self.client.post(self.react_url, {"reaction_type": "like"})
        response = self.client.post(self.react_url, {"reaction_type": "dislike"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "Reaction changed")

        self.post.refresh_from_db()
        self.assertEqual(self.post.likes_count, 0)
        self.assertEqual(self.post.dislikes_count, 1)

        reaction = PostReaction.objects.get(user=self.user, post=self.post)
        self.assertEqual(reaction.reaction_type, "dislike")

    def test_missing_reaction_type(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.react_url, {})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_reaction_type(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.react_url, {"reaction_type": "love"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_two_users_like_same_post(self):
        second_user = User.objects.create_user(username="reactor2", email="reactor2@test.com", password="password123")
        UserProfile.objects.get_or_create(user=second_user)

        self.client.force_authenticate(user=self.user)
        self.client.post(self.react_url, {"reaction_type": "like"})

        self.client.force_authenticate(user=second_user)
        self.client.post(self.react_url, {"reaction_type": "like"})

        self.post.refresh_from_db()
        self.assertEqual(self.post.likes_count, 2)


class PostReactionListTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="reactor", email="reactor@test.com", password="password123")
        self.user2 = User.objects.create_user(username="reactor2", email="reactor2@test.com", password="password123")
        self.author = User.objects.create_user(username="author", email="author@test.com", password="password123")

        UserProfile.objects.get_or_create(user=self.user)
        UserProfile.objects.get_or_create(user=self.user2)
        UserProfile.objects.get_or_create(user=self.author)

        self.post = Post.objects.create(
            author=self.author,
            title="Reaction List Target",
            description="A post to list reactions on",
            visibility=Post.Visibility.PUBLIC
        )

        self.reactions_url = reverse("posts-reactions", kwargs={"uuid": self.post.uuid})

    def test_list_all_reactions(self):
        PostReaction.objects.create(user=self.user, post=self.post, reaction_type="like")
        PostReaction.objects.create(user=self.user2, post=self.post, reaction_type="dislike")

        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.reactions_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

    def test_filter_reactions_by_type(self):
        PostReaction.objects.create(user=self.user, post=self.post, reaction_type="like")
        PostReaction.objects.create(user=self.user2, post=self.post, reaction_type="dislike")

        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.reactions_url, {"type": "like"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["reaction_type"], "like")

    def test_empty_reactions_list(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.reactions_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_soft_deleted_post_reactions_not_accessible(self):
        self.post.is_deleted = True
        self.post.save()

        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.reactions_url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
