# Plug Backend

## Setup and Installation

### 1. Install Requirements

First, navigate to the Plug backend project directory:

```powershell
cd D:\plug\Plug_backend-main
```

Install all required Python dependencies:

```powershell
pip install -r requirements.txt
```

---

## 2. Run Database Migrations

Run the migrations for each Plug application.

### Service Providers

Navigate to:

```text
D:\plug\Plug_backend-main\api\serviceProvidersDB
```

Then run:

```powershell
python manage.py migrate
```

### Clients

Navigate to:

```text
D:\plug\Plug_backend-main\api\clientsDB
```

Then run:

```powershell
python manage.py migrate
```

### Bookings

Navigate to:

```text
D:\plug\Plug_backend-main\api\bookings
```

Then run:

```powershell
python manage.py migrate
```

---

## 3. Add Default Services

The default services can be added using the `seed_services.py` management command.

The command is located at:

```text
D:\plug\Plug_backend-main\api\serviceProvidersDB\management\commands\seed_services.py
```

From the directory containing `manage.py`, run:

```powershell
python manage.py seed_services
```

This will populate the database with the predefined services.

---

## 4. Start the Server

Start the Django development server:

```powershell
python manage.py runserver
```

The backend should then be available at:

```text
http://127.0.0.1:8000/
```

---

## 5. Start Celery

Celery is required for background tasks.

From the Plug backend directory, start the Celery worker:

```powershell
celery -A plug_backend worker --loglevel=info
```

On Windows, if required, use:

```powershell
celery -A plug_backend worker --loglevel=info --pool=solo
```

Keep the Celery worker running while using the backend.

---

## Project Setup Order

For a fresh installation, follow this order:

1. Install dependencies from `requirements.txt`
2. Run database migrations
3. Seed the default services
4. Start the Django server
5. Start Celery

### Quick Commands

```powershell
cd D:\plug\Plug_backend-main

pip install -r requirements.txt

python manage.py migrate

python manage.py seed_services

python manage.py runserver
```

In a separate terminal:

```powershell
cd D:\plug\Plug_backend-main

celery -A plug_backend worker --loglevel=info --pool=solo
```
