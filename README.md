## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python train_model.py
python app.py
```

Default logins:

- Admin: `admin` / `admin123`
- Teacher: `teacher` / `teacher123`
- Student: `student` / `student123`

Change the default passwords before deploying.

## Project structure

- `app.py`: thin Flask entry point
- `app/`: application factory, route-group blueprints, and legacy route implementation
- `database.py`: SQLite schema initialization and migrations
- `services/`: grade and prediction services
- `templates/`: Jinja2 pages
- `static/`: CSS and frontend assets
- `dataset/` and `models/`: training data and model artifacts

## Application layout

`app.py` is the production entry point and exposes the Flask application
created by `create_app()`. The factory registers six route modules:
authentication, administration, teacher/academic workflows, student
workflows, payments, and analytics.

Short endpoint aliases are registered alongside blueprint endpoints so
existing templates, redirects, and integrations keep their original names
and URL paths. The legacy route implementation remains in `app/legacy.py`
during this incremental migration.