from django.urls import path , include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView,  TokenVerifyView
from .views import RegisterView , MyProfileView , UserProfileView

urlpatterns = [
    path("token/",TokenObtainPairView.as_view(),name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name='token_refresh'),
    path("token/verify/", TokenVerifyView.as_view(), name='token_verify'),
    path("sign-up/",RegisterView.as_view(),name="sign-up"),
    path("my-profile/",MyProfileView.as_view(),name = "my-profile"),
    path("profiles/<uuid:uuid>/",UserProfileView.as_view(),name = "user-profile"),
]
