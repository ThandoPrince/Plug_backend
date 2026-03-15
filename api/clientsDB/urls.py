from django.conf import settings
from django.http import JsonResponse
import os

def media_debug(request):
    rel = "client_profile_pics/modern-male-avatar-with-black-hair-and-hoodie-illustration-free-png.png"
    full = os.path.join(settings.MEDIA_ROOT, rel)
    return JsonResponse({
        "MEDIA_ROOT": str(settings.MEDIA_ROOT),
        "exists": os.path.exists(full),
        "full_path": full,
    })