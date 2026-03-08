from django.contrib.auth import get_user_model
from django.db.models import Q , F
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from rest_framework import generics, status , permissions
from rest_framework.response import Response
from rest_framework.permissions import AllowAny , IsAdminUser , IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken , OutstandingToken , BlacklistedToken , TokenError
from .models import UserProfile , UserFollower
from .serializers import UserRegisterSerializer , FullUserProfileSerializer , MiniUserProfileSerializer , ChangePasswordSerializer , UserFollowerSerializer
from common.permissions import IsOwner

User = get_user_model()
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserRegisterSerializer
    permission_classes = [AllowAny,]

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
    





        
    

        
    


        
    
    
  
       
        





