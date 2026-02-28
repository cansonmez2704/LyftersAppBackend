from rest_framework import generics, status , permissions
from rest_framework.response import Response
from rest_framework.permissions import AllowAny , IsAdminUser , IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from .models import UserProfile
from .serializers import UserRegisterSerializer , FullUserProfileSerializer , MiniUserProfileSerializer
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

        
    


        
    
    
  
       
        





