from django.core.management.base import BaseCommand
from django.db import transaction
from api.serviceProvidersDB.models import ServiceGroup, Service


class Command(BaseCommand):
    help = 'Seed initial service groups and services with predefined group_ids'

    def handle(self, *args, **options):
        service_groups = [
            {
                'group_id': 'BEA001',
                'name': 'Beauty & Personal Care',
                'services': [
                    {'service_name': 'Makeup Technician'},
                    {'service_name': 'Hairdresser'},
                    {'service_name': 'Nail Technician'},
                    {'service_name': 'Barber'},
                    {'service_name': 'Skincare Specialist'},
                    {'service_name': 'Tattoo Artist'},
                    {'service_name': 'Pest Control'},
                    
                ]
            },
            {
                'group_id': 'HOL001',
                'name': 'Household Support',
                'services': [
                    {'service_name': 'House Cleaner'},
                    {'service_name': 'Laundry Helper'},
                    {'service_name': 'Gardener'},
                    {'service_name': 'Car-wash'},
                    {'service_name': 'Plumber'},
                    {'service_name': 'Electrician'},
                    {'service_name': 'Pest Control'},
                    {'service_name': 'Handyman'},
                    {'service_name': 'Carpenter'},
                    {'service_name': 'Painter'},
                    {'service_name': 'Mover'},

                ]
            },
            {
                'group_id': 'OTH001',
                'name': 'Other Services',
                'services': [
                    {'service_name': 'Tutor'},
                    {'service_name': 'Driver'},
                    {'service_name': 'Babysitter'},
                    {'service_name': 'Pet Sitter'},
                    {'service_name': 'General Labourer'},
                    {'service_name': 'Security Guard'},
                ]
            },


            {
                'group_id': 'ENT001',
                'name': 'Entertainment',
                'services': [
   
                    {'service_name': 'DJ'},
                    {'service_name': 'Photographer'},
                    {'service_name': 'Videographer'},
                    {'service_name': 'Event Host'},   
                    {'service_name': 'Magician'},
                    {'service_name': 'Party Planner'},
                    {'service_name': 'Sound Technician'},         

                ]
            },

            {
                'group_id': 'FIT001',
                'name': 'Fitness & Wellness',
                'services': [
                    {'service_name': 'Personal Trainer'},
                    {'service_name': 'Yoga Instructor'},
                    {'service_name': 'Pilates Instructor'},
                    {'service_name': 'Nutrition'},
                    {'service_name': 'Massage Therapist'},
                    {'service_name': 'Chiropractor'},
                    {'service_name': 'Acupuncturist'},
                    {'service_name': 'Reiki Practitioner'},
                
  
            

        ]
            }
        ]

        with transaction.atomic():
            for group_data in service_groups:
                group_id = group_data['group_id']
                name = group_data['name']
                services = group_data['services']

                # First, try get by group_id
                group = ServiceGroup.objects.filter(group_id=group_id).first()

                if group:
                    if group.name != name:
                        # Check if another group already has this name
                        name_conflict = ServiceGroup.objects.filter(name=name).exclude(group_id=group_id).exists()
                        if name_conflict:
                            self.stdout.write(self.style.ERROR(
                                f"❌ Conflict: Name '{name}' is used by another group. Skipping group_id: {group_id}"
                            ))
                            continue
                        group.name = name
                        group.save()
                        self.stdout.write(self.style.SUCCESS(f"🔄 Updated name of group {group_id} to {name}"))
                    else:
                        self.stdout.write(self.style.WARNING(f"⚠️ Group already exists: {name} ({group_id})"))
                else:
                    # Check if name exists under another group_id
                    existing_by_name = ServiceGroup.objects.filter(name=name).first()
                    if existing_by_name:
                        self.stdout.write(self.style.ERROR(
                            f"❌ Conflict: Group name '{name}' already exists with different ID ({existing_by_name.group_id}). Skipping."
                        ))
                        continue
                    group = ServiceGroup.objects.create(group_id=group_id, name=name)
                    self.stdout.write(self.style.SUCCESS(f"🆕 Created group: {name} ({group_id})"))

                # Process services
                for service_data in services:
                    service_name = service_data['service_name'].strip().title()
                   

                    service, service_created = Service.objects.get_or_create(
                        service_name=service_name,
                        service_group=group,
                       
                    )

                    if service_created:
                        self.stdout.write(f"   ✅ Added service: {service_name}")
                    else:
                        updated = False

                        msg = "🔁 Service already exists"
                       
                        self.stdout.write(f"   {msg}: {service_name} (ID: {service.pk})")

        self.stdout.write(self.style.SUCCESS('\n✅ All service groups and services seeded successfully!'))
