# Student Analytics V2

A Flask-based student academic management and analytics system with role-based access for **Admin, Teacher, and Student** users.

## Features

- Separate Admin, Teacher, and Student login pages
- Role-based route protection
- Student profile and academic summary
- Semester-wise results, GPA and arrear tracking
- Teacher-managed student records and results
- Subject and exam registration management
- Hall-ticket generation with fee/registration checks
- Student fee view and temporary direct UPI payment intent
- Payment history and admin fee summaries
- K-Means based student performance clustering
- Performance recommendations
- SQLite database

## Tech Stack

- Python 3.12+
- Flask
- SQLite
- Pandas / NumPy
- Scikit-learn
- Joblib
- HTML/CSS/JavaScript

## Project Structure

```text
Student_Analytics_V2/
├── app.py
├── config.py
├── database.py
├── recommendation.py
├── train_model.py
├── payment.py
├── auth.py
├── requirements.txt
├── .env.example
├── dataset/
├── models/
├── services/
├── utils/
├── templates/
└── static/
```

## Setup

### 1. Clone the repository

```bash
git clone <your-repository-url>
cd Student_Analytics_V2
```

### 2. Create a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env` and set your own values. The application reads environment variables directly; it does not require committing a `.env` file.

For PowerShell, for example:

```powershell
$env:SECRET_KEY="replace-with-a-long-random-secret"
$env:ADMIN_PASSWORD="your-admin-password"
$env:TEACHER_PASSWORD="your-teacher-password"
$env:STUDENT_PASSWORD="your-student-password"
$env:UPI_ID="your-upi-id@example"
$env:UPI_NUMBER="your-payment-number"
$env:UPI_PAYEE="Your Name"
```

### 5. Initialize the database

```powershell
python database.py
```

The database is intentionally ignored by Git so local/user data is not published.

### 6. Run the application

```powershell
python app.py
```

Open the local Flask URL shown in the terminal.

## ML Model

The project includes the trained K-Means model and scaler under `models/`. If those artifacts are removed, regenerate them with:

```powershell
python train_model.py
```

## Payment Note

The current project uses a **temporary direct UPI intent**. The amount is read server-side from the outstanding balance. Opening a UPI intent does **not** mark a payment as successful; bank-side confirmation/gateway verification is required before a payment should be recorded as paid.

For production payments, integrate a supported payment gateway and verify callbacks/signatures server-side.

## Security Notes

- Never commit `.env` or real payment credentials.
- Never commit a local SQLite database containing personal/student data.
- Use a strong random `SECRET_KEY` in deployment.
- Keep `FLASK_DEBUG=0` in production.
- Use HTTPS and a production WSGI server for deployment.

## Future Enhancements

- Production payment-gateway integration with server-side verification
- Password reset/recovery flow with secure identity verification
- CSRF protection for state-changing forms
- Production deployment configuration
- Automated unit and integration test suite

## License

Add the license that matches your intended use before publishing.
