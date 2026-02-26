from rest_framework import serializers
from .models import Exercise , WorkoutExercise , Workout , MuscleGroup
from users.serializers import MiniUserProfileSerializer

class MuscleGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = MuscleGroup
        fields = ("id","name","description")

class ExerciseSerializer(serializers.ModelSerializer):
    muscles = MuscleGroupSerializer(many=True,read_only=True)
    class Meta:
        model = Exercise
        fields = ("id","name","description","exercise_type","movement_type","difficulty","muscles","instructions","video_url","equipment_needed","created_at","updated_at")

class WorkoutExerciseSerializer(serializers.ModelSerializer):
    exercise = ExerciseSerializer(read_only=True)
    class Meta:
        model = WorkoutExercise
        fields = ("id","exercise","order","sets","reps","weight_kg","duration_sec","rest_sec","notes")

class WorkoutSerializer(serializers.ModelSerializer):
    workout_exercises = WorkoutExerciseSerializer(many=True,read_only=True)
    owner = MiniUserProfileSerializer(read_only=True)
    class Meta:
        model = Workout
        fields = ("id","owner","name","description","cover_image","workout_exercises","visibility","estimated_duration_min","is_template","created_at","updated_at")