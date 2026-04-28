from rest_framework import serializers
from .models import Exercise , WorkoutSet,WorkoutExercise , Workout , MuscleGroup
from users.serializers import MiniUserProfileSerializer
from django.db import transaction

class MuscleGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = MuscleGroup
        fields = ("id", "name", "slug", "description")

class ExerciseSerializer(serializers.ModelSerializer):
    muscles = MuscleGroupSerializer(many=True,read_only=True)
    class Meta:
        model = Exercise
        fields = ("id", "uuid", "name", "slug", "description", "exercise_type", "movement_type", "difficulty", "muscles", "instructions", "video_url", "equipment_needed", "created_at", "updated_at")

class WorkoutSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkoutSet
        fields = ("set_number","reps","weight_unit","weight","duration_seconds")

    

class WorkoutExerciseSerializer(serializers.ModelSerializer):
    exercise = ExerciseSerializer(read_only=True)
    sets = WorkoutSetSerializer(read_only=True,many=True)
    class Meta:
        model = WorkoutExercise
        fields = ("id","exercise","order","sets","notes")
    
    

class WorkoutExerciseWriteSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    exercise = serializers.PrimaryKeyRelatedField(queryset=Exercise.objects.all())
    sets = WorkoutSetSerializer(many=True)
    class Meta:
        model = WorkoutExercise
        fields = ("id","exercise","order","sets","notes")

     


class WorkoutListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views — no exercise/set tree.

    Pulling the full tree on list pages produced thousands of rows per request
    (N exercises × M sets × K muscles). Clients that need the tree hit
    retrieve (`GET /workouts/<uuid>/`) instead.
    """

    owner = MiniUserProfileSerializer(source="owner.profile", read_only=True)

    class Meta:
        model = Workout
        fields = (
            "id", "uuid", "owner", "name", "description", "cover_image",
            "visibility", "estimated_duration_min",
            "created_at", "updated_at",
        )


class WorkoutSerializer(serializers.ModelSerializer):
    workout_exercises = WorkoutExerciseSerializer(many=True,read_only=True)
    owner = MiniUserProfileSerializer(source="owner.profile", read_only=True)

    class Meta:
        model = Workout
        fields = ("id","uuid","owner","name","description","cover_image","workout_exercises","visibility","estimated_duration_min","created_at","updated_at")

    

class WorkoutWriteSerializer(serializers.ModelSerializer):
    workout_exercises = WorkoutExerciseWriteSerializer(many=True)
    
    class Meta:
        model = Workout
        fields = ("id", "name", "description", "cover_image", "workout_exercises", "visibility", "estimated_duration_min")
    
    def create(self, validated_data):
        with transaction.atomic():
            exercises_data = validated_data.pop("workout_exercises", [])
            workout = Workout.objects.create(**validated_data)
            self._save_workout_exercises(workout, exercises_data)
            return workout

    def update(self, instance, validated_data):
        exercises_data = validated_data.pop("workout_exercises", None)
        
        with transaction.atomic():
            # 1. Update the top-level Workout fields
            instance = super().update(instance, validated_data)

            if exercises_data is not None:
                self._sync_workout_exercises(instance, exercises_data)
                
        return instance

    def _save_workout_exercises(self, workout, exercises_data):
        """
        Helper method to handle the heavy lifting of nested creation.
        Optimized to use bulk_create for both exercises and sets.
        """
        we_instances = []
        sets_map = [] 

        for exercise_item in exercises_data:
            sets_data = exercise_item.pop("sets", [])
            we = WorkoutExercise(workout=workout, **exercise_item)
            we_instances.append(we)
            sets_map.append(sets_data)

        # Bulk Create Exercises
        created_exercises = WorkoutExercise.objects.bulk_create(we_instances)

        # Map and Bulk Create Sets
        all_sets = []
        for i, workout_exercise in enumerate(created_exercises):
            for set_data in sets_map[i]:
                all_sets.append(WorkoutSet(workout_exercise=workout_exercise, **set_data))

        if all_sets:
            WorkoutSet.objects.bulk_create(all_sets)

    def _sync_workout_exercises(self, workout, exercises_data):
        """
        Reconciles incoming nested data with existing database records.
        """
        existing_exercises = {we.id: we for we in workout.workout_exercises.all()}
        incoming_exercises_ids = [item['id'] for item in exercises_data if 'id' in item]

        ids_to_delete = [
            ex_id for ex_id in existing_exercises.keys()
            if ex_id not in incoming_exercises_ids
        ]

        if ids_to_delete:
            WorkoutExercise.objects.filter(id__in=ids_to_delete).delete()
            for ex_id in ids_to_delete:
                existing_exercises.pop(ex_id)

        # Shift existing orders to high temp values to avoid unique constraint
        # violations when reordering (unique on workout_id + order).
        offset = 10000
        for we in existing_exercises.values():
            we.order = we.order + offset
        WorkoutExercise.objects.bulk_update(existing_exercises.values(), ["order"])

        sets_by_we = {}

        for item in exercises_data:
            exercise_id = item.get('id')
            sets_data = item.pop('sets', [])

            if exercise_id and exercise_id in existing_exercises:
                we_instance = existing_exercises[exercise_id]
                for attr, value in item.items():
                    setattr(we_instance, attr, value)
                we_instance.save()
            else:
                we_instance = WorkoutExercise.objects.create(workout=workout, **item)

            sets_by_we[we_instance.id] = (we_instance, sets_data)

        for we_instance, sets_data in sets_by_we.values():
            we_instance.sets.all().delete()
            if sets_data:
                WorkoutSet.objects.bulk_create([
                    WorkoutSet(workout_exercise=we_instance, **s) for s in sets_data
                ])