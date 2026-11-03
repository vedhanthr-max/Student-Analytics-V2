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

- `app.py`: Flask routes and application startup
- `database.py`: SQLite schema initialization and migrations
- `services/`: grade and prediction services
- `templates/`: Jinja2 pages
- `static/`: CSS and frontend assets
- `dataset/` and `models/`: training data and model artifacts