from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.communications import views

router = DefaultRouter()
router.register("communications/messages", views.MessageViewSet, basename="communications-message")
router.register("communications/templates", views.TemplateViewSet, basename="communications-template")
router.register("communications/deliveries", views.DeliveryViewSet, basename="communications-delivery")

urlpatterns = [
    path("", include(router.urls)),
    path("communications/settings/", views.CommunicationsSettingsView.as_view(), name="communications-settings"),
    path("communications/settings/test-email/", views.test_email, name="communications-test-email"),
    path("communications/settings/test-whatsapp/", views.test_whatsapp, name="communications-test-whatsapp"),
    path("communications/webhook/whatsapp/", views.whatsapp_webhook, name="communications-whatsapp-webhook"),
]
