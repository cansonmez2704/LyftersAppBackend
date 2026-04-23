from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    # The post_save signal on User already creates exactly one profile. Letting
    # the admin render an extra empty inline row would always fail to save
    # because of the OneToOneField uniqueness — so we pin it to the single row
    # that actually exists.
    extra = 0
    max_num = 1
    can_delete = False


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "is_staff")
    list_filter = ("is_staff", "is_superuser", "is_active")
    inlines = [UserProfileInline]
