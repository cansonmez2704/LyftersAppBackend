from rest_framework import status
from rest_framework.test import APITestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken

User = get_user_model()

class AuthViewsTests(APITestCase):

    def setUp(self):
        
        self.user_password = "SecurePassword123!"
        self.user = User.objects.create_user(
            username="testuser", 
            email="testuser@gmail.com", 
            password=self.user_password
        )
        
        self.refresh_token = RefreshToken.for_user(self.user)
        self.access_token = str(self.refresh_token.access_token)

        self.register_url = reverse("sign-up") 
        self.logout_url = reverse("logout")     
        self.change_password_url = reverse("change-password") 
    
    def test_register_user_succes(self):

        payload = {"username":"newuser", 
                   "email":"testuser@gmail.com",
                   "password" : "StrongPassw0rd!234" ,
                   "confirm_password":"StrongPassw0rd!234"
            }

        response = self.client.post(self.register_url,payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["message"], "Account created successfully!")
        self.assertIn("refresh", response.data["tokens"])
        self.assertIn("access", response.data["tokens"])
        self.assertTrue(User.objects.filter(username="newuser").exists())
    
    def test_register_user_missing_data(self):
        response = self.client.post(self.register_url, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    

    def test_logout_success(self):
        self.client.credentials(HTTP_AUTHORIZATION = f"Bearer {self.access_token}")
        payload = {"refresh": str(self.refresh_token)}
        response = self.client.post(self.logout_url,payload)

        self.assertEqual(response.status_code,status.HTTP_204_NO_CONTENT)
        
        outstanding = OutstandingToken.objects.get(token=str(self.refresh_token))
        self.assertTrue(BlacklistedToken.objects.filter(token=outstanding).exists())
    
    def test_logout_without_refresh_token(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
        
        response = self.client.post(self.logout_url, {}) 
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Refresh token is required to log out.")

    def test_logout_unauthenticated_user(self):
      
        payload = {"refresh": str(self.refresh_token)}
        response = self.client.post(self.logout_url, payload)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


    def test_change_password_success(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
        
        payload = {
            "old_password": self.user_password,
            "new_password": "EvenBetterPassword456!"
        }
        response = self.client.put(self.change_password_url, payload)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Password updated successfully.")
      
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("EvenBetterPassword456!"))
     
        outstanding_tokens = OutstandingToken.objects.filter(user=self.user)
        for token in outstanding_tokens:
            self.assertTrue(BlacklistedToken.objects.filter(token=token).exists())

    def test_change_password_wrong_old_password(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
        
        payload = {
            "old_password": "WrongPassword!",
            "new_password": "EvenBetterPassword456!"
        }
        response = self.client.put(self.change_password_url, payload)
     
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("old_password", response.data)
