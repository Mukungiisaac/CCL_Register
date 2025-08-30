from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from datetime import timedelta, datetime, date
import calendar
from flask_sqlalchemy import SQLAlchemy
import pandas as pd
from io import BytesIO
from xhtml2pdf import pisa
import os
from werkzeug.utils import secure_filename
from PIL import Image

# -------------------------------
# Flask App Config
# -------------------------------
app = Flask(__name__)
app.secret_key = "your_secret_key"
app.permanent_session_lifetime = timedelta(minutes=30)

# -------------------------------
# MySQL DB Config
# -------------------------------
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///church_register.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Image upload configuration
UPLOAD_FOLDER = 'static/uploads/profiles'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create upload directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def resize_image(image_path, max_size=(200, 200)):
    """Resize image to max_size while maintaining aspect ratio"""
    try:
        with Image.open(image_path) as img:
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            img.save(image_path, optimize=True, quality=85)
    except Exception as e:
        print(f"Error resizing image: {e}")

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
    profile_image = db.Column(db.String(200))  # Store image filename
    family_id = db.Column(db.String(50))  # For grouping family members

         #Attebndance Model
class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    present = db.Column(db.Boolean, default=True)

    # Relationship (optional but powerful)
    student = db.relationship('Student', backref=db.backref('attendances', lazy=True))

# -------------------------------
# Inventory Model (Table)
# -------------------------------
class Inventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    description = db.Column(db.String(200))
    date_added = db.Column(db.DateTime, default=datetime.now)
    last_checked = db.Column(db.DateTime, default=datetime.now)
    notes = db.Column(db.Text)  # For missing items explanations

class InventoryAudit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)  # 'added', 'deleted', 'found', 'missing'
    date = db.Column(db.DateTime, default=datetime.now)
    user = db.Column(db.String(100))
    notes = db.Column(db.Text)

    # Relationship
    item = db.relationship('Inventory', backref=db.backref('audit_logs', lazy=True))

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

    # Find the current Sunday (today if it's Sunday, or the most recent Sunday)
    current_sunday = None
    if today.weekday() == 6:  # Today is Sunday
        current_sunday = today
    else:
        # Find the most recent Sunday in the current month's Sundays
        for sunday in reversed(sundays):
            if sunday <= today:
                current_sunday = sunday
                break

    # If no current Sunday found in this month, use today's date
    if current_sunday is None:
        current_sunday = today

    if selected_class:
        filtered_students = Student.query.filter_by(student_class=selected_class, status="active").all()
    else:
        filtered_students = Student.query.filter_by(status="active").all()

    # Check for students at risk of deactivation (for admin notification)
    at_risk_count = 0
    if session.get("role") == "admin":
        # Get the last 4 Sundays for at-risk check
        today = datetime.now()
        check_sundays = []
        current_date = today

        for _ in range(4):
            days_back = (current_date.weekday() + 1) % 7
            if days_back == 0 and current_date.date() == today.date():
                days_back = 7

            sunday = current_date - timedelta(days=days_back)
            check_sundays.append(sunday.date())
            current_date = sunday - timedelta(days=1)

        # Count students at risk (all active students, not just filtered)
        all_active_students = Student.query.filter_by(status='active').all()
        for student in all_active_students:
            missed_count = 0
            for sunday in check_sundays:
                attendance = Attendance.query.filter_by(student_id=student.id, date=sunday).first()
                if not attendance or not attendance.present:
                    missed_count += 1

            if missed_count >= 3:  # At risk if missed 3+ Sundays
                at_risk_count += 1

    return render_template("dashboard.html",
                           students=filtered_students,
                           sundays=sundays,
                           month=month,
                           year=year,
                           selected_class=selected_class,
                           current_sunday=current_sunday,
                           at_risk_count=at_risk_count)

# -------------------------------
# Add Student
# -------------------------------
@app.route("/add_student", methods=["POST"])
def add_student():
    name = request.form["name"]
    dob = request.form["dob"]
    parent = request.form.get("parent", "")
    contact = request.form.get("contact", "")
    family_id = request.form.get("family_id", "")

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

    # Handle profile image upload
    profile_image_filename = None
    if 'profile_image' in request.files:
        file = request.files['profile_image']
        if file and file.filename != '' and allowed_file(file.filename):
            # Create unique filename
            timestamp = int(datetime.now().timestamp())
            filename = secure_filename(f"{timestamp}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            try:
                file.save(filepath)
                # Resize image to save space
                resize_image(filepath)
                profile_image_filename = filename
            except Exception as e:
                flash(f"Error uploading image: {str(e)}", "warning")

    student = Student(
        name=name,
        dob=dob,
        parent=parent,
        contact=contact,
        student_class=assigned_class,
        profile_image=profile_image_filename,
        family_id=family_id if family_id else None
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

@app.route('/get_student/<int:student_id>')
def get_student(student_id):
    if "user" not in session:
        return {"error": "Unauthorized"}, 401

    student = Student.query.get_or_404(student_id)
    return {
        "id": student.id,
        "name": student.name,
        "dob": student.dob,
        "parent": student.parent,
        "contact": student.contact,
        "student_class": student.student_class,
        "family_id": student.family_id,
        "profile_image": student.profile_image
    }

@app.route('/edit_student', methods=['POST'])
def edit_student():
    if not session.get("role") == "admin":
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard"))

    student_id = request.form.get("student_id")
    student = Student.query.get_or_404(student_id)

    # Update basic info
    student.name = request.form.get("name")
    student.dob = request.form.get("dob")
    student.parent = request.form.get("parent", "")
    student.contact = request.form.get("contact", "")
    student.family_id = request.form.get("family_id", "") or None

    # Handle profile image update
    if 'profile_image' in request.files:
        file = request.files['profile_image']
        if file and file.filename != '' and allowed_file(file.filename):
            # Delete old image if exists
            if student.profile_image:
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], student.profile_image)
                if os.path.exists(old_path):
                    os.remove(old_path)

            # Save new image
            timestamp = int(datetime.now().timestamp())
            filename = secure_filename(f"{timestamp}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            try:
                file.save(filepath)
                resize_image(filepath)
                student.profile_image = filename
            except Exception as e:
                flash(f"Error uploading image: {str(e)}", "warning")

    # Recalculate class based on age
    birth = datetime.strptime(student.dob, "%Y-%m-%d")
    today = datetime.now()
    age = (today - birth).days // 365

    if age <= 5:
        student.student_class = "Genesis"
    elif age <= 7:
        student.student_class = "Exodus"
    elif age <= 9:
        student.student_class = "Psalms"
    elif age <= 11:
        student.student_class = "Proverbs"
    elif age <= 13:
        student.student_class = "Revelation"
    else:
        student.student_class = "High Schoolers"

    db.session.commit()
    flash(f"Student '{student.name}' updated successfully!", "success")
    return redirect(url_for("dashboard"))

@app.route("/student/<int:student_id>")
def student_detail(student_id):
    if "user" not in session:
        flash("Please log in first.", "error")
        return redirect(url_for("home"))

    student = Student.query.get_or_404(student_id)

    # Calculate age
    from datetime import datetime
    birth_date = datetime.strptime(student.dob, "%Y-%m-%d")
    today = datetime.now()
    age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

    # Format date for display
    formatted_date = birth_date.strftime("%B %d, %Y")

    return render_template("student_detail.html",
                         student=student,
                         age=age,
                         formatted_date=formatted_date)

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

@app.route('/inventory')
def inventory():
    if not session.get("role") == "admin":
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard"))

    items = Inventory.query.all()

    # Get all unique categories dynamically
    categories = set()
    for item in items:
        if item.description and " - QR: " in item.description:
            category = item.description.split(" - QR: ")[0]
            # Skip placeholder items when showing categories
            if not item.item_name.endswith(" Placeholder"):
                categories.add(category)

    # Organize items by category
    all_items = items
    items_by_category = {}

    for category in categories:
        items_by_category[category] = [
            item for item in items
            if item.description and item.description.startswith(category + " - QR: ")
        ]

    return render_template("inventory.html",
                         all_items=all_items,
                         categories=sorted(categories),
                         items_by_category=items_by_category)

@app.route('/add_item', methods=['POST'])
def add_item():
    if not session.get("role") == "admin":
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard"))

    name = request.form.get("name")
    item_type = request.form.get("type")
    custom_type = request.form.get("custom_type")
    qr_code = request.form.get("qr_code")

    # Use custom type if selected
    if item_type == "Custom" and custom_type:
        item_type = custom_type.strip()

    if name and item_type:
        # If no QR code provided, generate a unique one
        if not qr_code or qr_code.strip() == "":
            import time
            import random
            timestamp = int(time.time())
            random_num = random.randint(100, 999)
            qr_code = f"AUTO_{timestamp}_{random_num}"

        # Check if QR code already exists
        existing_item = Inventory.query.filter(
            Inventory.description.like(f"%QR: {qr_code}%")
        ).first()

        if existing_item:
            flash(f"Item with QR code '{qr_code}' already exists!", "error")
            return redirect(url_for("inventory"))

        # Create new inventory item
        new_item = Inventory(
            item_name=name,
            quantity=1,
            description=f"{item_type} - QR: {qr_code}",
            date_added=datetime.now(),
            last_checked=datetime.now()
        )

        db.session.add(new_item)
        db.session.commit()

        # Log the action
        audit_log = InventoryAudit(
            item_id=new_item.id,
            action='added',
            user=session.get('user', 'Unknown'),
            notes=f"Item added via {'QR scan' if not qr_code.startswith('AUTO_') else 'manual entry'}"
        )
        db.session.add(audit_log)
        db.session.commit()

        if qr_code.startswith("AUTO_"):
            flash(f"Item '{name}' added successfully with auto-generated ID: {qr_code}!", "success")
        else:
            flash(f"Item '{name}' added successfully with QR code: {qr_code}!", "success")
    else:
        flash("Item name and type are required!", "error")

    return redirect(url_for("inventory"))

@app.route('/delete_item/<int:item_id>', methods=['POST'])
def delete_item(item_id):
    if not session.get("role") == "admin":
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard"))

    item = Inventory.query.get_or_404(item_id)
    item_name = item.item_name

    try:
        # Log the deletion before deleting
        audit_log = InventoryAudit(
            item_id=item.id,
            action='deleted',
            user=session.get('user', 'Unknown'),
            notes=f"Item '{item_name}' deleted by admin"
        )
        db.session.add(audit_log)

        db.session.delete(item)
        db.session.commit()
        flash(f"Item '{item_name}' deleted successfully!", "success")
    except Exception as e:
        flash(f"Error deleting item: {str(e)}", "error")

    return redirect(url_for("inventory"))

@app.route('/add_category', methods=['POST'])
def add_category():
    if not session.get("role") == "admin":
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard"))

    category_name = request.form.get("category_name", "").strip()

    if not category_name:
        flash("Category name is required!", "error")
        return redirect(url_for("inventory"))

    # Create a placeholder item for the new category to make the tab appear
    placeholder_item = Inventory(
        item_name=f"{category_name} Placeholder",
        quantity=0,
        description=f"{category_name} - QR: PLACEHOLDER_{int(datetime.now().timestamp())}",
        date_added=datetime.now(),
        last_checked=datetime.now(),
        notes="Placeholder item to create category tab. Add real items to this category."
    )

    db.session.add(placeholder_item)
    db.session.commit()

    flash(f"Category '{category_name}' added successfully! You can now add items to this category.", "success")
    return redirect(url_for("inventory"))

@app.route('/promote_students', methods=['GET', 'POST'])
def promote_students():
    if not session.get("role") == "admin":
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == 'POST':
        promotion_type = request.form.get('promotion_type')

        if promotion_type == 'automatic':
            # Automatic promotion based on age
            students = Student.query.filter_by(status='active').all()
            promoted_count = 0

            for student in students:
                birth_date = datetime.strptime(student.dob, "%Y-%m-%d")
                today = datetime.now()
                age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

                # Determine correct class based on current age
                if age <= 5:
                    new_class = "Genesis"
                elif age <= 7:
                    new_class = "Exodus"
                elif age <= 9:
                    new_class = "Psalms"
                elif age <= 11:
                    new_class = "Proverbs"
                elif age <= 13:
                    new_class = "Revelation"
                else:
                    new_class = "High Schoolers"

                # Only update if class needs to change
                if student.student_class != new_class:
                    old_class = student.student_class
                    student.student_class = new_class
                    promoted_count += 1

                    # Log the promotion
                    print(f"Promoted {student.name} from {old_class} to {new_class} (Age: {age})")

            db.session.commit()
            flash(f"Successfully promoted {promoted_count} students to age-appropriate classes!", "success")

        elif promotion_type == 'manual':
            # Manual promotion for selected students
            selected_students = request.form.getlist('student_ids')
            new_class = request.form.get('new_class')

            if not selected_students or not new_class:
                flash("Please select students and a target class.", "error")
                return redirect(url_for('promote_students'))

            promoted_count = 0
            for student_id in selected_students:
                student = Student.query.get(student_id)
                if student:
                    old_class = student.student_class
                    student.student_class = new_class
                    promoted_count += 1
                    print(f"Manually moved {student.name} from {old_class} to {new_class}")

            db.session.commit()
            flash(f"Successfully moved {promoted_count} students to {new_class}!", "success")

        return redirect(url_for('promote_students'))

    # GET request - show promotion interface
    students = Student.query.filter_by(status='active').all()

    # Calculate age and suggested class for each student
    student_data = []
    for student in students:
        birth_date = datetime.strptime(student.dob, "%Y-%m-%d")
        today = datetime.now()
        age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

        # Determine suggested class based on age
        if age <= 5:
            suggested_class = "Genesis"
        elif age <= 7:
            suggested_class = "Exodus"
        elif age <= 9:
            suggested_class = "Psalms"
        elif age <= 11:
            suggested_class = "Proverbs"
        elif age <= 13:
            suggested_class = "Revelation"
        else:
            suggested_class = "High Schoolers"

        needs_promotion = student.student_class != suggested_class

        student_data.append({
            'student': student,
            'age': age,
            'current_class': student.student_class,
            'suggested_class': suggested_class,
            'needs_promotion': needs_promotion
        })

    # Sort by those needing promotion first
    student_data.sort(key=lambda x: (not x['needs_promotion'], x['student'].name))

    classes = ["Genesis", "Exodus", "Psalms", "Proverbs", "Revelation", "High Schoolers"]

    return render_template("promote_students.html",
                         student_data=student_data,
                         classes=classes)

@app.route('/manage_status', methods=['GET', 'POST'])
def manage_status():
    if not session.get("role") == "admin":
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == 'POST':
        action = request.form.get('action')
        selected_students = request.form.getlist('student_ids')

        if not selected_students:
            flash("Please select at least one student.", "error")
            return redirect(url_for('manage_status'))

        updated_count = 0
        for student_id in selected_students:
            student = Student.query.get(student_id)
            if student:
                if action == 'activate':
                    student.status = 'active'
                elif action == 'deactivate':
                    student.status = 'inactive'
                updated_count += 1

        db.session.commit()
        status_text = "activated" if action == 'activate' else "deactivated"
        flash(f"Successfully {status_text} {updated_count} students!", "success")

        return redirect(url_for('manage_status'))

    # GET request - show status management interface
    students = Student.query.all()
    active_students = [s for s in students if s.status == 'active']
    inactive_students = [s for s in students if s.status == 'inactive']

    return render_template("manage_status.html",
                         active_students=active_students,
                         inactive_students=inactive_students)

@app.route('/check_attendance_deactivation', methods=['POST'])
def check_attendance_deactivation():
    if not session.get("role") == "admin":
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard"))

    # Get the last 4 Sundays
    today = datetime.now()
    sundays = []
    current_date = today

    # Find the last 4 Sundays
    for _ in range(4):
        # Go back to find the most recent Sunday
        days_back = (current_date.weekday() + 1) % 7
        if days_back == 0 and current_date.date() == today.date():
            days_back = 7  # If today is Sunday, go back to previous Sunday

        sunday = current_date - timedelta(days=days_back)
        sundays.append(sunday.date())
        current_date = sunday - timedelta(days=1)  # Move to day before this Sunday

    # Get all active students
    active_students = Student.query.filter_by(status='active').all()
    deactivated_count = 0
    deactivated_students = []

    for student in active_students:
        # Check attendance for the last 4 Sundays
        missed_count = 0
        attendance_details = []

        for sunday in sundays:
            attendance = Attendance.query.filter_by(
                student_id=student.id,
                date=sunday
            ).first()

            if not attendance or not attendance.present:
                missed_count += 1
                attendance_details.append(f"{sunday.strftime('%m/%d/%Y')}: Absent")
            else:
                attendance_details.append(f"{sunday.strftime('%m/%d/%Y')}: Present")

        # If student missed all 4 Sundays, deactivate them
        if missed_count >= 4:
            student.status = 'inactive'
            deactivated_count += 1
            deactivated_students.append({
                'name': student.name,
                'class': student.student_class,
                'attendance': attendance_details
            })

            print(f"Auto-deactivated {student.name} for missing {missed_count}/4 Sundays")

    db.session.commit()

    if deactivated_count > 0:
        flash(f"Automatically deactivated {deactivated_count} students for missing 4+ consecutive Sundays. They can be reactivated when they return.", "warning")

        # Log the deactivations for admin review
        for student_info in deactivated_students:
            print(f"DEACTIVATED: {student_info['name']} ({student_info['class']})")
            for attendance_line in student_info['attendance']:
                print(f"  - {attendance_line}")
    else:
        flash("No students needed automatic deactivation based on attendance.", "info")

    return redirect(url_for("manage_status"))

@app.route('/auto_attendance_check')
def auto_attendance_check():
    """Automatic check that can be called periodically"""
    if not session.get("role") == "admin":
        return {"error": "Access denied"}, 403

    # Get the last 4 Sundays
    today = datetime.now()
    sundays = []
    current_date = today

    for _ in range(4):
        days_back = (current_date.weekday() + 1) % 7
        if days_back == 0 and current_date.date() == today.date():
            days_back = 7

        sunday = current_date - timedelta(days=days_back)
        sundays.append(sunday.date())
        current_date = sunday - timedelta(days=1)

    active_students = Student.query.filter_by(status='active').all()
    students_at_risk = []

    for student in active_students:
        missed_count = 0
        recent_attendance = []

        for sunday in sundays:
            attendance = Attendance.query.filter_by(
                student_id=student.id,
                date=sunday
            ).first()

            if not attendance or not attendance.present:
                missed_count += 1
                recent_attendance.append({"date": sunday.strftime('%m/%d'), "present": False})
            else:
                recent_attendance.append({"date": sunday.strftime('%m/%d'), "present": True})

        if missed_count >= 3:  # At risk if missed 3+ (will be deactivated at 4)
            students_at_risk.append({
                'id': student.id,
                'name': student.name,
                'class': student.student_class,
                'missed_count': missed_count,
                'attendance': recent_attendance,
                'will_deactivate': missed_count >= 4
            })

    return {
        'students_at_risk': students_at_risk,
        'total_at_risk': len(students_at_risk)
    }

@app.route('/generate_report')
def generate_report():
    if not session.get("role") == "admin":
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard"))

    items = Inventory.query.all()
    total_items = len(items)
    available_items = len([item for item in items if item.quantity > 0])
    missing_items = total_items - available_items

    report_data = {
        'total_items': total_items,
        'available_items': available_items,
        'missing_items': missing_items,
        'items': items
    }

    flash(f"Report generated: {available_items} available, {missing_items} missing out of {total_items} total items.", "info")
    return redirect(url_for("inventory"))

@app.route('/inventory_pdf_report')
def inventory_pdf_report():
    if not session.get("role") == "admin":
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard"))

    items = Inventory.query.all()

    # Create simple HTML for PDF
    html_content = f"""
    <html>
    <head>
        <title>Inventory Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            .available {{ color: green; }}
            .missing {{ color: red; }}
        </style>
    </head>
    <body>
        <h1>Inventory Report</h1>
        <p>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <table>
            <tr>
                <th>QR Code</th>
                <th>Item Name</th>
                <th>Category</th>
                <th>Status</th>
            </tr>
    """

    for item in items:
        qr_code = item.description.split(' - QR: ')[1] if ' - QR: ' in item.description else 'N/A'
        category = item.description.split(' - QR: ')[0] if ' - QR: ' in item.description else item.description
        status = "Available" if item.quantity > 0 else "Missing"
        status_class = "available" if item.quantity > 0 else "missing"

        html_content += f"""
            <tr>
                <td>{qr_code}</td>
                <td>{item.item_name}</td>
                <td>{category}</td>
                <td class="{status_class}">{status}</td>
            </tr>
        """

    html_content += """
        </table>
    </body>
    </html>
    """

    # Generate PDF
    pdf = BytesIO()
    pisa_status = pisa.CreatePDF(html_content, dest=pdf)
    if pisa_status.err:
        flash("PDF generation error", "error")
        return redirect(url_for("inventory"))

    pdf.seek(0)
    filename = f"Inventory_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return send_file(pdf, download_name=filename, as_attachment=True)

@app.route('/inventory_excel_report')
def inventory_excel_report():
    if not session.get("role") == "admin":
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard"))

    items = Inventory.query.all()

    # Prepare data for Excel
    data = []
    for item in items:
        qr_code = item.description.split(' - QR: ')[1] if ' - QR: ' in item.description else 'N/A'
        category = item.description.split(' - QR: ')[0] if ' - QR: ' in item.description else item.description
        status = "Available" if item.quantity > 0 else "Missing"

        data.append({
            'QR Code': qr_code,
            'Item Name': item.item_name,
            'Category': category,
            'Status': status
        })

    df = pd.DataFrame(data)

    # Export to Excel
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Inventory')
    output.seek(0)

    filename = f"Inventory_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(output,
                     download_name=filename,
                     as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# -------------------------------
# Run App
# -------------------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)


