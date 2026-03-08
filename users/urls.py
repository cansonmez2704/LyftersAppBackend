from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from .views import (
    RegisterView, MyProfileView, UserProfileView,
    LogoutView, ChangePasswordView,
    FollowUserView, AcceptFollowView, RejectFollowView,
    FollowerListView, FollowingListView,
)

urlpatterns = [
    # Auth
    path("token/refresh/", TokenRefreshView.as_view(), name='token_refresh'),
    path("token/verify/", TokenVerifyView.as_view(), name='token_verify'),
    path("sign-up/", RegisterView.as_view(), name="sign-up"),
    path("log-out/", LogoutView.as_view(), name="log-out"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),

    # Profile
    path("my-profile/", MyProfileView.as_view(), name="my-profile"),
    path("profiles/<uuid:uuid>/", UserProfileView.as_view(), name="user-profile"),

    # Follow system
    path("<uuid:uuid>/follow/", FollowUserView.as_view(), name="follow-toggle"),
    path("<uuid:uuid>/followers/", FollowerListView.as_view(), name="follower-list"),
    path("<uuid:uuid>/following/", FollowingListView.as_view(), name="following-list"),
    path("followers/<uuid:uuid>/accept/", AcceptFollowView.as_view(), name="follow-accept"),
    path("followers/<uuid:uuid>/reject/", RejectFollowView.as_view(), name="follow-reject"),
]