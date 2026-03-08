from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from .views import RegisterView, MyProfileView, UserProfileView, LogoutView, ChangePasswordView

urlpatterns = [
    path("token/refresh/", TokenRefreshView.as_view(), name='token_refresh'),
    path("token/verify/", TokenVerifyView.as_view(), name='token_verify'),
    path("sign-up/", RegisterView.as_view(), name="sign-up"),
    path("log-out/", LogoutView.as_view(), name="log-out"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("my-profile/", MyProfileView.as_view(), name="my-profile"),
    path("profiles/<uuid:uuid>/", UserProfileView.as_view(), name="user-profile"),
]