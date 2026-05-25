import markdown
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory, abort, make_response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
from functools import wraps
import random, os, uuid
import pdfkit
from groq import Groq
import logging
from weasyprint import HTML
import unicodedata
import traceback
import re

# ── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'edunexus-super-secret-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///edunexus.db'

# ── PDFKIT CONFIGURATION (wkhtmltopdf) ──────────────────────────────────────
# For local Windows development:
WKHTMLTOPDF_PATH = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'
if os.path.exists(WKHTMLTOPDF_PATH):
    pdfkit_config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)
else:
    # For PythonAnywhere or other Linux environments where wkhtmltopdf is in PATH
    pdfkit_config = None

# ── FILE UPLOAD CONFIG ──────────────────────────────────────────────────────
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_EXTENSIONS = {'pdf','doc','docx','txt','png','jpg','jpeg','gif','ppt','pptx','xls','xlsx','zip','mp4','mp3'}
MAX_FILE_MB = 16
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_MB * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

def file_icon(filename):
    if not filename: return 'fa-file'
    ext = filename.rsplit('.',1)[-1].lower() if '.' in filename else ''
    icons = {
        'pdf':'fa-file-pdf','doc':'fa-file-word','docx':'fa-file-word',
        'ppt':'fa-file-powerpoint','pptx':'fa-file-powerpoint',
        'xls':'fa-file-excel','xlsx':'fa-file-excel',
        'png':'fa-file-image','jpg':'fa-file-image','jpeg':'fa-file-image','gif':'fa-file-image',
        'txt':'fa-file-lines','zip':'fa-file-zipper',
        'mp4':'fa-file-video','mp3':'fa-file-audio',
    }
    return icons.get(ext,'fa-file')

def file_color(filename):
    if not filename: return 'var(--text3)'
    ext = filename.rsplit('.',1)[-1].lower() if '.' in filename else ''
    colors = {
        'pdf':'#f74f6a','doc':'#4f8ef7','docx':'#4f8ef7',
        'ppt':'#f79240','pptx':'#f79240','xls':'#10d9a0','xlsx':'#10d9a0',
        'png':'#f76ab4','jpg':'#f76ab4','jpeg':'#f76ab4','gif':'#f76ab4',
        'txt':'#8896b0','zip':'#f5c842','mp4':'#7c6af7','mp3':'#7c6af7',
    }
    return colors.get(ext,'var(--text3)')

app.jinja_env.globals['file_icon'] = file_icon
app.jinja_env.globals['file_color'] = file_color

def fmt_size(b):
    if not b: return ''
    if b < 1024: return f'{b} B'
    if b < 1024*1024: return f'{b/1024:.1f} KB'
    return f'{b/1024/1024:.1f} MB'

app.jinja_env.globals['fmt_size'] = fmt_size
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ── MODELS ────────────────────────────────────────────────────────────────────

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # superadmin|admin|teacher|student|parent
    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    avatar_color = db.Column(db.String(7), default='#6366f1')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    # Limited-admin permission flags
    can_manage_students   = db.Column(db.Boolean, default=True)
    can_manage_teachers   = db.Column(db.Boolean, default=False)
    can_manage_exams      = db.Column(db.Boolean, default=True)
    can_manage_attendance = db.Column(db.Boolean, default=True)
    can_manage_announcements = db.Column(db.Boolean, default=True)
    can_manage_timetable  = db.Column(db.Boolean, default=False)
    can_manage_streams    = db.Column(db.Boolean, default=False)

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    motto = db.Column(db.String(300))
    address = db.Column(db.String(300))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    principal = db.Column(db.String(120))
    founded = db.Column(db.Integer)

class Stream(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    grade = db.Column(db.String(20), nullable=False)
    capacity = db.Column(db.Integer, default=45)
    class_teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    class_teacher = db.relationship('User', foreign_keys=[class_teacher_id])

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    adm_no = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', foreign_keys=[user_id])
    stream_id = db.Column(db.Integer, db.ForeignKey('stream.id'))
    stream = db.relationship('Stream')
    parent_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    parent = db.relationship('User', foreign_keys=[parent_id])
    dob = db.Column(db.Date)
    gender = db.Column(db.String(10))
    kcpe_marks = db.Column(db.Integer)
    joined_date = db.Column(db.Date, default=date.today)
    is_active = db.Column(db.Boolean, default=True)

class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(10), nullable=False)
    category = db.Column(db.String(50))
    is_compulsory = db.Column(db.Boolean, default=True)

class TeacherSubject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    teacher = db.relationship('User')
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    subject = db.relationship('Subject')
    stream_id = db.Column(db.Integer, db.ForeignKey('stream.id'), nullable=False)
    stream = db.relationship('Stream')

class Exam(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    term = db.Column(db.String(20), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    exam_type = db.Column(db.String(50))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    stream_id = db.Column(db.Integer, db.ForeignKey('stream.id'))
    stream = db.relationship('Stream')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Result(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    student = db.relationship('Student')
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), nullable=False)
    exam = db.relationship('Exam')
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    subject = db.relationship('Subject')
    marks = db.Column(db.Float, nullable=False)
    grade = db.Column(db.String(5))
    entered_by = db.Column(db.Integer, db.ForeignKey('user.id'))

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    student = db.relationship('Student')
    date = db.Column(db.Date, nullable=False, default=date.today)
    status = db.Column(db.String(20), nullable=False)
    stream_id = db.Column(db.Integer, db.ForeignKey('stream.id'))
    stream = db.relationship('Stream')
    recorded_by = db.Column(db.Integer, db.ForeignKey('user.id'))

class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    author = db.relationship('User')
    audience = db.Column(db.String(50), default='all')
    priority = db.Column(db.String(20), default='normal')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    event_date = db.Column(db.Date, nullable=False)
    event_type = db.Column(db.String(50))
    venue = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))

class Timetable(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stream_id = db.Column(db.Integer, db.ForeignKey('stream.id'), nullable=False)
    stream = db.relationship('Stream')
    day = db.Column(db.String(15), nullable=False)
    period = db.Column(db.Integer, nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'))
    subject = db.relationship('Subject')
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    teacher = db.relationship('User')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sender = db.relationship('User', foreign_keys=[sender_id])
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject = db.Column(db.String(200))
    body = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    subject = db.relationship('Subject')
    stream_id = db.Column(db.Integer, db.ForeignKey('stream.id'), nullable=False)
    stream = db.relationship('Stream')
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    teacher = db.relationship('User')
    due_date = db.Column(db.Date, nullable=False)
    max_marks = db.Column(db.Integer, default=100)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AssignmentSubmission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'), nullable=False)
    assignment = db.relationship('Assignment')
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    student = db.relationship('Student')
    notes = db.Column(db.Text)
    file_name = db.Column(db.String(300))
    file_path = db.Column(db.String(300))
    file_size = db.Column(db.Integer)
    marks_awarded = db.Column(db.Float)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    graded_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='submitted')

# ── HELPERS ───────────────────────────────────────────────────────────────────

def get_grade(m):
    if m>=80:return'A'
    elif m>=75:return'A-'
    elif m>=70:return'B+'
    elif m>=65:return'B'
    elif m>=60:return'B-'
    elif m>=55:return'C+'
    elif m>=50:return'C'
    elif m>=45:return'C-'
    elif m>=40:return'D+'
    elif m>=35:return'D'
    elif m>=30:return'D-'
    else:return'E'

def login_required(f):
    @wraps(f)
    def d(*a,**k):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*a,**k)
    return d

def role_required(*roles):
    def dec(f):
        @wraps(f)
        def d(*a,**k):
            if session.get('role') not in roles:
                flash('Access denied.','error'); return redirect(url_for('dashboard'))
            return f(*a,**k)
        return d
    return dec

def current_user():
    if 'user_id' in session: return User.query.get(session['user_id'])
    return None

def is_superadmin(): return session.get('role')=='superadmin'
def is_super_or_admin(): return session.get('role') in ('superadmin','admin')

def teacher_stream_ids(tid):
    return [r[0] for r in db.session.query(TeacherSubject.stream_id).filter_by(teacher_id=tid).distinct().all()]

def teacher_student_ids(tid):
    sids = teacher_stream_ids(tid)
    if not sids: return []
    return [s.id for s in Student.query.filter(Student.stream_id.in_(sids), Student.is_active==True).all()]

app.jinja_env.globals.update(current_user=current_user, is_superadmin=is_superadmin,
                              is_super_or_admin=is_super_or_admin, date=date)

# ── AUTH ──────────────────────────────────────────────────────────────────────
@app.route('/media/<path:filename>')
def serve_media(filename):
    # This ensures it works on both local and PythonAnywhere
    media_folder = os.path.join(os.path.dirname(__file__), 'media')
    return send_from_directory(media_folder, filename)

@app.route('/')
def index():
    return redirect(url_for('dashboard') if 'user_id' in session else url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username'].strip(), is_active=True).first()
        if u and check_password_hash(u.password_hash, request.form['password']):
            session.update({'user_id':u.id,'role':u.role,'full_name':u.full_name})
            flash(f'Welcome back, {u.full_name.split()[0]}! 🎉','success')
            return redirect(url_for('dashboard'))
        flash('Invalid credentials. Try again.','error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

# ── DASHBOARD ─────────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    school = School.query.first()
    ann = Announcement.query.filter((Announcement.audience=='all')|(Announcement.audience==user.role)).order_by(Announcement.created_at.desc()).limit(5).all()
    events = Event.query.filter(Event.event_date>=date.today()).order_by(Event.event_date).limit(5).all()
    stats = {}

    if user.role in ('superadmin','admin'):
        stats = dict(students=Student.query.filter_by(is_active=True).count(),
                     teachers=User.query.filter_by(role='teacher',is_active=True).count(),
                     streams=Stream.query.count(), subjects=Subject.query.count(),
                     exams=Exam.query.count())
        recent = Student.query.order_by(Student.id.desc()).limit(5).all()
        return render_template('dashboard_admin.html', stats=stats, school=school,
                               announcements=ann, events=events, recent_students=recent)

    elif user.role == 'teacher':
        sids = teacher_stream_ids(user.id)
        stats = dict(my_streams=len(sids),
                     my_subjects=TeacherSubject.query.filter_by(teacher_id=user.id).count(),
                     total_students=Student.query.filter(Student.stream_id.in_(sids),Student.is_active==True).count() if sids else 0,
                     today_attendance=Attendance.query.filter(Attendance.stream_id.in_(sids),Attendance.date==date.today()).count() if sids else 0,
                     pending_grading=AssignmentSubmission.query.join(Assignment).filter(Assignment.teacher_id==user.id,AssignmentSubmission.status=='submitted').count())
        my_asgn = Assignment.query.filter_by(teacher_id=user.id).order_by(Assignment.due_date).limit(5).all()
        return render_template('dashboard_teacher.html', stats=stats, school=school,
                               announcements=ann, events=events, my_assignments=my_asgn)

    elif user.role == 'student':
        student = Student.query.filter_by(user_id=user.id).first()
        if student:
            results = Result.query.filter_by(student_id=student.id).all()
            avg = round(sum(r.marks for r in results)/len(results),1) if results else 0
            att = Attendance.query.filter_by(student_id=student.id).all()
            pct = round(sum(1 for a in att if a.status=='present')/len(att)*100,1) if att else 0
            total_a = Assignment.query.filter_by(stream_id=student.stream_id).count() if student.stream_id else 0
            submitted_a = AssignmentSubmission.query.filter_by(student_id=student.id).count()
            stats = dict(avg_marks=avg, attendance_pct=pct,
                         subjects=len({r.subject_id for r in results}),
                         exams=len({r.exam_id for r in results}),
                         pending_assignments=max(0, total_a-submitted_a))
        return render_template('dashboard_student.html', stats=stats, school=school,
                               student=student, announcements=ann, events=events)

    elif user.role == 'parent':
        children = Student.query.filter_by(parent_id=user.id, is_active=True).all()
        cdata = []
        for c in children:
            results = Result.query.filter_by(student_id=c.id).all()
            avg = round(sum(r.marks for r in results)/len(results),1) if results else 0
            att = Attendance.query.filter_by(student_id=c.id).all()
            pct = round(sum(1 for a in att if a.status=='present')/len(att)*100,1) if att else 0
            recent_att = Attendance.query.filter_by(student_id=c.id).order_by(Attendance.date.desc()).limit(7).all()
            pending_a = 0
            if c.stream_id:
                total_a = Assignment.query.filter_by(stream_id=c.stream_id).count()
                sub_a = AssignmentSubmission.query.filter_by(student_id=c.id).count()
                pending_a = max(0, total_a-sub_a)
            cdata.append(dict(student=c, avg=avg, att_pct=pct, recent_att=recent_att, pending_assignments=pending_a))
        return render_template('dashboard_parent.html', children_data=cdata, school=school,
                               announcements=ann, events=events)
    return redirect(url_for('login'))

# ── STUDENTS ──────────────────────────────────────────────────────────────────

@app.route('/students')
@login_required
def students():
    user = current_user()
    q = request.args.get('q',''); sid = request.args.get('stream_id','')
    if user.role in ('superadmin','admin'):
        qr = Student.query.filter_by(is_active=True)
        if q: qr = qr.join(User).filter((User.full_name.ilike(f'%{q}%'))|(Student.adm_no.ilike(f'%{q}%')))
        if sid: qr = qr.filter_by(stream_id=int(sid))
        streams = Stream.query.all()
    elif user.role == 'teacher':
        sids = teacher_stream_ids(user.id)
        qr = Student.query.filter(Student.stream_id.in_(sids), Student.is_active==True)
        if q: qr = qr.join(User).filter((User.full_name.ilike(f'%{q}%'))|(Student.adm_no.ilike(f'%{q}%')))
        if sid and int(sid) in sids: qr = qr.filter_by(stream_id=int(sid))
        streams = Stream.query.filter(Stream.id.in_(sids)).all()
    elif user.role == 'student':
        st = Student.query.filter_by(user_id=user.id).first()
        return redirect(url_for('student_profile', id=st.id)) if st else redirect(url_for('dashboard'))
    else:
        return redirect(url_for('dashboard'))
    return render_template('students.html', students=qr.all(), streams=streams, q=q, selected_stream=sid)

@app.route('/students/add', methods=['GET','POST'])
@login_required
@role_required('superadmin','admin')
def add_student():
    user = current_user()
    if user.role == 'admin' and not user.can_manage_students:
        flash('Permission denied.','error'); return redirect(url_for('students'))
    if request.method == 'POST':
        adm = f"ADM{date.today().year}{random.randint(1000,9999)}"
        colors = ['#6366f1','#0ea5e9','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899']
        u = User(username=adm.lower(), email=request.form['email'],
                 password_hash=generate_password_hash('student123'),
                 role='student', full_name=request.form['full_name'], avatar_color=random.choice(colors))
        db.session.add(u); db.session.flush()
        dob = datetime.strptime(request.form['dob'],'%Y-%m-%d').date() if request.form.get('dob') else None
        db.session.add(Student(adm_no=adm, user_id=u.id, stream_id=int(request.form['stream_id']),
                               gender=request.form['gender'], dob=dob,
                               kcpe_marks=int(request.form.get('kcpe_marks',0) or 0)))
        db.session.commit()
        flash(f'Student added! Adm No: {adm}','success')
        return redirect(url_for('students'))
    return render_template('add_student.html', streams=Stream.query.all())

@app.route('/students/<int:id>/delete', methods=['POST'])
@login_required
@role_required('superadmin')
def delete_student(id):
    s = Student.query.get_or_404(id)
    s.is_active = False; s.user.is_active = False
    db.session.commit()
    flash(f'{s.user.full_name} removed.','success')
    return redirect(url_for('students'))

@app.route('/students/<int:id>')
@login_required
def student_profile(id):
    user = current_user()
    student = Student.query.get_or_404(id)
    if user.role == 'student':
        own = Student.query.filter_by(user_id=user.id).first()
        if not own or own.id != id: flash('You can only view your own profile.','error'); return redirect(url_for('dashboard'))
    elif user.role == 'parent':
        if id not in [s.id for s in Student.query.filter_by(parent_id=user.id,is_active=True).all()]:
            flash('Access denied.','error'); return redirect(url_for('dashboard'))
    elif user.role == 'teacher':
        if id not in teacher_student_ids(user.id): flash('Not in your classes.','error'); return redirect(url_for('students'))
    results = Result.query.filter_by(student_id=id).all()
    att = Attendance.query.filter_by(student_id=id).order_by(Attendance.date.desc()).limit(30).all()
    exam_results = {}
    for r in results:
        if r.exam_id not in exam_results:
            exam_results[r.exam_id] = {'exam':r.exam,'subjects':[],'total':0,'count':0}
        exam_results[r.exam_id]['subjects'].append(r)
        exam_results[r.exam_id]['total'] += r.marks
        exam_results[r.exam_id]['count'] += 1
    for eid in exam_results:
        exam_results[eid]['avg'] = round(exam_results[eid]['total']/exam_results[eid]['count'],1)
    att_counts = dict(present=0,absent=0,late=0,excused=0)
    for a in Attendance.query.filter_by(student_id=id).all(): att_counts[a.status] = att_counts.get(a.status,0)+1
    assignments = Assignment.query.filter_by(stream_id=student.stream_id).order_by(Assignment.due_date.desc()).all() if student.stream_id else []
    sub_map = {s.assignment_id:s for s in AssignmentSubmission.query.filter_by(student_id=id).all()}
    return render_template('student_profile.html', student=student, exam_results=exam_results,
                           attendance=att, att_counts=att_counts, assignments=assignments, sub_map=sub_map)

# ── TEACHERS ──────────────────────────────────────────────────────────────────

@app.route('/teachers')
@login_required
@role_required('superadmin','admin')
def teachers():
    user = current_user()
    if user.role == 'admin' and not user.can_manage_teachers: flash('Permission denied.','error'); return redirect(url_for('dashboard'))
    tdata = [{'teacher':t,'assignments':TeacherSubject.query.filter_by(teacher_id=t.id).count()}
             for t in User.query.filter_by(role='teacher',is_active=True).all()]
    return render_template('teachers.html', teacher_data=tdata)

@app.route('/teachers/add', methods=['GET','POST'])
@login_required
@role_required('superadmin','admin')
def add_teacher():
    user = current_user()
    if user.role == 'admin' and not user.can_manage_teachers: flash('Permission denied.','error'); return redirect(url_for('dashboard'))
    if request.method == 'POST':
        colors = ['#6366f1','#0ea5e9','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899']
        uname = request.form['email'].split('@')[0].lower().replace('.','_')
        db.session.add(User(username=uname, email=request.form['email'], phone=request.form.get('phone',''),
                            password_hash=generate_password_hash('teacher123'),
                            role='teacher', full_name=request.form['full_name'], avatar_color=random.choice(colors)))
        db.session.commit(); flash(f"Teacher {request.form['full_name']} added!",'success')
        return redirect(url_for('teachers'))
    return render_template('add_teacher.html')

@app.route('/teachers/<int:id>/delete', methods=['POST'])
@login_required
@role_required('superadmin')
def delete_teacher(id):
    t = User.query.get_or_404(id); t.is_active = False
    db.session.commit(); flash(f'{t.full_name} removed.','success')
    return redirect(url_for('teachers'))

@app.route('/teachers/<int:id>/assign', methods=['GET','POST'])
@login_required
@role_required('superadmin','admin')
def assign_teacher(id):
    teacher = User.query.get_or_404(id)
    if request.method == 'POST':
        sid,sub = int(request.form['stream_id']),int(request.form['subject_id'])
        if not TeacherSubject.query.filter_by(teacher_id=id,stream_id=sid,subject_id=sub).first():
            db.session.add(TeacherSubject(teacher_id=id,stream_id=sid,subject_id=sub))
            db.session.commit(); flash('Assignment added!','success')
        else: flash('Already assigned.','info')
        return redirect(url_for('assign_teacher', id=id))
    return render_template('assign_teacher.html', teacher=teacher,
                           assignments=TeacherSubject.query.filter_by(teacher_id=id).all(),
                           streams=Stream.query.all(), subjects=Subject.query.all())

@app.route('/teachers/assignment/<int:id>/delete', methods=['POST'])
@login_required
@role_required('superadmin')
def delete_teacher_assignment(id):
    ts = TeacherSubject.query.get_or_404(id); tid = ts.teacher_id
    db.session.delete(ts); db.session.commit(); flash('Assignment removed.','success')
    return redirect(url_for('assign_teacher', id=tid))

# ── STREAMS ───────────────────────────────────────────────────────────────────

@app.route('/streams')
@login_required
@role_required('superadmin','admin','teacher')
def streams():
    user = current_user()
    if user.role == 'teacher':
        sids = teacher_stream_ids(user.id)
        all_s = Stream.query.filter(Stream.id.in_(sids)).all()
    else: all_s = Stream.query.all()
    sdata = [{'stream':s,'count':Student.query.filter_by(stream_id=s.id,is_active=True).count()} for s in all_s]
    return render_template('streams.html', stream_data=sdata)

@app.route('/streams/add', methods=['GET','POST'])
@login_required
@role_required('superadmin','admin')
def add_stream():
    user = current_user()
    if user.role == 'admin' and not user.can_manage_streams: flash('Permission denied.','error'); return redirect(url_for('streams'))
    if request.method == 'POST':
        db.session.add(Stream(name=request.form['name'], grade=request.form['grade'],
                              capacity=int(request.form.get('capacity',45)),
                              class_teacher_id=request.form.get('class_teacher_id') or None))
        db.session.commit(); flash(f"Stream {request.form['name']} created!",'success')
        return redirect(url_for('streams'))
    return render_template('add_stream.html', teachers=User.query.filter_by(role='teacher',is_active=True).all())

@app.route('/streams/<int:id>/delete', methods=['POST'])
@login_required
@role_required('superadmin')
def delete_stream(id):
    s = Stream.query.get_or_404(id)
    cnt = Student.query.filter_by(stream_id=id,is_active=True).count()
    if cnt: flash(f'Cannot delete: {cnt} students still in this stream.','error'); return redirect(url_for('streams'))
    db.session.delete(s); db.session.commit(); flash(f'Stream {s.name} deleted.','success')
    return redirect(url_for('streams'))

# ── EXAMS ─────────────────────────────────────────────────────────────────────

@app.route('/exams')
@login_required
def exams():
    user = current_user()
    if user.role == 'teacher':
        sids = teacher_stream_ids(user.id)
        elist = Exam.query.filter((Exam.stream_id==None)|(Exam.stream_id.in_(sids))).order_by(Exam.year.desc()).all()
    else: elist = Exam.query.order_by(Exam.year.desc(),Exam.start_date.desc()).all()
    return render_template('exams.html', exams=elist)

@app.route('/exams/add', methods=['GET','POST'])
@login_required
@role_required('superadmin','admin')
def add_exam():
    user = current_user()
    if user.role == 'admin' and not user.can_manage_exams: flash('Permission denied.','error'); return redirect(url_for('exams'))
    if request.method == 'POST':
        db.session.add(Exam(name=request.form['name'],term=request.form['term'],
                            year=int(request.form['year']),exam_type=request.form['exam_type'],
                            stream_id=request.form.get('stream_id') or None,
                            start_date=datetime.strptime(request.form['start_date'],'%Y-%m-%d').date() if request.form.get('start_date') else None,
                            end_date=datetime.strptime(request.form['end_date'],'%Y-%m-%d').date() if request.form.get('end_date') else None))
        db.session.commit(); flash(f"Exam created!",'success')
        return redirect(url_for('exams'))
    return render_template('add_exam.html', streams=Stream.query.all())

@app.route('/exams/<int:id>/delete', methods=['POST'])
@login_required
@role_required('superadmin')
def delete_exam(id):
    e = Exam.query.get_or_404(id)
    Result.query.filter_by(exam_id=id).delete()
    db.session.delete(e); db.session.commit(); flash(f'Exam "{e.name}" deleted.','success')
    return redirect(url_for('exams'))

# ── RESULTS ───────────────────────────────────────────────────────────────────

@app.route('/results/enter', methods=['GET','POST'])
@login_required
@role_required('superadmin','admin','teacher')
def enter_results():
    user = current_user()
    if user.role == 'admin' and not user.can_manage_exams: flash('Permission denied.','error'); return redirect(url_for('results_view'))
    if request.method == 'POST':
        eid,sub_id,sid = int(request.form['exam_id']),int(request.form['subject_id']),int(request.form['stream_id'])
        if user.role == 'teacher' and sid not in teacher_stream_ids(user.id): flash('Access denied.','error'); return redirect(url_for('enter_results'))
        saved = 0
        for s in Student.query.filter_by(stream_id=sid,is_active=True).all():
            v = request.form.get(f'marks_{s.id}','').strip()
            if v:
                marks = float(v)
                ex = Result.query.filter_by(student_id=s.id,exam_id=eid,subject_id=sub_id).first()
                if ex: ex.marks=marks; ex.grade=get_grade(marks)
                else: db.session.add(Result(student_id=s.id,exam_id=eid,subject_id=sub_id,marks=marks,grade=get_grade(marks),entered_by=user.id))
                saved += 1
        db.session.commit(); flash(f'Results saved for {saved} students!','success')
        return redirect(url_for('results_view',exam_id=eid,stream_id=sid))
    elist = Exam.query.all(); subjects = Subject.query.all()
    if user.role == 'teacher': streams = Stream.query.filter(Stream.id.in_(teacher_stream_ids(user.id))).all()
    else: streams = Stream.query.all()
    se,ss = request.args.get('exam_id'),request.args.get('stream_id')
    students_list = []; existing = {}
    if se and ss:
        students_list = Student.query.filter_by(stream_id=int(ss),is_active=True).all()
        sub_id = request.args.get('subject_id')
        if sub_id:
            for r in Result.query.filter_by(exam_id=int(se),subject_id=int(sub_id)).all():
                existing[r.student_id] = r.marks
    return render_template('enter_results.html', exams=elist, subjects=subjects, streams=streams,
                           students=students_list, existing_results=existing, selected_exam=se, selected_stream=ss)

@app.route('/results')
@login_required
def results_view():
    user = current_user()
    if user.role == 'student':
        s = Student.query.filter_by(user_id=user.id).first()
        return redirect(url_for('student_profile',id=s.id)) if s else redirect(url_for('dashboard'))
    if user.role == 'parent': return redirect(url_for('dashboard'))
    elist = Exam.query.all()
    if user.role == 'teacher': streams = Stream.query.filter(Stream.id.in_(teacher_stream_ids(user.id))).all()
    else: streams = Stream.query.all()
    eid,sid = request.args.get('exam_id'),request.args.get('stream_id')
    rdata=[]; exam=stream=None
    if eid and sid:
        if user.role == 'teacher' and int(sid) not in teacher_stream_ids(user.id): flash('Access denied.','error'); return redirect(url_for('results_view'))
        exam=Exam.query.get(eid); stream=Stream.query.get(sid)
        for s in Student.query.filter_by(stream_id=int(sid),is_active=True).all():
            sr = Result.query.filter_by(student_id=s.id,exam_id=int(eid)).all()
            total=sum(r.marks for r in sr); avg=round(total/len(sr),1) if sr else 0
            rdata.append({'student':s,'results':sr,'total':total,'avg':avg,'grade':get_grade(avg) if sr else'-'})
        rdata.sort(key=lambda x:x['avg'],reverse=True)
        for i,r in enumerate(rdata): r['position']=i+1
    return render_template('results_view.html', exams=elist, streams=streams, results_data=rdata,
                           exam=exam, stream=stream, selected_exam=eid, selected_stream=sid)

# ── ATTENDANCE ────────────────────────────────────────────────────────────────

@app.route('/attendance', methods=['GET','POST'])
@login_required
@role_required('superadmin','admin','teacher')
def attendance():
    user = current_user()
    if user.role == 'admin' and not user.can_manage_attendance: flash('Permission denied.','error'); return redirect(url_for('dashboard'))
    if request.method == 'POST':
        sid=int(request.form['stream_id']); att_date=datetime.strptime(request.form['date'],'%Y-%m-%d').date()
        if user.role == 'teacher' and sid not in teacher_stream_ids(user.id): flash('Access denied.','error'); return redirect(url_for('attendance'))
        for s in Student.query.filter_by(stream_id=sid,is_active=True).all():
            status=request.form.get(f'status_{s.id}','absent')
            ex = Attendance.query.filter_by(student_id=s.id,date=att_date).first()
            if ex: ex.status=status
            else: db.session.add(Attendance(student_id=s.id,stream_id=sid,date=att_date,status=status,recorded_by=user.id))
        db.session.commit(); flash('Attendance saved!','success')
        return redirect(url_for('attendance'))
    if user.role == 'teacher': streams=Stream.query.filter(Stream.id.in_(teacher_stream_ids(user.id))).all()
    else: streams=Stream.query.all()
    ss=request.args.get('stream_id'); adate=request.args.get('date',str(date.today()))
    students_list=[]; existing={}
    if ss:
        if user.role=='teacher' and int(ss) not in teacher_stream_ids(user.id): flash('Access denied.','error'); return redirect(url_for('attendance'))
        students_list=Student.query.filter_by(stream_id=int(ss),is_active=True).all()
        pd=datetime.strptime(adate,'%Y-%m-%d').date()
        for a in Attendance.query.filter_by(stream_id=int(ss),date=pd).all(): existing[a.student_id]=a.status
    stats=[{'date':(date.today()-timedelta(days=i)).strftime('%a %d'),
            'present':Attendance.query.filter_by(date=date.today()-timedelta(days=i),status='present').count(),
            'absent':Attendance.query.filter_by(date=date.today()-timedelta(days=i),status='absent').count()} for i in range(7)]
    return render_template('attendance.html', streams=streams, students=students_list,
                           existing_att=existing, selected_stream=ss, att_date=adate, stats=stats)

# ── ASSIGNMENTS ───────────────────────────────────────────────────────────────

@app.route('/assignments')
@login_required
def assignments():
    user = current_user()
    if user.role == 'teacher':
        alist = Assignment.query.filter_by(teacher_id=user.id).order_by(Assignment.due_date.desc()).all()
        pc = {a.id: AssignmentSubmission.query.filter_by(assignment_id=a.id,status='submitted').count() for a in alist}
        return render_template('assignments_teacher.html', assignments=alist, pending_counts=pc)
    elif user.role == 'student':
        student = Student.query.filter_by(user_id=user.id).first()
        if not student: return redirect(url_for('dashboard'))
        alist = Assignment.query.filter_by(stream_id=student.stream_id).order_by(Assignment.due_date).all() if student.stream_id else []
        sub_map = {s.assignment_id:s for s in AssignmentSubmission.query.filter_by(student_id=student.id).all()}
        return render_template('assignments_student.html', assignments=alist, sub_map=sub_map, student=student, max_mb=MAX_FILE_MB)
    elif user.role in ('superadmin','admin'):
        alist = Assignment.query.order_by(Assignment.due_date.desc()).all()
        return render_template('assignments_admin.html', assignments=alist)
    elif user.role == 'parent':
        children = Student.query.filter_by(parent_id=user.id,is_active=True).all()
        cdata=[]
        for c in children:
            ca = Assignment.query.filter_by(stream_id=c.stream_id).order_by(Assignment.due_date).all() if c.stream_id else []
            submitted={s.assignment_id for s in AssignmentSubmission.query.filter_by(student_id=c.id).all()}
            cdata.append({'student':c,'assignments':ca,'submitted':submitted})
        return render_template('assignments_parent.html', children_data=cdata)
    return redirect(url_for('dashboard'))

@app.route('/assignments/add', methods=['GET','POST'])
@login_required
@role_required('superadmin','admin','teacher')
def add_assignment():
    user = current_user()
    if request.method == 'POST':
        tid = user.id if user.role=='teacher' else int(request.form.get('teacher_id',user.id))
        db.session.add(Assignment(title=request.form['title'],description=request.form['description'],
                                  subject_id=int(request.form['subject_id']),stream_id=int(request.form['stream_id']),
                                  teacher_id=tid,due_date=datetime.strptime(request.form['due_date'],'%Y-%m-%d').date(),
                                  max_marks=int(request.form.get('max_marks',100))))
        db.session.commit(); flash(f"Assignment posted!",'success')
        return redirect(url_for('assignments'))
    if user.role == 'teacher':
        sids = teacher_stream_ids(user.id)
        streams = Stream.query.filter(Stream.id.in_(sids)).all()
        sub_ids = {ts.subject_id for ts in TeacherSubject.query.filter_by(teacher_id=user.id).all()}
        subjects = Subject.query.filter(Subject.id.in_(sub_ids)).all()
        teachers = []
    else:
        streams=Stream.query.all(); subjects=Subject.query.all()
        teachers=User.query.filter_by(role='teacher',is_active=True).all()
    return render_template('add_assignment.html', streams=streams, subjects=subjects, teachers=teachers)

@app.route('/assignments/<int:id>')
@login_required
def view_assignment(id):
    user = current_user()
    a = Assignment.query.get_or_404(id)
    if user.role == 'teacher' and a.teacher_id != user.id: flash('Access denied.','error'); return redirect(url_for('assignments'))
    if user.role == 'student':
        s = Student.query.filter_by(user_id=user.id).first()
        if not s or s.stream_id != a.stream_id: flash('Access denied.','error'); return redirect(url_for('assignments'))
    if user.role == 'parent':
        children = [c.id for c in Student.query.filter_by(parent_id=user.id,is_active=True).all()]
        child_streams = [Student.query.get(cid).stream_id for cid in children]
        if a.stream_id not in child_streams: flash('Access denied.','error'); return redirect(url_for('assignments'))
    submissions = AssignmentSubmission.query.filter_by(assignment_id=id).all()
    students_in_stream = Student.query.filter_by(stream_id=a.stream_id,is_active=True).all()
    submitted_ids = {s.student_id for s in submissions}
    return render_template('view_assignment.html', assignment=a, submissions=submissions,
                           students_in_stream=students_in_stream, submitted_ids=submitted_ids)

@app.route('/assignments/<int:id>/submit', methods=['POST'])
@login_required
@role_required('student')
def submit_assignment(id):
    a = Assignment.query.get_or_404(id)
    student = Student.query.filter_by(user_id=session['user_id']).first()
    if AssignmentSubmission.query.filter_by(assignment_id=id,student_id=student.id).first():
        flash('Already submitted.','info'); return redirect(url_for('assignments'))
    status = 'late' if date.today() > a.due_date else 'submitted'

    # handle optional file upload
    fname = fpath = fsize = None
    uploaded = request.files.get('submission_file')
    if uploaded and uploaded.filename:
        if not allowed_file(uploaded.filename):
            flash('File type not allowed. Allowed: ' + ', '.join(sorted(ALLOWED_EXTENSIONS)),'error')
            return redirect(url_for('assignments'))
        ext = uploaded.filename.rsplit('.',1)[1].lower()
        stored_name = 'sub_' + uuid.uuid4().hex + '.' + ext
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
        uploaded.save(save_path)
        fname = secure_filename(uploaded.filename)
        fpath = stored_name
        fsize = os.path.getsize(save_path)

    sub = AssignmentSubmission(
        assignment_id=id, student_id=student.id,
        notes=request.form.get('notes',''),
        file_name=fname, file_path=fpath, file_size=fsize,
        status=status
    )
    db.session.add(sub)
    db.session.commit()
    msg = 'Late submission recorded' if status=='late' else 'Assignment submitted successfully'
    if fname: msg += ' (file attached 📎)'
    flash(msg + '! ✅','success')
    return redirect(url_for('assignments'))


@app.route('/uploads/<path:filename>')
@login_required
def serve_upload(filename):
    sub = AssignmentSubmission.query.filter_by(file_path=filename).first_or_404()
    user = current_user()
    is_owner  = (user.role=='student' and Student.query.filter_by(user_id=user.id,id=sub.student_id).first())
    is_teacher = user.role in ('teacher','admin','superadmin')
    if not (is_owner or is_teacher):
        abort(403)
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename,
                               as_attachment=True, download_name=sub.file_name or filename)

@app.route('/assignments/submission/<int:id>/grade', methods=['POST'])
@login_required
@role_required('superadmin','admin','teacher')
def grade_submission(id):
    sub = AssignmentSubmission.query.get_or_404(id)
    sub.marks_awarded=float(request.form['marks']); sub.status='graded'; sub.graded_at=datetime.utcnow()
    db.session.commit(); flash('Submission graded!','success')
    return redirect(url_for('view_assignment', id=sub.assignment_id))

@app.route('/assignments/<int:id>/delete', methods=['POST'])
@login_required
@role_required('superadmin','teacher')
def delete_assignment(id):
    user = current_user(); a = Assignment.query.get_or_404(id)
    if user.role=='teacher' and a.teacher_id!=user.id: flash('Access denied.','error'); return redirect(url_for('assignments'))
    AssignmentSubmission.query.filter_by(assignment_id=id).delete()
    db.session.delete(a); db.session.commit(); flash('Assignment deleted.','success')
    return redirect(url_for('assignments'))

# ── TIMETABLE ─────────────────────────────────────────────────────────────────

@app.route('/timetable')
@login_required
def timetable():
    user = current_user()
    if user.role=='teacher': streams=Stream.query.filter(Stream.id.in_(teacher_stream_ids(user.id))).all()
    elif user.role=='student':
        s=Student.query.filter_by(user_id=user.id).first()
        streams=Stream.query.filter_by(id=s.stream_id).all() if s and s.stream_id else []
    elif user.role=='parent':
        cids=[c.stream_id for c in Student.query.filter_by(parent_id=user.id,is_active=True).all() if c.stream_id]
        streams=Stream.query.filter(Stream.id.in_(cids)).all()
    else: streams=Stream.query.all()
    ss=request.args.get('stream_id')
    if user.role=='student' and not ss:
        s=Student.query.filter_by(user_id=user.id).first()
        if s and s.stream_id: ss=str(s.stream_id)
    td={}; days=['Monday','Tuesday','Wednesday','Thursday','Friday']; periods=list(range(1,9))
    pt={1:'7:00-7:40',2:'7:40-8:20',3:'8:20-9:00',4:'9:20-10:00',5:'10:00-10:40',6:'11:00-11:40',7:'11:40-12:20',8:'2:00-2:40'}
    if ss:
        for e in Timetable.query.filter_by(stream_id=int(ss)).all(): td[(e.day,e.period)]=e
    return render_template('timetable.html', streams=streams, timetable_data=td, days=days,
                           periods=periods, period_times=pt, selected_stream=ss,
                           subjects=Subject.query.all(), teachers=User.query.filter_by(role='teacher',is_active=True).all())

@app.route('/timetable/save', methods=['POST'])
@login_required
@role_required('superadmin','admin')
def save_timetable():
    user = current_user()
    if user.role=='admin' and not user.can_manage_timetable:
        flash('Permission denied.','error'); return redirect(url_for('timetable'))
    sid = int(request.form['stream_id'])
    days = ['Monday','Tuesday','Wednesday','Thursday','Friday']
    stream = Stream.query.get_or_404(sid)

    # ── Collision detection ───────────────────────────────────────────────────
    # Build a map of (teacher_id, day, period) already used by OTHER streams
    collisions = []
    for day in days:
        for p in range(1, 9):
            subj_id = request.form.get(f'{day}_{p}_subject')
            tchr_id = request.form.get(f'{day}_{p}_teacher')
            if not subj_id or not tchr_id:
                continue
            tchr_id_int = int(tchr_id)
            # Check if this teacher is already teaching another stream at the same slot
            conflict = Timetable.query.filter(
                Timetable.teacher_id == tchr_id_int,
                Timetable.day == day,
                Timetable.period == p,
                Timetable.stream_id != sid
            ).first()
            if conflict:
                teacher = User.query.get(tchr_id_int)
                other   = Stream.query.get(conflict.stream_id)
                subject = Subject.query.get(int(subj_id))
                collisions.append(
                    f"{teacher.full_name} is already teaching {other.name} "
                    f"on {day} Period {p}"
                )

            # Check duplicate subject for this stream in same day (optional warning)
            same_subj = Timetable.query.filter(
                Timetable.stream_id == sid,
                Timetable.day == day,
                Timetable.subject_id == int(subj_id),
                Timetable.period != p
            ).first()
            # (we allow same subject twice a day; just teacher conflict is a hard block)

    if collisions:
        for msg in collisions:
            flash(f'⚠️ Collision: {msg}', 'error')
        flash('Timetable NOT saved due to teacher collision(s). Please fix and try again.', 'error')
        return redirect(url_for('timetable', stream_id=sid))

    # ── No collisions — save ──────────────────────────────────────────────────
    for day in days:
        for p in range(1, 9):
            subj = request.form.get(f'{day}_{p}_subject')
            tchr = request.form.get(f'{day}_{p}_teacher')
            if subj and tchr:
                ex = Timetable.query.filter_by(stream_id=sid, day=day, period=p).first()
                if ex:
                    ex.subject_id = int(subj); ex.teacher_id = int(tchr)
                else:
                    db.session.add(Timetable(stream_id=sid, day=day, period=p,
                                             subject_id=int(subj), teacher_id=int(tchr)))
            elif request.form.get(f'{day}_{p}_clear'):
                # Clear a slot if explicitly blanked
                ex = Timetable.query.filter_by(stream_id=sid, day=day, period=p).first()
                if ex: db.session.delete(ex)

    db.session.commit()
    flash(f'Timetable for {stream.name} saved successfully! ✅', 'success')
    return redirect(url_for('timetable', stream_id=sid))


@app.route('/timetable/check-collision')
@login_required
def check_collision():
    """AJAX endpoint: check if a teacher is free for a given slot."""
    teacher_id = request.args.get('teacher_id', type=int)
    day        = request.args.get('day', '')
    period     = request.args.get('period', type=int)
    stream_id  = request.args.get('stream_id', type=int)
    if not all([teacher_id, day, period]):
        return jsonify({'collision': False})
    conflict = Timetable.query.filter(
        Timetable.teacher_id == teacher_id,
        Timetable.day == day,
        Timetable.period == period,
        Timetable.stream_id != stream_id
    ).first()
    if conflict:
        teacher = User.query.get(teacher_id)
        other   = Stream.query.get(conflict.stream_id)
        subj    = Subject.query.get(conflict.subject_id)
        return jsonify({
            'collision': True,
            'message': f'{teacher.full_name} is teaching {subj.name if subj else "?"} '
                       f'in {other.name if other else "?"} at this slot'
        })
    return jsonify({'collision': False})

# ── ANNOUNCEMENTS ─────────────────────────────────────────────────────────────

@app.route('/announcements')
@login_required
def announcements():
    user = current_user()
    ann=Announcement.query.filter((Announcement.audience=='all')|(Announcement.audience==user.role)).order_by(Announcement.created_at.desc()).all()
    return render_template('announcements.html', announcements=ann)

@app.route('/announcements/add', methods=['GET','POST'])
@login_required
@role_required('superadmin','admin','teacher')
def add_announcement():
    user = current_user()
    if user.role=='admin' and not user.can_manage_announcements: flash('Permission denied.','error'); return redirect(url_for('announcements'))
    if request.method=='POST':
        db.session.add(Announcement(title=request.form['title'],content=request.form['content'],
                                    audience=request.form['audience'],priority=request.form['priority'],author_id=user.id))
        db.session.commit(); flash('Announcement posted!','success'); return redirect(url_for('announcements'))
    return render_template('add_announcement.html')

@app.route('/announcements/<int:id>/delete', methods=['POST'])
@login_required
@role_required('superadmin','admin')
def delete_announcement(id):
    a=Announcement.query.get_or_404(id); db.session.delete(a); db.session.commit()
    flash('Announcement deleted.','success'); return redirect(url_for('announcements'))

# ── EVENTS ─────────────────────────────────────────────────────────────────────

@app.route('/events')
@login_required
def events():
    return render_template('events.html',
                           upcoming=Event.query.filter(Event.event_date>=date.today()).order_by(Event.event_date).all(),
                           past=Event.query.filter(Event.event_date<date.today()).order_by(Event.event_date.desc()).limit(10).all())

@app.route('/events/add', methods=['GET','POST'])
@login_required
@role_required('superadmin','admin')
def add_event():
    if request.method=='POST':
        db.session.add(Event(title=request.form['title'],description=request.form.get('description'),
                             event_date=datetime.strptime(request.form['event_date'],'%Y-%m-%d').date(),
                             event_type=request.form['event_type'],venue=request.form.get('venue'),created_by=session['user_id']))
        db.session.commit(); flash('Event added!','success'); return redirect(url_for('events'))
    return render_template('add_event.html')

@app.route('/events/<int:id>/delete', methods=['POST'])
@login_required
@role_required('superadmin')
def delete_event(id):
    e=Event.query.get_or_404(id); db.session.delete(e); db.session.commit()
    flash('Event deleted.','success'); return redirect(url_for('events'))

# ── MESSAGES ──────────────────────────────────────────────────────────────────

@app.route('/messages')
@login_required
def messages():
    user = current_user()
    inbox=Message.query.filter_by(recipient_id=user.id).order_by(Message.created_at.desc()).all()
    sent=Message.query.filter_by(sender_id=user.id).order_by(Message.created_at.desc()).all()
    return render_template('messages.html', inbox=inbox, sent=sent, unread=sum(1 for m in inbox if not m.is_read))

@app.route('/messages/send', methods=['GET','POST'])
@login_required
def send_message():
    user = current_user()
    if request.method=='POST':
        db.session.add(Message(sender_id=user.id,recipient_id=int(request.form['recipient_id']),
                               subject=request.form['subject'],body=request.form['body']))
        db.session.commit(); flash('Message sent!','success'); return redirect(url_for('messages'))
    if user.role=='student':
        s=Student.query.filter_by(user_id=user.id).first()
        tids=[r[0] for r in db.session.query(TeacherSubject.teacher_id).filter_by(stream_id=s.stream_id if s else None).distinct().all()]
        recipients=User.query.filter(User.role.in_(['admin','superadmin']),User.is_active==True).all()+User.query.filter(User.id.in_(tids),User.is_active==True).all()
    elif user.role=='parent':
        children=Student.query.filter_by(parent_id=user.id,is_active=True).all()
        sids=[c.stream_id for c in children if c.stream_id]
        tids=[r[0] for r in db.session.query(TeacherSubject.teacher_id).filter(TeacherSubject.stream_id.in_(sids)).distinct().all()]
        recipients=User.query.filter(User.role.in_(['admin','superadmin']),User.is_active==True).all()+User.query.filter(User.id.in_(tids),User.is_active==True).all()
    elif user.role=='teacher':
        sids=teacher_stream_ids(user.id)
        students=Student.query.filter(Student.stream_id.in_(sids),Student.is_active==True).all()
        pids=list({s.parent_id for s in students if s.parent_id})
        recipients=User.query.filter(User.role.in_(['admin','superadmin']),User.is_active==True).all()+User.query.filter(User.id.in_(pids)).all()
    else: recipients=User.query.filter(User.id!=user.id,User.is_active==True).all()
    return render_template('send_message.html', users=recipients)

@app.route('/messages/<int:id>/read')
@login_required
def read_message(id):
    m=Message.query.get_or_404(id)
    if m.recipient_id==session['user_id']: m.is_read=True; db.session.commit()
    return render_template('read_message.html', message=m)

@app.route('/messages/<int:id>/delete', methods=['POST'])
@login_required
def delete_message(id):
    m=Message.query.get_or_404(id)
    if m.recipient_id==session['user_id'] or m.sender_id==session['user_id'] or is_superadmin():
        db.session.delete(m); db.session.commit(); flash('Message deleted.','success')
    return redirect(url_for('messages'))

# ── SUBJECTS ──────────────────────────────────────────────────────────────────

@app.route('/subjects')
@login_required
@role_required('superadmin','admin','teacher')
def subjects():
    return render_template('subjects.html', subjects=Subject.query.all())

@app.route('/subjects/add', methods=['GET','POST'])
@login_required
@role_required('superadmin','admin')
def add_subject():
    if request.method=='POST':
        db.session.add(Subject(name=request.form['name'],code=request.form['code'],
                               category=request.form['category'],is_compulsory='is_compulsory' in request.form))
        db.session.commit(); flash(f"Subject added!",'success'); return redirect(url_for('subjects'))
    return render_template('add_subject.html')

@app.route('/subjects/<int:id>/delete', methods=['POST'])
@login_required
@role_required('superadmin')
def delete_subject(id):
    s=Subject.query.get_or_404(id); db.session.delete(s); db.session.commit()
    flash(f'Subject {s.name} deleted.','success'); return redirect(url_for('subjects'))

# ── ADMIN MANAGEMENT ─────────────────────────────────────────────────────────

@app.route('/admins')
@login_required
@role_required('superadmin')
def admins():
    return render_template('admins.html', admins=User.query.filter_by(role='admin',is_active=True).all())

@app.route('/admins/add', methods=['GET','POST'])
@login_required
@role_required('superadmin')
def add_admin():
    if request.method=='POST':
        colors=['#6366f1','#0ea5e9','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899']
        db.session.add(User(username=request.form['username'],email=request.form['email'],phone=request.form.get('phone',''),
                            password_hash=generate_password_hash(request.form['password']),
                            role='admin',full_name=request.form['full_name'],avatar_color=random.choice(colors),
                            can_manage_students='can_manage_students' in request.form,
                            can_manage_teachers='can_manage_teachers' in request.form,
                            can_manage_exams='can_manage_exams' in request.form,
                            can_manage_attendance='can_manage_attendance' in request.form,
                            can_manage_announcements='can_manage_announcements' in request.form,
                            can_manage_timetable='can_manage_timetable' in request.form,
                            can_manage_streams='can_manage_streams' in request.form))
        db.session.commit(); flash(f"Admin created!",'success'); return redirect(url_for('admins'))
    return render_template('add_admin.html')

@app.route('/admins/<int:id>/edit', methods=['GET','POST'])
@login_required
@role_required('superadmin')
def edit_admin(id):
    admin=User.query.get_or_404(id)
    if request.method=='POST':
        admin.full_name=request.form['full_name']; admin.phone=request.form.get('phone','')
        for f in ['can_manage_students','can_manage_teachers','can_manage_exams','can_manage_attendance','can_manage_announcements','can_manage_timetable','can_manage_streams']:
            setattr(admin,f,f in request.form)
        if request.form.get('new_password'): admin.password_hash=generate_password_hash(request.form['new_password'])
        db.session.commit(); flash('Permissions updated!','success'); return redirect(url_for('admins'))
    return render_template('edit_admin.html', admin=admin)

@app.route('/admins/<int:id>/delete', methods=['POST'])
@login_required
@role_required('superadmin')
def delete_admin(id):
    a=User.query.get_or_404(id); a.is_active=False; db.session.commit()
    flash(f'{a.full_name} deactivated.','success'); return redirect(url_for('admins'))

# ── SETTINGS & PROFILE ────────────────────────────────────────────────────────

@app.route('/settings', methods=['GET','POST'])
@login_required
@role_required('superadmin')
def settings():
    school=School.query.first()
    if request.method=='POST':
        if school:
            for f in ['name','motto','address','phone','email','principal']: setattr(school,f,request.form.get(f,''))
            school.founded=request.form.get('founded') or None
        else:
            school=School(**{f:request.form.get(f) for f in ['name','motto','address','phone','email','principal']}); db.session.add(school)
        db.session.commit(); flash('Settings updated!','success'); return redirect(url_for('settings'))
    return render_template('settings.html', school=school)

@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    user=current_user()
    if request.method=='POST':
        user.full_name=request.form['full_name']; user.phone=request.form.get('phone')
        if request.form.get('new_password'):
            if check_password_hash(user.password_hash,request.form['current_password']):
                user.password_hash=generate_password_hash(request.form['new_password']); flash('Password updated!','success')
            else: flash('Current password incorrect.','error'); return redirect(url_for('profile'))
        db.session.commit(); session['full_name']=user.full_name; flash('Profile updated!','success')
        return redirect(url_for('profile'))
    return render_template('profile.html', user=user)

# ── API ───────────────────────────────────────────────────────────────────────

@app.route('/api/students-by-stream/<int:stream_id>')
@login_required
def api_students(stream_id):
    user=current_user()
    if user.role=='teacher' and stream_id not in teacher_stream_ids(user.id): return jsonify([])
    return jsonify([{'id':s.id,'name':s.user.full_name,'adm_no':s.adm_no}
                    for s in Student.query.filter_by(stream_id=stream_id,is_active=True).all()])

# ─── AI TEACHING ASSISTANT (GROQ) ───────────────────────────────────────────

@app.route('/ai-assistant', methods=['GET','POST'])
@login_required
@role_required('superadmin','admin','teacher')
def ai_assistant():
    response_text = None
    error_msg     = None
    form_data     = {}

    if request.method == 'POST':
        # Get API key from environment variable
        api_key = os.environ.get('GROQ_API_KEY')
        if not api_key:
            error_msg = 'GROQ_API_KEY environment variable not set. Please set it and restart the app.'
            return render_template('ai_assistant.html', response=None, error=error_msg, form_data={})

        task       = request.form.get('task','lesson_plan')
        subject    = request.form.get('subject','').strip()
        grade      = request.form.get('grade','').strip()
        topic      = request.form.get('topic','').strip()
        duration   = request.form.get('duration','40 minutes').strip()
        objectives = request.form.get('objectives','').strip()
        extra      = request.form.get('extra','').strip()
        form_data  = dict(task=task, subject=subject, grade=grade,
                          topic=topic, duration=duration, objectives=objectives, extra=extra)

        task_labels = {
            'lesson_plan':'Lesson Plan','scheme':'Scheme of Work','notes':'Student Notes',
            'exam':'Exam / Quiz Paper','marking_scheme':'Marking Scheme',
            'report_comments':'Report Card Comments','homework':'Homework Questions',
            'activity':'Classroom Activity','revision':'Revision Materials',
            'performance':'Performance Analysis','remedial':'Remedial Recommendations',
            'parent_letter':'Parent Communication Draft'
        }
        task_label = task_labels.get(task, task)

        system_prompt = (
            "You are an expert AI Teaching Assistant for Kenyan schools.\n"
            "Your role is to help teachers save time while improving lesson delivery, "
            "assessment quality, and student performance.\n\n"
            "When responding:\n"
            "- Follow the Kenyan CBC (Competency Based Curriculum) framework\n"
            "- Be concise, practical, and classroom-ready\n"
            "- Generate well-structured educational content\n"
            "- Adapt to the stated grade/class level\n"
            "- Include engaging classroom activities where appropriate\n"
            "- Support both low-resource and digital classrooms\n"
            "- Use clear, simple English unless advanced terminology is required\n"
            "- Format all outputs with clear headings, bullet points, and tables\n\n"
            "Always produce professional, complete, ready-to-use content."
        )

        missing = [x for x,v in [('subject',subject),('grade/class',grade),('topic',topic)] if not v]
        needs_details = missing and task not in ('report_comments','parent_letter','performance','remedial')

        if needs_details:
            user_prompt = (
                f"Generate a {task_label} for a Kenyan CBC school.\n"
                f"The teacher has not specified: {', '.join(missing)}.\n"
                "Please ask for these details first, then provide the content once clarified.\n"
                f"Additional context: {extra or 'None provided.'}"
            )
        else:
            user_prompt = (
                f"Please generate a complete, ready-to-use **{task_label}** with these details:\n\n"
                f"- Subject: {subject or 'Not specified'}\n"
                f"- Grade / Class: {grade or 'Not specified'}\n"
                f"- Topic: {topic or 'Not specified'}\n"
                f"- Lesson Duration: {duration}\n"
                f"- Learning Objectives: {objectives or 'Derive from topic'}\n"
                f"- Additional Instructions: {extra or 'None'}\n\n"
                "Follow the Kenyan CBC curriculum framework throughout. "
                "Produce a complete, well-formatted document a teacher can use immediately."
            )

        try:
            client = Groq(api_key=api_key)
            model_name = "llama-3.3-70b-versatile"

            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=3000,
            )
            response_text = response.choices[0].message.content
        except Exception as e:
            err = str(e)
            if 'API key' in err.lower() or 'auth' in err.lower() or 'invalid' in err.lower():
                error_msg = 'Invalid Groq API key. Please check your GROQ_API_KEY environment variable.'
            elif 'quota' in err.lower() or 'rate' in err.lower():
                error_msg = 'Groq API quota exceeded or rate limited. Please try later or check your plan.'
            elif 'connect' in err.lower() or 'network' in err.lower():
                error_msg = 'Network error: cannot reach Groq API. Check your internet connection.'
            else:
                error_msg = f'Groq API error: {err}'

    return render_template('ai_assistant.html', response=response_text, error=error_msg, form_data=form_data)

@app.route('/ai/chat', methods=['POST'])
@login_required
def ai_chat():
    data       = request.get_json(force=True)
    user_msg   = data.get('message','').strip()
    history    = data.get('history',[])
    api_key    = os.environ.get('GROQ_API_KEY')
    if not user_msg:   return jsonify({'error':'Empty message'}), 400
    if not api_key:    return jsonify({'error':'GROQ_API_KEY not set in environment'}), 400

    SYSTEM = """You are EduNexus AI — an intelligent teaching assistant for Kenyan schools following the CBC.

Your role: help teachers save time while improving lesson delivery, assessment quality, and student performance.

Guidelines:
- Follow the Kenyan CBC framework strictly
- Be concise, practical, and classroom-ready
- Generate structured, well-formatted educational content
- Adapt content to the specified grade level (PP1, PP2, Grade 1-6, Form 1-4)
- Include engaging classroom activities
- Support both low-resource and digital classrooms
- Use simple English unless advanced terminology is required

You can help with:
1. Lesson plans (outcomes, materials, activities, assessment)
2. Schemes of work (termly or yearly)
3. Teaching notes and summaries
4. Exams and quizzes (with mark allocation)
5. Marking schemes and rubrics
6. Report card comments (professional and personalised)
7. Homework and assignments
8. Classroom activities and games
9. Revision materials and study guides
10. Student performance analysis
11. Remedial recommendations for struggling learners
12. Parent communication drafts

Format outputs with ## headings, bullet points, and tables where appropriate.
If subject, grade, topic, or duration is missing — ask for it politely before generating."""

    try:
        client = Groq(api_key=api_key)
        model_name = "llama-3.3-70b-versatile"

        messages = [{"role": "system", "content": SYSTEM}]

        for msg in history[-10:]:
            role = msg.get('role')
            if role in ['user', 'assistant']:
                messages.append({"role": role, "content": msg.get('content', '')})

        messages.append({"role": "user", "content": user_msg})

        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.7,
            max_tokens=2000,
        )
        ai_reply = response.choices[0].message.content

        return jsonify({'reply': ai_reply})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── PDF DOWNLOAD (wkhtmltopdf) ──────────────────────────────────────────────
import base64

def get_logo_data_uri():
    logo_path = os.path.join(os.path.dirname(__file__), 'media', 'logo.png')
    if os.path.exists(logo_path):
        with open(logo_path, 'rb') as f:
            logo_data = base64.b64encode(f.read()).decode('utf-8')
        return f'data:image/png;base64,{logo_data}'
    return None

@app.route('/download-pdf', methods=['POST'])
@login_required
def download_pdf():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data received'}), 400

        # Extract data (same as before)
        task = data.get('task', 'Document')
        subject = data.get('subject', '')
        grade = data.get('grade', '')
        topic = data.get('topic', '')
        content_md = data.get('content', '')

        # Clean markdown
        content_md = content_md.replace('\\*', '*').replace('\\_', '_')
        content_html = markdown.markdown(
            content_md,
            extensions=['extra', 'nl2br', 'sane_lists', 'codehilite', 'toc']
        )
        content_html = re.sub(r'<p>\s*</p>', '', content_html)

        # Document title
        title_parts = []
        if task: title_parts.append(task.replace('_', ' ').title())
        if subject: title_parts.append(subject)
        if grade: title_parts.append(f"({grade})")
        if topic: title_parts.append(f"– {topic}")
        doc_title = " ".join(title_parts) if title_parts else "AI Generated Document"

        # School info
        school = School.query.first()
        school_name = school.name if school else "ST. TERESA CHILDREN LEARNING CENTRE"
        school_address = school.address if school and school.address else "P.O BOX 1077 – 20300, NYAHURURU"
        school_phone = school.phone if school and school.phone else "0706 747 155"
        school_email = school.email if school and school.email else "stteresa699@gmail.com"
        school_motto = school.motto if school and school.motto else "Excellence Through Innovation"
        current_date = datetime.now().strftime("%d %B %Y")

        # Logo as base64 data URI
        logo_data_uri = get_logo_data_uri()

        # Render HTML template (pass logo_data_uri instead of logo_url)
        rendered_html = render_template(
            'pdf_template.html',
            doc_title=doc_title,
            school_name=school_name,
            school_address=school_address,
            school_phone=school_phone,
            school_email=school_email,
            school_motto=school_motto,
            logo_data_uri=logo_data_uri,
            current_date=current_date,
            content_html=content_html
        )

        # Generate PDF with WeasyPrint
        pdf_output = HTML(string=rendered_html).write_pdf()

        if not pdf_output or len(pdf_output) < 1000:
            return jsonify({'error': 'Generated PDF is empty or too small'}), 500

        # Safe filename
        safe_title = unicodedata.normalize('NFKD', doc_title).encode('ascii', 'ignore').decode('ascii')
        safe_title = safe_title.replace(" ", "_").replace("/", "_")[:50]
        filename = f"{safe_title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

        response = make_response(pdf_output)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f'PDF generation failed: {str(e)}'}), 500


# ── SEED DATABASE ─────────────────────────────────────────────────────────────

def seed_database():
    if User.query.first(): return
    school=School(name="St. Teresa Children Learning Centre", motto="Excellence Through Innovation",
                  address="P.O BOX 1077 – 20300, NYAHURURU", phone="0706 747 155",
                  email="stteresa699@gmail.com", principal="", founded=2000)
    db.session.add(school)
    superadmin=User(username='superadmin',email='superadmin@nexus.ac.ke',
                    password_hash=generate_password_hash('super123'),
                    role='superadmin',full_name='Super Administrator',avatar_color='#ef4444')
    db.session.add(superadmin)
    limited_admin=User(username='admin',email='admin@nexus.ac.ke',
                       password_hash=generate_password_hash('admin123'),
                       role='admin',full_name='Office Administrator',avatar_color='#6366f1',
                       can_manage_students=True,can_manage_teachers=False,can_manage_exams=True,
                       can_manage_attendance=True,can_manage_announcements=True,
                       can_manage_timetable=False,can_manage_streams=False)
    db.session.add(limited_admin); db.session.flush()
    subjects_data=[('Mathematics','MAT','Sciences',True),('English','ENG','Languages',True),
                   ('Kiswahili','KIS','Languages',True),('Biology','BIO','Sciences',False),
                   ('Chemistry','CHE','Sciences',False),('Physics','PHY','Sciences',False),
                   ('History','HIS','Humanities',False),('Geography','GEO','Humanities',False),
                   ('Computer Studies','CMP','Technical',False),('Business Studies','BST','Commercial',False)]
    subjects=[]
    for name,code,cat,comp in subjects_data:
        s=Subject(name=name,code=code,category=cat,is_compulsory=comp); db.session.add(s); subjects.append(s)
    db.session.flush()
    teacher_data=[('Alice Mwangi','alice@nexus.ac.ke','#10b981'),('John Ochieng','john@nexus.ac.ke','#f59e0b'),
                  ('Mary Njeri','mary@nexus.ac.ke','#ec4899'),('David Kamau','david@nexus.ac.ke','#0ea5e9'),
                  ('Sarah Akinyi','sarah@nexus.ac.ke','#8b5cf6')]
    teachers=[]
    for i,(name,email,color) in enumerate(teacher_data):
        t=User(username=f'teacher{i+1}',email=email,password_hash=generate_password_hash('teacher123'),
               role='teacher',full_name=name,avatar_color=color); db.session.add(t); teachers.append(t)
    db.session.flush()
    stream_data=[('Form 1 A','Form 1'),('Form 1 B','Form 1'),('Form 2 A','Form 2'),
                 ('Form 2 B','Form 2'),('Form 3 A','Form 3'),('Form 4 A','Form 4')]
    streams=[]
    for i,(name,grade) in enumerate(stream_data):
        s=Stream(name=name,grade=grade,capacity=45,class_teacher_id=teachers[i%len(teachers)].id)
        db.session.add(s); streams.append(s)
    db.session.flush()
    # Assign teachers to streams (each teacher gets 1-2 streams, 3 subjects each)
    for i,teacher in enumerate(teachers):
        for j,stream in enumerate(streams):
            if j%len(teachers)==i:
                for subj in subjects[:3]:
                    db.session.add(TeacherSubject(teacher_id=teacher.id,subject_id=subj.id,stream_id=stream.id))
    db.session.flush()
    parents=[]
    for i in range(10):
        p=User(username=f'parent{i+1}',email=f'parent{i+1}@mail.com',
               password_hash=generate_password_hash('parent123'),role='parent',
               full_name=f'Parent {i+1} Family',avatar_color=random.choice(['#6366f1','#0ea5e9','#10b981','#f59e0b','#ef4444']))
        db.session.add(p); parents.append(p)
    db.session.flush()
    first_names=['James','Grace','Kevin','Faith','Brian','Mercy','Alex','Diana','Peter','Joyce','Samuel','Lydia','Daniel','Esther','Michael','Ruth','Joseph','Naomi','David','Mary']
    last_names=['Mwangi','Ochieng','Njeri','Kamau','Akinyi','Wanjiku','Otieno','Mutua','Kariuki','Nyambura']
    students_list=[]
    for i in range(40):
        adm=f"ADM{2024}{1000+i}"
        u=User(username=adm.lower(),email=f'student{i+1}@nexus.ac.ke',password_hash=generate_password_hash('student123'),
               role='student',full_name=f"{random.choice(first_names)} {random.choice(last_names)}",
               avatar_color=random.choice(['#6366f1','#0ea5e9','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899']))
        db.session.add(u); db.session.flush()
        s=Student(adm_no=adm,user_id=u.id,stream_id=streams[i%len(streams)].id,parent_id=parents[i%len(parents)].id,
                  gender=random.choice(['Male','Female']),dob=date(2008+random.randint(0,2),random.randint(1,12),random.randint(1,28)),
                  kcpe_marks=random.randint(250,450))
        db.session.add(s); students_list.append(s)
    db.session.flush()
    exams_data=[('Term 1 CAT 2024','Term 1',2024,'CAT'),('Term 1 Mid-Term 2024','Term 1',2024,'Mid-Term'),
                ('Term 1 End-Term 2024','Term 1',2024,'End-Term'),('Term 2 CAT 2024','Term 2',2024,'CAT')]
    exams=[]
    for name,term,year,etype in exams_data:
        e=Exam(name=name,term=term,year=year,exam_type=etype); db.session.add(e); exams.append(e)
    db.session.flush()
    for student in students_list:
        for exam in exams:
            for subj in subjects[:6]:
                marks=round(max(10,min(100,random.gauss(62,15))),1)
                db.session.add(Result(student_id=student.id,exam_id=exam.id,subject_id=subj.id,marks=marks,grade=get_grade(marks),entered_by=superadmin.id))
    for student in students_list:
        for i in range(14):
            d=date.today()-timedelta(days=i)
            if d.weekday()<5:
                db.session.add(Attendance(student_id=student.id,stream_id=student.stream_id,date=d,
                                          status=random.choices(['present','absent','late'],weights=[85,10,5])[0],recorded_by=superadmin.id))
    # Sample Assignments
    for i,teacher in enumerate(teachers[:3]):
        ts=TeacherSubject.query.filter_by(teacher_id=teacher.id).first()
        if ts:
            db.session.add(Assignment(title=f"Chapter {i+3} Practice — {ts.subject.name}",
                                      description=f"Complete all exercises in chapter {i+3}. Show all workings clearly and submit neatly written.",
                                      subject_id=ts.subject_id,stream_id=ts.stream_id,teacher_id=teacher.id,
                                      due_date=date.today()+timedelta(days=random.randint(3,14)),max_marks=50))
    for title,content,audience,priority in [
        ('Welcome Back!','Welcome to a new term. Let us make it count!','all','high'),
        ('Sports Day','Annual sports day is scheduled for next Friday.','all','normal'),
        ('Staff Meeting','Mandatory staff meeting Thursday 4PM in the staffroom.','teachers','urgent'),
        ('Parent-Teacher Conference','PTA meeting Saturday 10AM.','parents','high'),
        ('End-Term Exams','End of term exams begin next week. Prepare well!','students','urgent')]:
        db.session.add(Announcement(title=title,content=content,audience=audience,priority=priority,author_id=superadmin.id))
    for title,desc,edate,etype,venue in [
        ('Annual Sports Day','Inter-house athletics',date.today()+timedelta(days=7),'sports','School Grounds'),
        ('Science Fair','Student science projects',date.today()+timedelta(days=14),'academic','Hall A'),
        ('Graduation Ceremony','Form 4 Graduation',date.today()+timedelta(days=30),'academic','Main Hall'),
        ('Cultural Day','Celebrating our cultures',date.today()+timedelta(days=21),'cultural','School Compound')]:
        db.session.add(Event(title=title,description=desc,event_date=edate,event_type=etype,venue=venue,created_by=superadmin.id))
    db.session.commit()
    print("✅ Database seeded!")

with app.app_context():
    db.create_all()
    seed_database()

if __name__ == '__main__':
    app.run(debug=True, port=5000)