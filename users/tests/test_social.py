import uuid
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from users.models import UserFollower,UserProfile

User = get_user_model()
class FollowUserViewTest(APITestCase):

    def setUp(self):
        
        self.from_user = User.objects.create_user(username="Arnold", email="arnold@gmail.com", password="password123")
        self.to_user = User.objects.create_user(username="Phil", email="phil@gmail.com", password="password123")
        
        self.profile_follower, _ = UserProfile.objects.get_or_create(user=self.from_user)
        self.profile_following, _ = UserProfile.objects.get_or_create(user=self.to_user)

        self.follow_user_url = reverse("follow-user", kwargs={"uuid": self.to_user.uuid})   
   
    def test_follower_requests_to_follow_public(self):
        self.profile_following.is_public = True
        self.profile_following.save()

        self.client.force_authenticate(user = self.from_user)
        follow_action_response = self.client.post(self.follow_user_url)

        self.assertEqual(follow_action_response.status_code,status.HTTP_201_CREATED)
        self.assertEqual(follow_action_response.data["status"],"Following")

        self.profile_follower.refresh_from_db()
        self.profile_following.refresh_from_db()

        self.assertEqual(self.profile_follower.following_count, 1)
        self.assertEqual(self.profile_following.followers_count, 1)
    
    def test_follower_requests_to_follow_private(self):
        self.profile_following.is_public = False
        self.profile_following.save()

        self.client.force_authenticate(user = self.from_user)
        follow_action_response = self.client.post(self.follow_user_url)

        self.assertEqual(follow_action_response.status_code,status.HTTP_201_CREATED)
        self.assertEqual(follow_action_response.data["status"],"Follow request sent")

        self.profile_follower.refresh_from_db()
        self.profile_following.refresh_from_db()

        self.assertEqual(self.profile_follower.following_count, 0)
        self.assertEqual(self.profile_following.followers_count, 0)
    
    def account_tries_to_follow_himself(self):
       
        self.client.force_authenticate(user=self.from_user)

        own_account_url = reverse("follow-user",kwargs={"uuid":self.from_user.uuid})

        response = self.client.post(own_account_url)
        self.assertEqual(response.status_code,status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["status"],"Can't follow yourself")

        self.profile_follower.refresh_from_db()
        self.assertEqual(self.profile_follower.following_count, 0)
        self.assertEqual(self.profile_following.followers_count, 0)
    
    def test_unfollow_public_user(self):
    
        self.profile_following.is_public = True
        self.profile_following.save()
        self.client.force_authenticate(user=self.from_user)

        self.client.post(self.follow_user_url)
        
        response = self.client.post(self.follow_user_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "Unfollowed")
        
        self.profile_follower.refresh_from_db()
        self.profile_following.refresh_from_db()
        self.assertEqual(self.profile_follower.following_count, 0)
        self.assertEqual(self.profile_following.followers_count, 0)
    
    def test_cancel_pending_follow_request(self):
        
        self.profile_following.is_public = False
        self.profile_following.save()
        self.client.force_authenticate(user=self.from_user)

        self.client.post(self.follow_user_url)
        
        response = self.client.post(self.follow_user_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "Follow request cancelled")
        
        self.assertFalse(UserFollower.objects.filter(
            from_user=self.from_user, 
            to_user=self.to_user
        ).exists())

        self.profile_follower.refresh_from_db()
        self.profile_following.refresh_from_db()

        self.assertEqual(self.profile_follower.following_count, 0)
        self.assertEqual(self.profile_following.followers_count, 0)
    
    def test_follow_non_existent_user(self):
        self.client.force_authenticate(user=self.from_user)
        invalid_url = reverse("follow-user", kwargs={"uuid": "00000000-0000-0000-0000-000000000000"})
        response = self.client.post(invalid_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_anonymous_user_cannot_follow(self):
        self.client.logout()
        response = self.client.post(self.follow_user_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    

class AcceptFollowViewTest(APITestCase):

    def setUp(self):
        self.from_user = User.objects.create_user(username="Arnold", email="arnold@gmail.com", password="password123")
        self.to_user = User.objects.create_user(username="Phil", email="phil@gmail.com", password="password123")
        
        self.profile_from_user, _ = UserProfile.objects.get_or_create(user=self.from_user)
        self.profile_to_user, _ = UserProfile.objects.get_or_create(user=self.to_user)

        self.follow_request = UserFollower.objects.create(
            from_user=self.from_user,
            to_user=self.to_user,
            status=UserFollower.FollowStatus.PENDING
        )

        self.accept_url = reverse("accept-follow",kwargs={"uuid":self.from_user.uuid})
       
    
    def test_to_user_accepts_from_user(self):
        
        self.client.force_authenticate(user = self.to_user)
        accept = self.client.post(self.accept_url)
       
        self.assertEqual(accept.status_code,status.HTTP_200_OK)
        self.assertEqual(accept.data["status"], "Follow request accepted")

        self.profile_from_user.refresh_from_db()
        self.profile_to_user.refresh_from_db()

        self.assertEqual(self.profile_to_user.followers_count,1)
        self.assertEqual(self.profile_from_user.following_count,1)
    
    def test_cannot_accept_already_accepted_request(self):
        self.follow_request.status = UserFollower.FollowStatus.ACCEPTED
        self.follow_request.save()

        self.client.force_authenticate(user=self.to_user)
        response = self.client.post(self.accept_url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_wrong_user_cannot_accept_request(self):
        self.third_party = User.objects.create_user(username="Helga",email="helga123@gmail.com", password="password123")
        self.client.force_authenticate(user=self.third_party)

        response = self.client.post(self.accept_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

class RejectViewTest(APITestCase):

    def setUp(self):
        self.from_user = User.objects.create_user(username="Arnold", email="arnold@gmail.com", password="password123")
        self.to_user = User.objects.create_user(username="Phil", email="phil@gmail.com", password="password123")
        
        self.profile_from_user, _ = UserProfile.objects.get_or_create(user=self.from_user)
        self.profile_to_user, _ = UserProfile.objects.get_or_create(user=self.to_user)

        self.follow_request = UserFollower.objects.create(
            from_user=self.from_user,
            to_user=self.to_user,
            status=UserFollower.FollowStatus.PENDING
        )

        self.reject_url = reverse("reject-follow",kwargs={"uuid":self.from_user.uuid})
    

    def test_to_user_rejects_from_user_successfully(self):

        self.client.force_authenticate(user = self.to_user)
        response = self.client.post(self.reject_url)
        self.assertEqual(response.status_code,status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "Follow request rejected")
        self.assertFalse(UserFollower.objects.filter(pk=self.follow_request.pk).exists())
    
    def test_cannot_reject_accepted_follow(self):
        self.follow_request.status = UserFollower.FollowStatus.ACCEPTED
        self.follow_request.save()

        self.client.force_authenticate(user=self.to_user)
        response = self.client.post(self.reject_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.assertTrue(UserFollower.objects.filter(pk=self.follow_request.pk).exists())
    
    def test_wrong_user_cannot_reject_request(self):
        self.client.force_authenticate(user=self.from_user)
        response = self.client.post(self.reject_url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

class ProfileNetworkListViewTests(APITestCase):

    def setUp(self):
        self.from_user = User.objects.create_user(username="Arnold", email="arnold@gmail.com", password="password123")
        self.target = User.objects.create_user(username="Phil", email="phil@gmail.com", password="password123")

        self.profile_from_user, _ = UserProfile.objects.get_or_create(user=self.from_user)
        self.profile_target, _ = UserProfile.objects.get_or_create(user=self.target)

        self.network_urls = [
            reverse("following-list", kwargs={"uuid": self.target.uuid}),
            reverse("follower-list", kwargs={"uuid": self.target.uuid})
        ]


    def test_unauth_user_cant_view(self):
        self.profile_target.is_public = True
        self.profile_target.save()

        for url in self.network_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_from_user_cannot_view_private_lists(self):
        self.profile_target.is_public = False
        self.profile_target.save()

        self.client.force_authenticate(user=self.from_user)

        for url in self.network_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                self.assertEqual(response.data["error"]["message"], "This profile is private.")

    def test_account_owner_can_view_own_lists(self):
        self.profile_target.is_public = False
        self.profile_target.save()

        self.client.force_authenticate(user=self.target)

        for url in self.network_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_accepted_follower_can_view_private_lists(self):
        self.profile_target.is_public = False
        self.profile_target.save()

        UserFollower.objects.create(
            from_user=self.from_user,
            to_user=self.target,
            status=UserFollower.FollowStatus.ACCEPTED
        )

        self.client.force_authenticate(user=self.from_user)

        for url in self.network_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_200_OK)


    def test_network_lists_return_correct_data(self):
       
        UserFollower.objects.create(
            from_user=self.from_user,
            to_user=self.target,
            status=UserFollower.FollowStatus.ACCEPTED
        )

       
        self.client.force_authenticate(user=self.target)

        
        follower_url = reverse("follower-list", kwargs={"uuid": self.target.uuid})
        follower_response = self.client.get(follower_url)
        self.assertEqual(follower_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(follower_response.data["results"]), 1)
        self.assertEqual(follower_response.data["results"][0]["user"]["username"], "Arnold")

        following_url = reverse("following-list", kwargs={"uuid": self.from_user.uuid})
        self.client.force_authenticate(user=self.from_user) 
        following_response = self.client.get(following_url)
        
        self.assertEqual(following_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(following_response.data["results"]), 1)
        self.assertEqual(following_response.data["results"][0]["user"]["username"], "Phil")



        

    
        
       



