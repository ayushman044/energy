# Energy Materials Library (Flask)
Admin uploads PDFs; everyone else can only browse, view and download. Topics: energy storage, sensors, CO2 reduction, HER, coal gasification, rare earths, critical-mineral recycling.

## Run locally
    python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
    pip install -r requirements.txt
    cp .env.example .env     # then edit SECRET_KEY and ADMIN_PASSWORD
    python app.py            # http://127.0.0.1:5000  (admin: /admin/login)

## Deploy free on PythonAnywhere (persistent disk, so uploads are kept)
1. Create a free account at pythonanywhere.com, open a Bash console.
2. Upload this folder (zip via Files tab, then `unzip`), then:
   `cd energy-library && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
3. `cp .env.example .env` and edit it (nano .env): set SECRET_KEY and ADMIN_PASSWORD.
4. Web tab -> Add a new web app -> Manual configuration -> pick your Python version.
5. Set Virtualenv to `/home/<you>/energy-library/venv`.
6. Edit the WSGI file: replace its contents with
       import sys; sys.path.insert(0, '/home/<you>/energy-library')
       from app import app as application
7. Click Reload. Site is live at https://<you>.pythonanywhere.com

## Deploy on Render (needs paid plan for a persistent disk)
Push to GitHub, create a Blueprint from `render.yaml`, set ADMIN_PASSWORD. Without a disk, uploaded PDFs vanish on every redeploy/restart.
