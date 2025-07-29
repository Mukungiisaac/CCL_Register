from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import timedelta, datetime, date
import calendar
from markupsafe import Markup
from flask_sqlalchemy import SQLAlchemy
import pandas as pd
from io import BytesIO
from flask import send_file
from flask import render_template_string
from xhtml2pdf import pisa

# -------------------------------
# Flask App Config
# -------------------------------
app = Flask(__name__)
app.secret_key = "your_secret_key"
app.permanent_session_lifetime = timedelta(minutes=30)

# -------------------------------
# MySQL DB Config
# -------------------------------
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+mysqlconnector://root:password@localhost/church_register'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# -------------------------------
# Student Model (Table)
# -------------------------------
class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    dob = db.Column(db.String(20), nullable=False)
    parent = db.Column(db.String(100))
    contact = db.Column(db.String(50))
    student_class = db.Column(db.String(50))
    status = db.Column(db.String(10), default="active")
    deletion_requested = db.Column(db.Boolean, default=False)

         #Attebndance Model
class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    present = db.Column(db.Boolean, default=True)

    # Relationship (optional but powerful)
    student = db.relationship('Student', backref=db.backref('attendances', lazy=True))

# -------------------------------
# Dummy Users
# -------------------------------
users = {
    "admin@church.org": {"password": "admin123", "role": "admin"},
    "teacher@church.org": {"password": "teacher123", "role": "teacher"}
}

# -------------------------------
# Helper: Get all Sundays in a month
# -------------------------------
def get_sundays(year, month):
    sundays = []
    cal = calendar.Calendar()
    for day in cal.itermonthdates(year, month):
        if day.weekday() == 6 and day.month == month:
            sundays.append(day)
    return sundays

# -------------------------------
# Jinja Filter + Now Context
# -------------------------------
@app.template_filter('todatetime')
def to_datetime_filter(s):
    return datetime.strptime(s, "%Y-%m-%d")

@app.context_processor
def inject_now():
    return {'now': datetime.now}

# -------------------------------
# Login Page
# -------------------------------
@app.route("/")
def home():
    return render_template("login.html")

# -------------------------------
# Login Submission
# -------------------------------
@app.route("/login", methods=["POST"])
def login():
    email = request.form["email"]
    password = request.form["password"]

    if email in users and users[email]["password"] == password:
        session["user"] = email
        session["role"] = users[email]["role"]
        return redirect(url_for("dashboard"))
    else:
       flash("Invalid login", "error")
       return redirect(url_for("home"))  


# -------------------------------
# Dashboard
# -------------------------------
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user" not in session:
        return redirect(url_for("home"))

    today = date.today()
    month = int(request.args.get("month", today.month))
    year = int(request.args.get("year", today.year))
    selected_class = request.args.get("class_name")

    sundays = get_sundays(year, month)

    if selected_class:
        filtered_students = Student.query.filter_by(student_class=selected_class, status="active").all()
    else:
        filtered_students = Student.query.filter_by(status="active").all()

    return render_template("dashboard.html",
                           students=filtered_students,
                           sundays=sundays,
                           month=month,
                           year=year,
                           selected_class=selected_class)

# -------------------------------
# Add Student
# -------------------------------
@app.route("/add_student", methods=["POST"])
def add_student():
    name = request.form["name"]
    dob = request.form["dob"]
    parent = request.form.get("parent", "")
    contact = request.form.get("contact", "")

    birth = datetime.strptime(dob, "%Y-%m-%d")
    today = datetime.now()

    if birth > today:
        flash("Date of birth cannot be in the future!", "error")
        return redirect(url_for("dashboard"))

    age = (today - birth).days // 365

    if age <= 5:
        assigned_class = "Genesis"
    elif age <= 7:
        assigned_class = "Exodus"
    elif age <= 9:
        assigned_class = "Psalms"
    elif age <= 11:
        assigned_class = "Proverbs"
    elif age <= 13:
        assigned_class = "Revelation"
    else:
        assigned_class = "High Schoolers"

    student = Student(
        name=name,
        dob=dob,
        parent=parent,
        contact=contact,
        student_class=assigned_class
    )

    db.session.add(student)
    db.session.commit()

    flash("Student registered successfully!", "success")
    return redirect(url_for("dashboard"))

# -------------------------------
# Logout
# -------------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# -------------------------------
# Request Deletion (Teacher)
# -------------------------------
@app.route("/delete_request/<int:student_id>", methods=["POST"])
def mark_for_deletion(student_id):
    if session.get("role") != "teacher":
        flash("Only teachers can request deletion", "error")
        return redirect(url_for("dashboard"))

    student = Student.query.get(student_id)
    if student and student.status == "active":
        student.deletion_requested = True
        db.session.commit()
        flash("Deletion request sent to admin", "success")

    return redirect(url_for("dashboard"))

# -------------------------------
# Approve Delete (Admin)
# -------------------------------
@app.route("/approve_delete/<int:student_id>", methods=["POST"])
def approve_delete(student_id):
    if session.get("role") != "admin":
        flash("Only admins can approve deletion", "error")
        return redirect(url_for("dashboard"))

    student = Student.query.get(student_id)
    if student:
        student.status = "deleted"
        student.deletion_requested = False
        db.session.commit()
        flash("Student marked as deleted", "success")

    return redirect(url_for("dashboard"))

# -------------------------------
# Reject Delete (Admin)
# -------------------------------
@app.route("/reject_delete/<int:student_id>", methods=["POST"])
def reject_delete(student_id):
    if session.get("role") != "admin":
        flash("Only admins can reject deletion", "error")
        return redirect(url_for("dashboard"))

    student = Student.query.get(student_id)
    if student:
        student.deletion_requested = False
        db.session.commit()
        flash("Deletion request rejected", "success")

    return redirect(url_for("dashboard"))

   #ttendance Marking

@app.route("/mark_attendance", methods=["POST"])
def mark_attendance():
    if "user" not in session:
        return redirect(url_for("home"))

    student_id = request.form.get("student_id")
    date_str = request.form.get("date")
    present = request.form.get("present") == "true"

    date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()

    # Check if already marked
    record = Attendance.query.filter_by(student_id=student_id, date=date_obj).first()
    if record:
        record.present = present
    else:
        record = Attendance(student_id=student_id, date=date_obj, present=present)
        db.session.add(record)

    db.session.commit()
    return "Attendance marked", 200


@app.context_processor
def utility_functions():
    def attendance_present(student_id, sunday):
        record = Attendance.query.filter_by(student_id=student_id, date=sunday).first()
        return record.present if record else False
    return dict(attendance_present=attendance_present)


@app.route("/attendance_report")
def attendance_report():
    if "user" not in session:
        return redirect(url_for("home"))

    today = date.today()
    month = int(request.args.get("month", today.month))
    year = int(request.args.get("year", today.year))
    selected_class = request.args.get("class_name")

    sundays = get_sundays(year, month)

    # Fetch students
    if selected_class:
        students = Student.query.filter_by(student_class=selected_class, status="active").all()
    else:
        students = Student.query.filter_by(status="active").all()

    # Fetch all attendance records for this month
    all_attendance = Attendance.query.filter(
        Attendance.date.between(date(year, month, 1), date(year, month, 31))
    ).all()

    # Create quick lookup: {(student_id, date): present}
    attendance_map = {
        (a.student_id, a.date): a.present for a in all_attendance
    }

    return render_template("attendance_report.html", students=students,
                           sundays=sundays, month=month, year=year,
                           selected_class=selected_class, attendance_map=attendance_map)


@app.route("/download_attendance")
def download_attendance():
    if "user" not in session:
        return redirect(url_for("home"))

    today = date.today()
    month = int(request.args.get("month", today.month))
    year = int(request.args.get("year", today.year))
    selected_class = request.args.get("class_name")

    sundays = get_sundays(year, month)

    # Get students
    if selected_class:
        students = Student.query.filter_by(student_class=selected_class, status="active").all()
    else:
        students = Student.query.filter_by(status="active").all()

    # Attendance records
    all_attendance = Attendance.query.filter(
        Attendance.date.between(date(year, month, 1), date(year, month, 31))
    ).all()

    attendance_map = {
        (a.student_id, a.date): a.present for a in all_attendance
    }

    # Build DataFrame rows
    data = []
    for student in students:
        row = {"Name": student.name}
        for sunday in sundays:
            status = "✔" if attendance_map.get((student.id, sunday), False) else "❌"
            row[sunday.strftime('%d %b')] = status
        data.append(row)

    df = pd.DataFrame(data)

    # Export to Excel
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
     df.to_excel(writer, index=False, sheet_name='Attendance')
    output.seek(0)


    filename = f"attendance_report_{month}_{year}.xlsx"
    return send_file(output,
                     download_name=filename,
                     as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')





@app.route("/attendance_pdf")
def attendance_pdf():
    if "user" not in session:
        return redirect(url_for("home"))

    # Get data
    today = date.today()
    month = int(request.args.get("month", today.month))
    year = int(request.args.get("year", today.year))
    selected_class = request.args.get("class_name")

    sundays = get_sundays(year, month)

    if selected_class:
        students = Student.query.filter_by(student_class=selected_class, status="active").all()
    else:
        students = Student.query.filter_by(status="active").all()

    records = Attendance.query.filter(
        Attendance.date.between(date(year, month, 1), date(year, month, 31))
    ).all()

    attendance_map = {
        (a.student_id, a.date): a.present for a in records
    }

    # Render HTML
    html = render_template("attendance_pdf.html",
                           students=students,
                           sundays=sundays,
                           month=month,
                           year=year,
                           selected_class=selected_class,
                           attendance_map=attendance_map)

    # Generate PDF with xhtml2pdf
    pdf = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=pdf)
    if pisa_status.err:
        return "PDF generation error", 500

    pdf.seek(0)
    filename = f"Attendance_{selected_class or 'All'}_{month}_{year}.pdf"
    return send_file(pdf, download_name=filename, as_attachment=True)

@app.route("/edit_student/<int:student_id>", methods=["GET", "POST"])
def edit_student(student_id):
    if "user" not in session or session.get("role") != "admin":
        flash("Only admins can edit students.", "error")
        return redirect(url_for("dashboard"))

    student = Student.query.get_or_404(student_id)

    if request.method == "POST":
        student.name = request.form["name"]
        student.dob = request.form["dob"]
        student.parent = request.form.get("parent", "")
        student.contact = request.form.get("contact", "")
        student.student_class = request.form["class"]
        db.session.commit()
        flash("Student updated successfully!", "success")
        return redirect(url_for("dashboard"))

    return render_template("edit_student.html", student=student)

@app.route("/student/<int:student_id>")
def student_detail(student_id):
    if "user" not in session:
        flash("Please log in first.", "error")
        return redirect(url_for("home"))

    student = Student.query.get_or_404(student_id)
    return render_template("student_detail.html", student=student)

@app.route("/all_students")
def all_students():
    if "user" not in session:
        flash("You must be logged in to view this page.", "error")
        return redirect(url_for("home"))

    selected_class = request.args.get("class_name")
    
    class_list = ['Genesis', 'Exodus', 'Psalms', 'Proverbs', 'Revelation', 'High Schoolers']  # ✅ Make sure this is included

    if selected_class:
        students = Student.query.filter_by(status="active", student_class=selected_class).order_by(Student.name).all()
    else:
        students = Student.query.filter_by(status="active").order_by(Student.name).all()

    return render_template("all_students.html", students=students, selected_class=selected_class, class_list=class_list)

# -------------------------------
# Run App
# -------------------------------
if __name__ == "__main__":
    app.run(debug=True)
