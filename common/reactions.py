from django.db.models import F, Greatest, Value


def toggle_reaction(*, reaction_model, parent_obj, parent_field_name,
                    user, reaction_type, valid_choices):
  
    if reaction_type not in valid_choices:
        return ("Invalid reaction type. Must be 'like' or 'dislike'.", 400)

    lookup = {"user": user, parent_field_name: parent_obj}
    existing = reaction_model.objects.filter(**lookup).first()

    like_field = "likes_count"
    dislike_field = "dislikes_count"
    delta_field = like_field if reaction_type == "like" else dislike_field
    opposite_field = dislike_field if reaction_type == "like" else like_field

    if not existing:
        # New reaction
        reaction_model.objects.create(**lookup, reaction_type=reaction_type)
        parent_obj.__class__.objects.filter(pk=parent_obj.pk).update(
            **{delta_field: F(delta_field) + 1}
        )
        return ("Reaction added", 201)

    if existing.reaction_type == reaction_type:
        # Undo same reaction
        existing.delete()
        parent_obj.__class__.objects.filter(pk=parent_obj.pk).update(
            **{delta_field: Greatest(F(delta_field) - 1, Value(0))}
        )
        return ("Reaction removed", 200)

    # Switch reaction
    existing.reaction_type = reaction_type
    existing.save(update_fields=["reaction_type"])
    parent_obj.__class__.objects.filter(pk=parent_obj.pk).update(
        **{
            delta_field: F(delta_field) + 1,
            opposite_field: Greatest(F(opposite_field) - 1, Value(0)),
        }
    )
    return ("Reaction changed", 200)