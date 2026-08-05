from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.doctors.views import DoctorProfileViewSet, DoctorScheduleViewSet

router = DefaultRouter()
router.register("doctors/profiles", DoctorProfileViewSet, basename="doctorprofile")
router.register("doctors/schedules", DoctorScheduleViewSet, basename="doctorschedule")

urlpatterns = [
    path("", include(router.urls)),
]
