from django.core.management.base import BaseCommand
from django.db import transaction

from api.serviceProvidersDB.models import (
    ServiceCategory,
    ServiceGroup,
    Service,
    RiskLevel,
    ServiceCategoryID,
    ServiceCategoryName,
    ServiceKeyword,
)


class Command(BaseCommand):
    help = "Seed service categories, groups, services, keywords and enforce inherited risk levels"

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Seeding Service Categories..."))

        # NOTE: HIGH_STAKES (Security & Protection) and OTHER (Tutor/Babysitter/
        # Pet Sitter/General Labourer) categories have been removed. These
        # required verification/admin approval and were dropped to avoid
        # regulatory + liability exposure (PSIRA/Firearms Control Act for
        # armed security; unvetted care/labour services for the "Other" group).
        categories_data = [
            {
                "id": ServiceCategoryID.DOMESTIC,
                "name": ServiceCategoryName.DOMESTIC,
                "risk": RiskLevel.LOW,
                "verification": False,
                "admin": False,
            },
            {
                "id": ServiceCategoryID.PERSONAL_BODY,
                "name": ServiceCategoryName.PERSONAL_BODY,
                "risk": RiskLevel.MEDIUM,
                "verification": True,
                "admin": False,
            },
            {
                "id": ServiceCategoryID.EVENTS_MEDIA,
                "name": ServiceCategoryName.EVENTS_MEDIA,
                "risk": RiskLevel.LOW,
                "verification": False,
                "admin": False,
            },
            {
                "id": ServiceCategoryID.GENERAL,
                "name": ServiceCategoryName.GENERAL,
                "risk": RiskLevel.MEDIUM,
                "verification": False,
                "admin": False,
            },
            {
                "id": ServiceCategoryID.RESTRICTED,
                "name": ServiceCategoryName.RESTRICTED,
                "risk": RiskLevel.PROHIBITED,
                "verification": True,
                "admin": True,
            },
        ]

        category_map = {}
        for cat in categories_data:
            category, created = ServiceCategory.objects.update_or_create(
                category_id=cat["id"],
                defaults={
                    "name": cat["name"],
                    "risk_level": cat["risk"],
                    "requires_verification": cat["verification"],
                    "requires_admin_approval": cat["admin"],
                },
            )
            category_map[cat["id"]] = category
            msg = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{msg} Category: {category.name}"))

        self.stdout.write(self.style.WARNING("\nSeeding Groups & Services..."))

        # SEC001 (Security & Protection) and OTH001 (Other) groups removed.
        groups_data = [
            {
                "group_id": "BEA001",
                "name": "Beauty & Personal Care",
                "category": ServiceCategoryID.PERSONAL_BODY,
                "services": ["Makeup Technician", "Hairdresser", "Nail Technician", "Barber", "Skincare Specialist", "Tattoo Artist"],
            },
            {
                "group_id": "FOD001",
                "name": "Catering & Food",
                "category": ServiceCategoryID.EVENTS_MEDIA,
                "services": ["Private Chef", "Cake Baker", "Catering", "Spit Braai Specialist"],
            },
            {
                "group_id": "AUT001",
                "name": "Automotive Services",
                "category": ServiceCategoryID.DOMESTIC,
                "services": ["Mechanic", "Car Wash", "Auto Electrician", "Towing Service", "Tyre Specialist"],
            },
            {
                "group_id": "HOL001",
                "name": "Household Support",
                "category": ServiceCategoryID.DOMESTIC,
                # NOTE (compliance decision): "Electrician" legally requires a
                # Wireman's Licence + DoL registration to perform electrical
                # installation work / issue a Certificate of Compliance (COC).
                # "Plumber" legally requires PIRB registration specifically to
                # issue a COC for geyser/solar/gas work. Both services are kept
                # here for general tasks per decision, but COC-issuing work
                # should be excluded via Terms of Service / listing description
                # rather than the data model, since these platforms don't
                # distinguish "general repair" from "certificate-issuing work"
                # as separate services. Consider a "verified for COC work"
                # provider flag if that work needs to be offered later.
                "services": ["House Cleaner", "Laundry Helper", "Gardener", "Plumber", "Electrician", "Handyman", "Carpenter", "Painter", "Mover"],
            },
            {
                "group_id": "LOG001",
                "name": "Logistics & Transport",
                "category": ServiceCategoryID.GENERAL,
                "services": ["Runner"],
            },
            {
                "group_id": "FIT001",
                "name": "Fitness & Wellness",
                "category": ServiceCategoryID.GENERAL,
                # "Chiropractor" and "Acupuncturist" removed: AHPCSA registration
                # is legally mandatory to practise these (criminal offence
                # otherwise). "Massage Therapist" and "Nutrition" are kept per
                # decision, despite AHPCSA/HPCSA registration technically
                # applying to those titles too — flag for a verification step
                # if this changes later.
                "services": ["Personal Trainer", "Yoga Instructor", "Pilates Instructor", "Nutrition", "Massage Therapist", "Reiki Practitioner"],
            },
            {
                "group_id": "PRO001",
                "name": "Professional & Business Services",
                "category": ServiceCategoryID.GENERAL,
                "services": ["Private Tutor", "Graphic Designer", "IT Technician", "Translator", "Marketing Specialist", "Legal Consultant", "CV Writer"],
            },
            {
                "group_id": "ENT001",
                "name": "Entertainment",
                "category": ServiceCategoryID.EVENTS_MEDIA,
                "services": ["DJ", "Photographer", "Videographer", "Event Host", "Magician", "Party Planner", "Sound Technician"],
            },
        ]

        for group_data in groups_data:
            category = category_map[group_data["category"]]

            group, created = ServiceGroup.objects.update_or_create(
                group_id=group_data["group_id"],
                defaults={"name": group_data["name"], "category": category},
            )

            msg = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{msg} Group: {group.name}"))

            for service_name in group_data["services"]:
                service, created = Service.objects.get_or_create(
                    service_name=service_name.strip(),
                    service_group=group,
                    defaults={"review_status": "APPROVED"},
                )
                service.save()  # enforce inherited risk
                action = "Added" if created else "Exists"
                self.stdout.write(f"{action} Service: {service.service_name} ({service.risk_level})")

        # -----------------------------
        # PROHIBITED KEYWORDS
        # -----------------------------
        self.stdout.write(self.style.WARNING("\nSeeding Prohibited Keywords..."))
        prohibited_keywords = [
            # adult/illegal/prohibited terms...
            "escort", "prostitute", "prostitution", "sexual service", "sex worker", "happy ending", "erotic massage", "sex", "porn", "nudes",
            "intimate service", "adult service", "sensual massage", "adult entertainment", "sex work", "porn service",
            "xxx service", "weed", "marijuana", "cannabis", "coke", "cocaine", "heroin", "meth", "methamphetamine", "drug delivery",
            "narcotics", "ecstasy", "lsd", "opioid", "illegal drugs", "pill selling", "isibhamu", "gun for hire", "illegal firearm", "weapon sale",
            "gun sale", "arms trade", "firearm trafficking", "inkabi", "killer", "kill people", "hitman", "fake id", "forged documents",
            "identity fraud", "scam service", "phishing", "credit card fraud", "counterfeit", "imitation documents", "fake passport", "fraudulent service", "hacking service", "cybercrime", "illegal software",
            "pirated software", "smuggling", "indunu", "umdidi", "ingquza", "inquza", "only fans", "only-fans", "thengisa ingquza",
            "ngithengisa ingquza", "thengisa inquza", "ngithengisa inquza", "ngithengisa umdidi", "isitho", "isitho esingaseze",
            "hookup", "strip club", "lap dance", "webcam service", "camgirl", "sugar daddy", "sugar baby", "blesser", "blessee",
            "adult chat", "massage parlor", "body to body", "B2B massage", "nude photos", "send nudes", "sexting", "ukudayisa umzimba",
            "thengisa umzimba", "ukuphinga", "dagga", "nyaope", "wunga", "crystal tik", "tik", "rock cocaine", "crack", "shrooms", "magic mushrooms", "lsd tabs", "xanax", "codeine syrup",
            "lean drink", "tramadol", "abortion pills", "cytotec", "mizoprostol", "zaza", "hubbly flavors nicotine",
            "assassination", "contract killer", "ukubulala", "idubula", "ukushaya", "hostage", "kidnapping", "protection money",
            "extortion", "debt collection force", "hijacking", "stolen goods", "hot property", "izimoto ezitshontshiwe",
            "money laundering", "wash wash", "black dollars", "ssd solution", "cloned cards", "carding", "money mule",
            "pyramid scheme", "ponzi", "invest and get double",
            "binary options trading", "forex signals scam", "bitcoin doubler", "account hacking", "bank login", "stolen id",
            "social engineering", "human organs", "kidney sale", "ivory", "rhino horn", "imfezi", "muthi for luck",
            "bring back lost lover", "get rich quick muthi", "traditional healer luck", "penis enlargement", "hips and bum cream",

            # Removed services (previously required compliance/verification/
            # admin approval) — Security & Protection and "Other" groups
            "armed guard", "bodyguard", "security system installer", "private investigator",
            "tutor", "babysitter", "pet sitter", "general labourer",

            # Removed services — mandatory AHPCSA registration required to
            # legally practise; unregistered practice is a criminal offence
            "chiropractor", "acupuncturist",
        ]

        for word in prohibited_keywords:
            obj, created = ServiceKeyword.objects.get_or_create(
                keyword=word.lower().strip(),
                defaults={"service": None, "is_prohibited": True, "risk_level": RiskLevel.PROHIBITED},
            )
            if created:
                self.stdout.write(f"\U0001F6AB Prohibited keyword added: {word}")

        # -----------------------------
        # CLEANUP: REMOVE PROHIBITED SERVICES STILL IN DB
        # -----------------------------
        # Older runs of this script (or manual entries) may have created
        # Service rows for things that are now prohibited (e.g. Armed Guard,
        # Chiropractor). Removing a service from groups_data above does NOT
        # delete it from an existing database — this pass finds and removes
        # any Service whose name exactly matches a prohibited keyword, then
        # removes any ServiceGroup/ServiceCategory left with nothing in it.
        self.stdout.write(self.style.WARNING("\nRemoving prohibited services still present in the database..."))
        prohibited_set = {word.lower().strip() for word in prohibited_keywords}

        affected_groups = set()
        removed_count = 0
        for service in list(Service.objects.all()):
            if service.service_name.lower().strip() in prohibited_set:
                self.stdout.write(
                    self.style.ERROR(f"\U0001F5D1 Deleting prohibited service found in DB: {service.service_name}")
                )
                affected_groups.add(service.service_group_id)
                service.delete()
                removed_count += 1

        if removed_count:
            self.stdout.write(self.style.SUCCESS(f"Removed {removed_count} prohibited service(s) from the database."))
        else:
            self.stdout.write("No prohibited services found in the database.")

        # Remove any groups that are now empty (no services left)
        affected_categories = set()
        for group_id in affected_groups:
            if group_id is None:
                continue
            group = ServiceGroup.objects.filter(pk=group_id).first()
            if group and not Service.objects.filter(service_group=group).exists():
                self.stdout.write(self.style.ERROR(f"\U0001F5D1 Deleting now-empty group: {group.name}"))
                affected_categories.add(group.category_id)
                group.delete()

        # Remove any categories that are now empty (no groups left)
        for category_id in affected_categories:
            if category_id is None:
                continue
            category = ServiceCategory.objects.filter(pk=category_id).first()
            if category and not ServiceGroup.objects.filter(category=category).exists():
                self.stdout.write(self.style.ERROR(f"\U0001F5D1 Deleting now-empty category: {category.name}"))
                category.delete()

        # -----------------------------
        # SERVICE SYNONYMS
        # -----------------------------
        self.stdout.write(self.style.WARNING("\nSeeding Service Synonyms..."))
        # NOTE: "Armed Guard", "Bodyguard", "Security System Installer" and
        # "Babysitter" synonym entries removed along with their services.
        service_synonyms = {
            "House Cleaner": ["maid", "cleaner", "domestic worker", "housekeeping", "cleaning service"],
            "Hairdresser": ["hairstylist", "hair stylist", "barber", "hair salon", "hair treatment"],
            "Makeup Technician": ["makeup artist", "mua", "beauty artist", "bridal makeup", "special effects makeup"],
            "DJ": ["disc jockey", "music dj", "deejay", "event dj"],
            "Nail Technician": ["nail tech", "manicurist", "pedicurist", "nail salon"],
            "Plumber": ["pipe repair", "plumbing service", "leak repair", "drain cleaning"],
            "Electrician": ["electrical repair", "wiring", "circuit repair", "electrical maintenance"],
            "Gardener": ["landscaper", "yard work", "lawn care", "garden maintenance"],
            "Painter": ["house painter", "wall painting", "interior painter", "exterior painter"],
            "Private Tutor": ["teacher", "private lessons", "academic support", "tutor", "coaching"],
            "Graphic Designer": ["logo design", "branding", "digital artist", "illustrator"],
            "IT Technician": ["computer repair", "tech support", "pc doctor", "network setup"],
            "Accountant": ["bookkeeper", "tax consultant", "auditor", "financial advisor"],
            "Translator": ["language service", "interpreting", "document translation"],
            "Marketing Specialist": ["social media manager", "digital marketing", "seo expert", "content creator"],
            "Personal Trainer": ["fitness coach", "gym instructor", "workout partner", "personal training"],
            "Massage Therapist": ["massage", "spa", "deep tissue", "reflexology"],
        }

        for service_name, keywords in service_synonyms.items():
            service = Service.objects.filter(service_name__iexact=service_name).first()
            if not service:
                self.stdout.write(self.style.WARNING(f"\u26A0 Service not found: {service_name}"))
                continue

            for word in keywords:
                obj, created = ServiceKeyword.objects.get_or_create(
                    keyword=word.lower().strip(),
                    defaults={"service": service, "is_prohibited": False, "risk_level": service.risk_level},
                )
                if created:
                    self.stdout.write(f"+ Synonym added: {word} \u2192 {service.service_name}")

        self.stdout.write(self.style.SUCCESS("\nAll categories, groups, services, and keywords seeded successfully!"))