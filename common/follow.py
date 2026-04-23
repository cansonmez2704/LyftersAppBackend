import logging
from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Greatest
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework import status
from .utils import lock_profiles_for_update



logger = logging.getLogger(__name__)

def toggle_follow(*, follow_model, from_user, target_profile):
    if from_user.pk == target_profile.user_id:
        return Response({"status": "Can't follow yourself"}, status=status.HTTP_400_BAD_REQUEST)

    profile_model = target_profile.__class__
    from_user_profile_pk = profile_model.objects.filter(user=from_user).values_list("pk", flat=True).first()

    with transaction.atomic():
        # 1. Use our new centralized locking utility
        locked_profiles = lock_profiles_for_update(target_profile.pk, from_user_profile_pk, profile_model)
        
        target_profile = locked_profiles[target_profile.pk]
        from_user_profile = locked_profiles[from_user_profile_pk]

        existing = (
            follow_model.objects
            .select_for_update()
            .filter(from_user=from_user, to_user=target_profile.user)
            .first()
        )

        if not existing:
            if target_profile.is_public:
                follow_model.objects.create(
                    from_user=from_user, to_user=target_profile.user, status=follow_model.FollowStatus.ACCEPTED
                )
                profile_model.objects.filter(pk=target_profile.pk).update(followers_count=F("followers_count") + 1)
                profile_model.objects.filter(pk=from_user_profile.pk).update(following_count=F("following_count") + 1)
                
                logger.info("User %s followed User %s", from_user.id, target_profile.user_id)
                return Response({"status": "Following"}, status=status.HTTP_201_CREATED)
            else:
                follow_model.objects.create(
                    from_user=from_user, to_user=target_profile.user, status=follow_model.FollowStatus.PENDING
                )
                logger.info("User %s requested to follow private User %s", from_user.id, target_profile.user_id)
                return Response({"status": "Follow request sent"}, status=status.HTTP_201_CREATED)
        else:
            status_was_accepted = existing.status == follow_model.FollowStatus.ACCEPTED
            existing.delete()

            if status_was_accepted:
                # 2. Prevent negative counters using Greatest()
                profile_model.objects.filter(pk=target_profile.pk).update(
                    followers_count=Greatest(F("followers_count") - 1, Value(0))
                )
                profile_model.objects.filter(pk=from_user_profile.pk).update(
                    following_count=Greatest(F("following_count") - 1, Value(0))
                )
                logger.info("User %s unfollowed User %s", from_user.id, target_profile.user_id)
                return Response({"status": "Unfollowed"}, status=status.HTTP_200_OK)
            
            return Response({"status": "Follow request cancelled"}, status=status.HTTP_200_OK)