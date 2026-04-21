from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from users.models import User,UserFollower,UserProfile
import tempfile
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from community.models import Post

class MyProfileViewTest(APITestCase):

    def setUp(self):

        self.profile_url = reverse("my-profile")

        self.user = User.objects.create_user(
        username="arnold", email="arnold@gold.com", password="password123"
           )
        self.stranger = User.objects.create_user(
        username="stranger", email="stranger@test.com", password="password123"
          )
        self.admin = User.objects.create_superuser(
        username="admin", email="admin@gymhub.com", password="adminpassword"
          )
        
        image = Image.new('RGB', (100, 100))
        tmp_file = tempfile.NamedTemporaryFile(suffix='.jpg')
        image.save(tmp_file)
        tmp_file.seek(0)
        self.dummy_avatar = SimpleUploadedFile("avatar.jpg", tmp_file.read(), content_type="image/jpeg")

      
        self.profile, created = UserProfile.objects.get_or_create(user=self.user)
        self.profile.bio = "7x Mr. Olympia"
        self.profile.height = 188
        self.profile.weight = 105
        self.profile.gender = "M"
        self.profile.is_public = False 
        self.profile.avatar = self.dummy_avatar
        self.profile.save()

        self.post = Post.objects.create(
            author=self.user,
            title="First Post",
            description="I'll be back.",
            visibility=Post.Visibility.PUBLIC
        )
    
    def test_owner_retrieve_update_profile(self):
       
        user = self.profile.user

        self.client.force_authenticate(user=user)

        response_read = self.client.get(self.profile_url)
        self.assertEqual(response_read.status_code,status.HTTP_200_OK)

        patch_payload = {
            "bio": "Updated bio: Training for the next competition.",
            "height": 190,
            "weight": 110,
            "gender": "M",
            "is_public": True,
            "birth_date": "1947-07-30"
        }
       
        response_patch = self.client.patch(self.profile_url,patch_payload,format="json")
        self.assertEqual(response_patch.status_code,status.HTTP_200_OK)
    
    def test_stranger_access_to_private_profile(self):

        self.profile.is_public = False
        self.profile.save()

        arnold_profile_link = reverse("user-profile",kwargs={"uuid":self.user.uuid})

        stranger = self.stranger
        self.client.force_authenticate(stranger)

        stranger_read_response = self.client.get(arnold_profile_link)
        self.assertEqual(stranger_read_response.status_code,status.HTTP_200_OK)

        # Private profiles are discoverable; restricted data (posts/workouts) stays hidden.
        self.assertEqual(stranger_read_response.data.get("is_public"), False)
        self.assertNotIn("posts", stranger_read_response.data)
        self.assertNotIn("workouts", stranger_read_response.data)

        self.assertEqual(stranger_read_response.data['user']['username'], "arnold")
    
    def test_admin_access_to_private_profile(self):

         self.profile.is_public = False
         self.profile.save()

         arnold_profile_link = reverse("user-profile",kwargs={"uuid":self.user.uuid})
         self.client.force_authenticate(self.admin)

         response = self.client.get(arnold_profile_link)
         self.assertEqual(response.status_code,status.HTTP_200_OK)

         self.assertIn("bio",response.data)
         self.assertEqual(response.data['weight'], 105)

    def test_stranger_cannot_update_other_profile(self):
   
        self.profile.is_public = True 
        self.profile.save()
        arnold_profile_link = reverse("user-profile", kwargs={"uuid": self.user.uuid})
        
        self.client.force_authenticate(self.stranger)
        
    
        patch_payload = {"bio": "Hacked by a stranger"}
        response = self.client.patch(arnold_profile_link, patch_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        
        
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.bio, "7x Mr. Olympia")
        

        







        

