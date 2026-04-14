from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, F
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied 
from rest_framework import generics, status
from rest_framework.filters import SearchFilter
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken, OutstandingToken, BlacklistedToken, TokenError
from .models import UserProfile, UserFollower
from .serializers import UserRegisterSerializer, FullUserProfileSerializer, MiniUserProfileSerializer, ChangePasswordSerializer
from common.pagination import FeedCursorPagination
from common.follow import toggle_follow

User = get_user_model()
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserRegisterSerializer
    permission_classes = [AllowAny,]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'strict_auth'

    def create (self,request,*args,**kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        refresh = RefreshToken.for_user(user)

        return Response({
            "message": "Account created successfully!",
            "user": serializer.data,
            "tokens": {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            }
        }, status=status.HTTP_201_CREATED)

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'strict_auth'

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if not refresh_token:
                return Response(
                    {"error": "Refresh token is required to log out."}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response(
                {"message": "Successfully logged out."}, 
                status=status.HTTP_205_RESET_CONTENT
            )
            
        except TokenError:
            return Response(
                {"error": "Token is invalid or already logged out."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'strict_auth'

    def put(self, request, *args, **kwargs):
        serializer = ChangePasswordSerializer(
            data=request.data, 
            context={'request': request} 
        )
        
        if serializer.is_valid():
            user = request.user
            user.set_password(serializer.validated_data['new_password'])
            user.save()

            active_tokens = OutstandingToken.objects.filter(user=user)
            
            for token in active_tokens:
                BlacklistedToken.objects.get_or_create(token=token)    
            
            return Response(
                {"message": "Password updated successfully."}, 
                status=status.HTTP_200_OK
            )
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class MyProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = FullUserProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user.profile
    
class UserProfileView(generics.RetrieveAPIView):

    lookup_field = "user__uuid"
    lookup_url_kwarg = "uuid"
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
     return UserProfile.objects.select_related("user")
    
    def retrieve(self, request, *args, **kwargs):
        profile = self.get_object()
       
        is_owner = (profile.user == request.user)
        is_admin = request.user.is_staff
        is_public = profile.is_public

        if is_owner or is_admin or is_public:
            serializer = FullUserProfileSerializer(profile, context={'request': request})
        else:
            serializer = MiniUserProfileSerializer(profile, context={'request': request})
        return Response(serializer.data)


class FollowUserView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, uuid):
        target_profile = get_object_or_404(
            UserProfile.objects.select_related("user"),
            user__uuid=uuid,
        )
        return toggle_follow(
            follow_model=UserFollower,
            from_user=request.user,
            target_profile=target_profile,
        )


class AcceptFollowView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, uuid):
        follow_request = get_object_or_404(
            UserFollower,
            from_user__uuid=uuid,
            to_user=request.user,
            status=UserFollower.FollowStatus.PENDING,
        )

        with transaction.atomic():
            follower_profile = UserProfile.objects.get(user=follow_request.from_user)
            target_profile = request.user.profile

            ordered_pks = sorted([follower_profile.pk, target_profile.pk])
            locked_profiles = {
                p.pk: p
                for p in UserProfile.objects.select_for_update().filter(pk__in=ordered_pks)
            }

            follow_request.status = UserFollower.FollowStatus.ACCEPTED
            follow_request.save(update_fields=["status"])

            UserProfile.objects.filter(pk=target_profile.pk).update(
                followers_count=F("followers_count") + 1,
            )
            UserProfile.objects.filter(pk=follower_profile.pk).update(
                following_count=F("following_count") + 1,
            )

        return Response({"status": "Follow request accepted"}, status=status.HTTP_200_OK)


class RejectFollowView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, uuid):
        follow_request = get_object_or_404(
            UserFollower,
            from_user__uuid=uuid,
            to_user=request.user,
            status=UserFollower.FollowStatus.PENDING,
        )
        follow_request.delete()
        return Response({"status": "Follow request rejected"}, status=status.HTTP_200_OK)

class FollowerListView(generics.ListAPIView):
    serializer_class = MiniUserProfileSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = FeedCursorPagination
    filter_backends = [SearchFilter]
    search_fields = ["user__username"]

    def get_queryset(self):
        target_profile = get_object_or_404(
            UserProfile.objects.select_related('user'), 
            user__uuid=self.kwargs["uuid"]
        )

        if not target_profile.is_public and target_profile.user != self.request.user:
            has_access = UserFollower.objects.filter(
                from_user=self.request.user, 
                to_user=target_profile.user, 
                status=UserFollower.FollowStatus.ACCEPTED
            ).exists()
            
            if not has_access:
                raise PermissionDenied("This profile is private.")

        return (
            UserProfile.objects
            .filter(
                user__outgoing_followers__to_user__uuid=self.kwargs["uuid"],
                user__outgoing_followers__status=UserFollower.FollowStatus.ACCEPTED,
            )
            .select_related("user")
        )

class FollowingListView(generics.ListAPIView):
    serializer_class = MiniUserProfileSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = FeedCursorPagination
    filter_backends = [SearchFilter]
    search_fields = ["user__username"]

    def get_queryset(self):
        
        target_profile = get_object_or_404(
            UserProfile.objects.select_related('user'), 
            user__uuid=self.kwargs["uuid"]
        )

 
        if not target_profile.is_public and target_profile.user != self.request.user:
            has_access = UserFollower.objects.filter(
                from_user=self.request.user, 
                to_user=target_profile.user, 
                status=UserFollower.FollowStatus.ACCEPTED
            ).exists()
            
            if not has_access:
                raise PermissionDenied("This profile is private.")

        
        return (
            UserProfile.objects
            .filter(
                user__incoming_followers__from_user__uuid=self.kwargs["uuid"],
                user__incoming_followers__status=UserFollower.FollowStatus.ACCEPTED,
            )
            .select_related("user")
        )

        
    


        
    
    
  
       
        





