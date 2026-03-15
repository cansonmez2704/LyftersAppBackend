from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from workouts.models import (
    MuscleGroup, 
    Exercise, 
    Workout, 
    WorkoutExercise, 
    WorkoutSet
)

User = get_user_model()

class ExerciseViewSetTests(APITestCase):

    def setUp(self):
        self.list_url = reverse("exercises-list")
        self.regular_user = User.objects.create_user(
            username="josh",
            email="joshjeffy@gmail.com",
            password="123456"
        )
        self.super_user = User.objects.create_superuser(
            username="admin_boss",
            email="admin@admin.com",
            password="supersecret"
        )

        # We create a Squat
        self.exercise = Exercise.objects.create(
            name="Squat",
            slug="squat",
            exercise_type=Exercise.ExerciseType.WEIGHTLIFTING
        )
        
        # BUG 1 FIX: Renamed to self.detail_url
        self.detail_url = reverse("exercises-detail", kwargs={"pk": self.exercise.pk})
        
        # BUG 2 FIX: Changed to Deadlift so it doesn't trigger unique=True error
        self.create_payload = {
            "name": "Deadlift",
            "slug": "deadlift-barbell",
            "description": "The ultimate pull."
        }   

    def test_regular_user_read_only_permissions(self):
        self.client.force_authenticate(user=self.regular_user)

        response_get = self.client.get(self.list_url)
        self.assertEqual(response_get.status_code, status.HTTP_200_OK)

        response_post = self.client.post(self.list_url, self.create_payload)
        self.assertEqual(response_post.status_code, status.HTTP_403_FORBIDDEN)

        response_delete = self.client.delete(self.detail_url)
        self.assertEqual(response_delete.status_code, status.HTTP_403_FORBIDDEN)

    def test_superuser_full_crud_permissions(self):
        self.client.force_authenticate(user=self.super_user)

        response_post = self.client.post(self.list_url, self.create_payload)
        self.assertEqual(response_post.status_code, status.HTTP_201_CREATED)
        
        self.assertEqual(Exercise.objects.count(), 2) 

        response_delete = self.client.delete(self.detail_url)
        self.assertEqual(response_delete.status_code, status.HTTP_204_NO_CONTENT)


class WorkoutViewSetTests(APITestCase):

    def setUp(self):
        self.workouts_list_url = reverse("workouts-list")        
        
        self.admin_user = User.objects.create_superuser(
            username="Cnmsz",
            email="cansonmez06@uoml.k12.tr",
            password="cnmsz1903*J"
        )

        self.user = User.objects.create_user(
            username="arnold", 
            email="arnold@goldssgym.com", 
            password="securepassword123"
        )

        # 2. Create Muscle Groups
        self.chest = MuscleGroup.objects.create(name="Chest", slug="chest")
        self.triceps = MuscleGroup.objects.create(name="Triceps", slug="triceps")

        # 3. Create the Exercise and add M2M relations
        self.bench_press = Exercise.objects.create(
            name="Barbell Bench Press",
            slug="barbell-bench-press",
            exercise_type=Exercise.ExerciseType.WEIGHTLIFTING,
            movement_type=Exercise.MovementType.COMPOUND,
            difficulty=Exercise.DifficultyLevel.INTERMEDIATE,
            equipment_needed="Barbell, Bench"
        )
        self.bench_press.muscles.add(self.chest, self.triceps)

        # 4. Create the main Workout container
        self.push_day = Workout.objects.create(
            owner=self.user,
            name="Heavy Push Day",
            description="Focus on chest and triceps strength.",
            visibility=Workout.Visibility.PUBLIC,
            estimated_duration_min=60
        )

        # 5. Create the Bridge (WorkoutExercise)
        self.workout_bench = WorkoutExercise.objects.create(
            workout=self.push_day,
            exercise=self.bench_press,
            order=0,
            notes="Warm up shoulders first. Keep back tight."
        )

        # 6. Create the Sets attached to that specific WorkoutExercise bridge
        WorkoutSet.objects.create(
            workout_exercise=self.workout_bench, # Updated to self.
            set_number=1, 
            reps=10, 
            weight=135, 
            weight_unit=WorkoutSet.WeightUnit.POUND
        )
        WorkoutSet.objects.create(
            workout_exercise=self.workout_bench, # Updated to self.
            set_number=2, 
            reps=8, 
            weight=185, 
            weight_unit=WorkoutSet.WeightUnit.POUND
        )
        WorkoutSet.objects.create(
            workout_exercise=self.workout_bench, # Updated to self.
            set_number=3, 
            reps=5, 
            weight=225, 
            weight_unit=WorkoutSet.WeightUnit.POUND
        )
        
        # Updated to self.push_day
        self.workouts_detail_url = reverse("workouts-detail", kwargs={"pk": self.push_day.pk})

    def test_unauthenticate_user_read_rejection(self):
   
      response = self.client.get(self.workouts_list_url)
   
      self.assertEqual(response.status_code,status.HTTP_401_UNAUTHORIZED)

    def test_admin_allowed_full_crud(self):
   
        self.client.force_authenticate(user=self.admin_user)

        response = self.client.get(self.workouts_list_url)
        self.assertEqual(response.status_code,status.HTTP_200_OK)

        get_workout = self.client.get(self.workouts_detail_url)
        self.assertEqual(get_workout.status_code,status.HTTP_200_OK)

        create_payload = {
            "name": "Admin's Secret Workout",
            "description": "Only the admin can do this.",
            "visibility": "public",
            "workout_exercises": [] # <-- The missing field!
        }
        create_workout = self.client.post(self.workouts_list_url,create_payload,format="json")
        self.assertEqual(create_workout.status_code,status.HTTP_201_CREATED)

        update_payload = {"name":"I changed the name of this workout"}
        update_workout = self.client.patch(self.workouts_detail_url,update_payload)
        self.assertEqual(update_workout.status_code,status.HTTP_200_OK)

        delete_workout = self.client.delete(self.workouts_detail_url)
        self.assertEqual(delete_workout.status_code,status.HTTP_204_NO_CONTENT)

    def test_isowner_else_read_if_public(self):
   
     stranger = User.objects.create_user(username = "stranger" ,email = "stranger123@gmail.com",password = "stranger123")

     self.client.force_authenticate(user = stranger)

     read_response = self.client.get(self.workouts_detail_url)
     self.assertEqual(read_response.status_code,status.HTTP_200_OK)

     update_payload = {"name": "Hacked Workout Name"}
     update_response = self.client.patch(self.workouts_detail_url,update_payload)
     self.assertEqual(update_response.status_code,status.HTTP_403_FORBIDDEN)

     delete_response = self.client.delete(self.workouts_detail_url)
     self.assertEqual(delete_response.status_code, status.HTTP_403_FORBIDDEN)


    def test_stranger_cannot_read_private_workout(self):
   
         private_workout = Workout.objects.create(
            owner=self.user, 
            name="Arnold's Secret Olympia Prep",
            visibility=Workout.Visibility.PRIVATE
        )
         private_url = reverse("workouts-detail",kwargs={"pk":private_workout.pk})

         stranger = User.objects.create_user(
            username="nosy_lifter", 
            email="nosy@test.com", 
            password="password123"
        )
         self.client.force_authenticate(user=stranger)

         response = self.client.get(private_url)

         self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


    def test_owner_allowed_full_crud_on_own_workout(self):
   
         owner = self.push_day.owner
         pk = self.push_day.pk

         self.client.force_authenticate(user = owner)

         workout_url = reverse("workouts-detail",kwargs={"pk":pk})
 
         response_read = self.client.get(workout_url)
         self.assertEqual(response_read.status_code,status.HTTP_200_OK)

         patch_payload = {"name": "back day"}
         response_patch = self.client.patch(workout_url,patch_payload)
         self.assertEqual(response_patch.status_code,status.HTTP_200_OK)

         response_delete = self.client.delete(workout_url)
         self.assertEqual(response_delete.status_code,status.HTTP_204_NO_CONTENT)


    def test_create_workout_with_nested_data(self):
        # 1. ARRANGE: Log in as Arnold
        self.client.force_authenticate(user=self.user)
        
        # Build the massive nested payload exactly as the frontend would send it
        payload = {
            "name": "Full Stack Workout",
            "description": "Testing the nested serializer via the API",
            "visibility": "private",
            "workout_exercises": [
                {
                    # Use the exercise ID from your setUp method
                    "exercise": self.bench_press.id, 
                    "order": 0,
                    "notes": "Testing nested creation",
                    "sets": [
                        {"set_number": 1, "reps": 10, "weight": 100, "weight_unit": "LBS"},
                        {"set_number": 2, "reps": 8, "weight": 110, "weight_unit": "LBS"}
                    ]
                }
            ]
        }
        
        # 2. ACT: Send it to the POST endpoint. 
        # CRITICAL: You must use format='json' so DRF parses the nested dictionaries correctly!
        response = self.client.post(self.workouts_list_url, payload, format='json')
        
        # 3. ASSERT: The View allowed it and the Serializer processed it
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # 4. ASSERT: Prove the database actually saved the nested relationships
        new_workout = Workout.objects.get(name="Full Stack Workout")
        self.assertEqual(new_workout.workout_exercises.count(), 1)
        self.assertEqual(new_workout.workout_exercises.first().sets.count(), 2)







        
        
