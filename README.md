# Church Register

## Description
A Flask web app for managing church student registration and attendance. Uses SQLite (no setup required).

## Requirements
- Python 3.10+
- The packages listed in `requirements.txt`

## Setup

1. **Install dependencies:**
   ```
   pip install -r requirements.txt
   ```

2. **Run the app:**
   ```
   python3 app.py
   ```

3. **Login credentials:**
   - Admin: `admin@church.org` / `admin123`
   - Teacher: `teacher@church.org` / `teacher123`

## Features

- Register new students with parent and contact info
- Automatic class assignment based on age
- Mark weekly attendance for each student
- Request and approve student deletions (teacher/admin roles)
- Edit student details (admin only)
- View all students by class
- Export attendance reports to Excel and PDF
- Secure login for admin and teacher roles

## Notes
- The database (`church_register.db`) is created automatically.
- No MySQL or external database

## Contributing

Contributions are welcome! To contribute:

1. Fork this repository
2. Create a new branch (`git checkout -b feature-branch`)
3. Make your changes
4. Commit and push (`git commit -am 'Add new feature'`)
5. Open a pull request

**Reporting Bugs / Requesting Features**

- Open an issue on GitHub with a clear description.
- For feature requests, describe the use case and possible implementation.
- For bugs, include steps to reproduce and any error messages.

Thank you for helping improve this project!
