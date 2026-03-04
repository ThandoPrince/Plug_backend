from django.db import models

class RiskLevel(models.TextChoices):
    LOW = "LOW", "Low Risk"
    MEDIUM = "MEDIUM", "Medium Risk"
    HIGH = "HIGH", "High Risk"
    PROHIBITED = "PROHIBITED", "Prohibited"


class ServiceCategoryID(models.TextChoices):
    DOMESTIC = "CAT001"
    PERSONAL_BODY = "CAT002"
    EVENTS_MEDIA = "CAT003"
    GENERAL = "CAT004"
    OTHER = "CAT005"
    HIGH_STAKES = "CAT006"  # Added this
    RESTRICTED = "CAT999"

class ServiceCategoryName(models.TextChoices):
    DOMESTIC = "Domestic Services"
    PERSONAL_BODY = "Personal & Body Services"
    EVENTS_MEDIA = "Events & Media"
    GENERAL = "General Services"
    OTHER = "Other"
    HIGH_STAKES = "High Risk & Specialized" # Added this
    RESTRICTED = "Restricted / Regulated"