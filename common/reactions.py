from django.db import IntegrityError, transaction
from django.db.models import F, Value
from django.db.models.functions import Greatest
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework import status


def toggle_reaction(*, reaction_model, parent_obj, parent_field_name,
                    user, reaction_type, valid_choices):
    if not reaction_type:
        raise ValidationError({"reaction_type": "This field is required."})

    if reaction_type not in valid_choices:
        raise ValidationError(
            {"reaction_type": f"Invalid choice. Must be one of: {', '.join(valid_choices)}"}
        )

    parent_model = parent_obj.__class__
    lookup = {"user": user, parent_field_name: parent_obj}

    like_field = "likes_count"
    dislike_field = "dislikes_count"
    delta_field = like_field if reaction_type == "like" else dislike_field
    opposite_field = dislike_field if reaction_type == "like" else like_field

    with transaction.atomic():
        # Always lock the parent (Post/Comment) first — it's the coarser
        # resource. Other writers on the same parent queue up here, which
        # gives us a consistent ordering that matches perform_destroy and
        # reconcile_counters, eliminating the deadlock window where two
        # coroutines grabbed locks in opposite orders.
        if not parent_model.objects.select_for_update().filter(pk=parent_obj.pk).exists():
            raise ValidationError("Parent no longer exists.")

        existing = reaction_model.objects.select_for_update().filter(**lookup).first()

        if not existing:
            try:
                reaction_model.objects.create(**lookup, reaction_type=reaction_type)
            except IntegrityError:
                raise ValidationError("Already reacted.")
            parent_model.objects.filter(pk=parent_obj.pk).update(
                **{delta_field: F(delta_field) + 1}
            )
            return Response({"status": "Reaction added"}, status=status.HTTP_201_CREATED)

        if existing.reaction_type == reaction_type:
            deleted_count, _ = reaction_model.objects.filter(pk=existing.pk).delete()
            if not deleted_count:
                raise ValidationError("Already removed.")

            parent_model.objects.filter(pk=parent_obj.pk).update(
                **{delta_field: Greatest(F(delta_field) - 1, Value(0))}
            )
            return Response({"status": "Reaction removed"}, status=status.HTTP_200_OK)

        updated_count = reaction_model.objects.filter(pk=existing.pk).update(
            reaction_type=reaction_type,
        )
        if not updated_count:
            raise ValidationError("Reaction already changed.")

        parent_model.objects.filter(pk=parent_obj.pk).update(**{
            delta_field: F(delta_field) + 1,
            opposite_field: Greatest(F(opposite_field) - 1, Value(0)),
        })
        return Response({"status": "Reaction changed"}, status=status.HTTP_200_OK)
