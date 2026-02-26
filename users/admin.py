from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User , UserProfile


class UserProfileInline(admin.TabularInline):
    model = UserProfile
    extra = 1



@admin.register(User)
class CustomUserAdmin(UserAdmin): 
    
    list_display = ("username", "email", "is_staff")
    list_filter = ("is_staff", "is_superuser", "is_active") 
    inlines = [UserProfileInline]
    
    

