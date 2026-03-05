from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Greatest

def toggle_reaction(*, reaction_model, parent_obj, parent_field_name,
                    user, reaction_type, valid_choices):
    # 1. Start the 'All-or-Nothing' Safety Bubble
    with transaction.atomic():
        
        # 2. LOCK the parent object (Post or Comment) to update counters safely
        # This prevents two users from updating the same count at the same millisecond
        parent_model = parent_obj.__class__
        parent_obj = parent_model.objects.select_for_update().get(pk=parent_obj.pk)

        if reaction_type not in valid_choices:
            return ("Invalid reaction type.", 400)

        # 3. LOCK the specific reaction row (if it exists)
        # This prevents the 'Double Tap' where a user creates two likes by mistake
        lookup = {"user": user, parent_field_name: parent_obj}
        existing = reaction_model.objects.select_for_update().filter(**lookup).first()

        like_field = "likes_count"
        dislike_field = "dislikes_count"
        delta_field = like_field if reaction_type == "like" else dislike_field
        opposite_field = dislike_field if reaction_type == "like" else like_field

        if not existing:
            # New reaction logic
            reaction_model.objects.create(**lookup, reaction_type=reaction_type)
            parent_model.objects.filter(pk=parent_obj.pk).update(
                **{delta_field: F(delta_field) + 1}
            )
            return ("Reaction added", 201)

        if existing.reaction_type == reaction_type:
            # Undo same reaction logic
            existing.delete()
            parent_model.objects.filter(pk=parent_obj.pk).update(
                **{delta_field: Greatest(F(delta_field) - 1, Value(0))}
            )
            return ("Reaction removed", 200)

        # Switch reaction logic
        existing.reaction_type = reaction_type
        existing.save(update_fields=["reaction_type"])
        parent_model.objects.filter(pk=parent_obj.pk).update(
            **{
                delta_field: F(delta_field) + 1,
                opposite_field: Greatest(F(opposite_field) - 1, Value(0)),
            }
        )
        return ("Reaction changed", 200)