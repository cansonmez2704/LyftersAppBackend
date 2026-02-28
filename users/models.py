from django.contrib.auth.models import UserManager , AbstractUser
from django.db import models
from django.conf import settings
from PIL import Image
from django.db.models.signals import post_save
from django.dispatch import receiver
import uuid

class CustomUserManager(UserManager):

    def create_user(self, username, email=None, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email must be set")
        
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)

        user.save(using=self._db)
        return user

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(username, email, password, **extra_fields)
    

class User(AbstractUser):
    objects = CustomUserManager()
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    def __str__(self):
        return self.username

class UserProfile(models.Model):
    
    def avatar_upload_image_path(instance,filename):
        ext = filename.split(".")[-1]
        filename = f"avatar.{ext}"
        return f"avatars/user_{instance.user.id}/{filename}"

    class GenderChoices(models.TextChoices):
       MALE = "M" , "Male"
       FEMALE = "F" , "Female"
       OTHER =  "O" , "Other"
       
    
    user = models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="profile")
    avatar = models.ImageField(upload_to=avatar_upload_image_path, null = True, blank =True)
    is_public = models.BooleanField(default=True)
    bio = models.TextField(null = True , blank = True)
    height = models.IntegerField(null = True , blank = True)
    weight = models.IntegerField(null = True , blank = True)
    gender = models.CharField(max_length=10, choices=GenderChoices.choices, null = True , blank = True)
    birth_date = models.DateField(null = True , blank = True)
    

    def save(self,*args,**kwargs):
        super().save(*args,**kwargs)

        if self.avatar:
          img = Image.open(self.avatar.path)
         
          if img.height > 300 or img.width > 300:
            output_size = (300, 300)
            img.thumbnail(output_size) 
            img.save(self.avatar.path)

    @property
    def avatar_url(self):
     if self.avatar and hasattr(self.avatar, 'url'):
        return self.avatar.url
     return "/static/images/default-avatar.png"

@receiver(post_save,sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
   if created:
      UserProfile.objects.create(user=instance)


