from django.conf import settings
from django.db import models

# Create your models here.

class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=255)
    model_name = models.CharField(max_length=255)
    object_id = models.CharField(max_length=255, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    additional_info = models.TextField(blank=True)

    def __str__(self):
        return f"{self.timestamp} | {self.user} | {self.action} on {self.model_name}({self.object_id})"
