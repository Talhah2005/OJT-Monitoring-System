from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField
from wtforms.validators import DataRequired, Length, Email, EqualTo
import pyodbc
import os
import qrcode
from io import BytesIO
import base64
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
import jinja2
from werkzeug.utils import secure_filename
import json
import hashlib


load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY') or 'your-secret-key-here'

# Enable template auto-reload and debug
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['DEBUG'] = True
app.jinja_env.cache = {}

# Database configuration
def get_db_connection():
    try:
        conn = pyodbc.connect(
            'Driver={SQL Server};'
            'Server=DESKTOP-FDTP2UC\\SQLEXPRESS;'  # From your screenshot
            'Database=JobTrainingMonitoring;'
            'Trusted_Connection=yes;'
            'Encrypt=no;'
        )
        return conn
    except pyodbc.Error as e:
        app.logger.error(f"Database connection failed: {str(e)}")
        raise
# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    pass

@login_manager.user_loader
def load_user(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, role FROM Users WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()
        if not user_data:
            return None
        user = User()
        user.id = user_data.user_id
        user.username = user_data.username
        user.role = user_data.role
        return user
    except Exception as e:
        app.logger.error(f"Error loading user: {str(e)}")
        return None
    finally:
        if 'conn' in locals():
            conn.close()

# Forms
class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=25)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=6, message='Password must be at least 6 characters')
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match')
    ])
    full_name = StringField('Full Name', validators=[DataRequired()])
    department = StringField('Department', validators=[DataRequired()])
    position = StringField('Position')
    role = SelectField('Role', choices=[
        ('trainee', 'Trainee'),
        ('supervisor', 'Supervisor'),
        ('admin', 'Admin')
    ], validators=[DataRequired()])
    submit = SubmitField('Register')

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    try:
        return render_template('404.html'), 404
    except jinja2.exceptions.TemplateNotFound:
        return "<h1>404 - Page Not Found</h1><p>The page you requested could not be found.</p>", 404

@app.errorhandler(500)
def internal_server_error(e):
    try:
        return render_template('500.html'), 500
    except jinja2.exceptions.TemplateNotFound:
        return "<h1>500 - Server Error</h1><p>Something went wrong on our end.</p>", 500

@app.errorhandler(jinja2.exceptions.TemplateNotFound)
def handle_template_not_found(e):
    app.logger.error(f"Template not found: {e}")
    try:
        return render_template('500.html'), 500
    except:
        return "<h1>Template Error</h1><p>Required template file missing.</p>", 500

# Routes

@app.route('/')
def home():
    try:
        return render_template('home.html')
    except jinja2.exceptions.TemplateNotFound as e:
        app.logger.error(f"Home template missing: {e}")
        return "<h1>Welcome</h1><p>Home page is under construction.</p>"

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # First check in Users table
            cursor.execute("""
                SELECT u.user_id, u.username, u.password, u.role, u.department,
                       COALESCE(t.trainee_id, NULL) as trainee_id
                FROM Users u
                LEFT JOIN Trainees t ON u.user_id = t.user_id
                WHERE u.username = ? OR u.email = ?
            """, (form.username.data, form.username.data))
            
            user_data = cursor.fetchone()
            
            if user_data and user_data.password == form.password.data:
                user = User()
                user.id = user_data.user_id
                user.username = user_data.username
                user.role = user_data.role
                user.department = user_data.department
                if user_data.role == 'trainee':
                    user.trainee_id = user_data.trainee_id
                
                login_user(user)
                flash('Login successful!', 'success')
                return redirect(url_for('dashboard'))
            
            flash('Invalid username or password', 'danger')
        except Exception as e:
            flash('Login error occurred', 'danger')
            app.logger.error(f"Login error: {str(e)}", exc_info=True)
        finally:
            if 'conn' in locals():
                conn.close()
    
    return render_template('auth/login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = RegistrationForm()
    conn = None
    try:
        if form.validate_on_submit():
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT user_id FROM Users WHERE username = ? OR email = ?
                UNION
                SELECT user_id FROM Trainees WHERE email = ?
                UNION
                SELECT user_id FROM Admins WHERE email = ?
                UNION
                SELECT user_id FROM Supervisors WHERE email = ?
            """, (form.username.data, form.email.data, form.email.data, form.email.data, form.email.data))
            if cursor.fetchone():
                flash('Username or email already exists', 'danger')
                return redirect(url_for('register'))
            cursor.execute("""
                INSERT INTO Users (username, password, email, role, department)
                VALUES (?, ?, ?, ?, ?)
            """, (form.username.data, form.password.data, form.email.data, form.role.data, form.department.data))
            cursor.execute("SELECT @@IDENTITY AS user_id")
            user_id = cursor.fetchone().user_id
            if form.role.data == 'trainee':
                cursor.execute("""
                    INSERT INTO Trainees (
                        user_id, full_name, password, email, position, training_status
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (user_id, form.full_name.data, form.password.data, form.email.data, form.position.data, 'Not Started'))
            elif form.role.data == 'admin':
                cursor.execute("""
                    INSERT INTO Admins (
                        user_id, full_name, email, position, department
                    ) VALUES (?, ?, ?, ?, ?)
                """, (user_id, form.full_name.data, form.email.data, form.position.data, form.department.data))
            elif form.role.data == 'supervisor':
                cursor.execute("""
                    INSERT INTO Supervisors (
                        user_id, full_name, email, position, department
                    ) VALUES (?, ?, ?, ?, ?)
                """, (user_id, form.full_name.data, form.email.data, form.position.data, form.department.data))
            conn.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
    except pyodbc.Error as e:
        if conn: conn.rollback()
        flash(f'Database error: {str(e)}', 'danger')  # Show actual error
        app.logger.error(f"Registration error: {str(e)}", exc_info=True)
    except Exception as e:
        if conn: conn.rollback()
        flash(f'Registration failed: {str(e)}', 'danger')  # Show actual error
        app.logger.error(f"Unexpected error: {str(e)}", exc_info=True)
    finally:
        if conn: conn.close()
    try:
        return render_template('auth/register.html', form=form)
    except jinja2.exceptions.TemplateNotFound:
        return """
        <form method="POST">
            <h2>Register</h2>
            <div>
                <label>Username: <input type="text" name="username" required></label>
            </div>
            <!-- Add all other registration fields similarly -->
            <button type="submit">Register</button>
        </form>
        """

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if current_user.role == 'trainee':
            # First get trainee details
            cursor.execute("""
                SELECT t.trainee_id, t.full_name, t.position, t.training_status,
                       u.department
                FROM Trainees t
                JOIN Users u ON t.user_id = u.user_id
                WHERE t.user_id = ?
            """, (current_user.id,))
            
            trainee_data = cursor.fetchone()
            if not trainee_data:
                flash('Trainee profile not found', 'danger')
                return redirect(url_for('logout'))
            
            # Get trainee's today's attendance using CheckIns table
            cursor.execute("""
                SELECT TOP 1
                    checkin_time,
                    checkout_time,
                    location
                FROM CheckIns
                WHERE trainee_id = ?
                AND CAST(checkin_time AS DATE) = CAST(GETDATE() AS DATE)
                ORDER BY checkin_time DESC
            """, (trainee_data.trainee_id,))
            today_attendance = cursor.fetchone()
            
            # Get trainee's tasks
            cursor.execute("""
                SELECT task_id, task_name, is_completed, task_type, task_url
                FROM TraineeTasks
                WHERE user_id = ?
                ORDER BY task_id DESC
            """, (current_user.id,))
            tasks = cursor.fetchall()
            
            # Generate QR code data
            qr_code_url = url_for('get_qr_code', _external=True)
            
            return render_template('dashboard/trainee_dashboard.html',
                                trainee=trainee_data,
                                today_attendance=today_attendance,
                                tasks=tasks,
                                qr_code_url=qr_code_url)
        
        elif current_user.role == 'supervisor':
            # Get supervisor's trainees
            cursor.execute("""
                SELECT t.user_id, t.full_name, t.email, t.position, t.training_status
                FROM Trainees t
                JOIN Supervisors s ON t.supervisor_id = s.supervisor_id
                WHERE s.user_id = ?
            """, (current_user.id,))
            trainees = cursor.fetchall()
            
            # Get recent tasks assigned by this supervisor
            cursor.execute("""
                SELECT tt.task_id, tt.task_name, tt.task_type, tt.is_completed, 
                       t.full_name as trainee_name
                FROM TraineeTasks tt
                JOIN Trainees t ON tt.user_id = t.user_id
                JOIN Supervisors s ON t.supervisor_id = s.supervisor_id
                WHERE s.user_id = ?
                ORDER BY tt.task_id DESC
            """, (current_user.id,))
            recent_tasks = cursor.fetchall()
            
            return render_template('dashboard/supervisor_dashboard.html',
                                 trainees=trainees,
                                 recent_tasks=recent_tasks)
        
        elif current_user.role == 'admin':
            # Get all users count
            cursor.execute("SELECT COUNT(*) FROM Users")
            total_users = cursor.fetchone()[0]
            
            # Get trainees count
            cursor.execute("SELECT COUNT(*) FROM Users WHERE role = 'trainee'")
            total_trainees = cursor.fetchone()[0]
            
            # Get supervisors count
            cursor.execute("SELECT COUNT(*) FROM Users WHERE role = 'supervisor'")
            total_supervisors = cursor.fetchone()[0]
            
            # Get recent users
            cursor.execute("""
                SELECT u.user_id, u.username, u.email, u.role, 
                       COALESCE(t.full_name, s.full_name, a.full_name) as full_name
                FROM Users u
                LEFT JOIN Trainees t ON u.user_id = t.user_id
                LEFT JOIN Supervisors s ON u.user_id = s.user_id
                LEFT JOIN Admins a ON u.user_id = a.user_id
                ORDER BY u.user_id DESC
            """)
            recent_users = cursor.fetchall()
            
            return render_template('dashboard/admin_dashboard.html',
                                total_users=total_users,
                                total_trainees=total_trainees,
                                total_supervisors=total_supervisors,
                                recent_users=recent_users)
        
        flash('Invalid user role', 'danger')
        return redirect(url_for('logout'))
        
    except Exception as e:
        app.logger.error(f"Dashboard error: {str(e)}", exc_info=True)
        flash('Error loading dashboard: ' + str(e), 'danger')
        return render_template('dashboard/error_dashboard.html', error=str(e))
    finally:
        if 'conn' in locals():
            conn.close()


@app.route('/admin/assign_trainee', methods=['POST'])
@login_required
def admin_assign_trainee():
    if current_user.role != 'admin':
        flash('Unauthorized access', 'danger')
        return redirect(url_for('dashboard'))

    trainee_id = request.form.get('trainee_id')
    supervisor_id = request.form.get('supervisor_id')

    if not trainee_id or not supervisor_id:
        flash('Please select both trainee and supervisor.', 'warning')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Get supervisor's department and supervisor_id (from Supervisors table)
        cursor.execute("""
            SELECT s.supervisor_id, s.department 
            FROM Supervisors s
            JOIN Users u ON s.user_id = u.user_id
            WHERE u.user_id = ?
        """, (supervisor_id,))
        sup_data = cursor.fetchone()
        
        if not sup_data:
            flash('Invalid supervisor selected.', 'danger')
            return redirect(url_for('dashboard'))

        supervisor_db_id = sup_data.supervisor_id
        department = sup_data.department

        # Update trainee record in both Users and Trainees tables
        cursor.execute("""
            UPDATE Users 
            SET department = ? 
            WHERE user_id = ? AND role = 'trainee'
        """, (department, trainee_id))

        cursor.execute("""
            UPDATE Trainees 
            SET department = ?, supervisor_id = ?
            WHERE user_id = ?
        """, (department, supervisor_db_id, trainee_id))

        conn.commit()
        flash('Trainee assigned to supervisor successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error assigning trainee: {str(e)}', 'danger')
        app.logger.error(f"Error assigning trainee: {str(e)}", exc_info=True)
    finally:
        conn.close()

    return redirect(url_for('dashboard'))



@app.route('/admin/add_trainee', methods=['POST'])
@login_required
def admin_add_trainee():
    if current_user.role != 'admin':
        flash('Unauthorized access', 'danger')
        return redirect(url_for('dashboard'))

    full_name = request.form.get('full_name')
    email = request.form.get('email')
    username = request.form.get('username')
    password = request.form.get('password')
    position = request.form.get('position')
    supervisor_id = request.form.get('supervisor_id')

    if not all([full_name, email, username, password, position, supervisor_id]):
        flash('Please fill all required fields.', 'warning')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if username or email exists
        cursor.execute("""
            SELECT user_id FROM Users WHERE username = ? OR email = ?
        """, (username, email))
        if cursor.fetchone():
            flash('Username or email already exists.', 'danger')
            return redirect(url_for('dashboard'))

        # Get supervisor's department
        cursor.execute("""
            SELECT s.department 
            FROM Supervisors s
            JOIN Users u ON s.user_id = u.user_id
            WHERE u.user_id = ?
        """, (supervisor_id,))
        sup_dept = cursor.fetchone()
        if not sup_dept:
            flash('Invalid supervisor selected.', 'danger')
            return redirect(url_for('dashboard'))

        department = sup_dept.department

        # Insert into Users table
        cursor.execute("""
            INSERT INTO Users (username, password, email, role, department)
            VALUES (?, ?, ?, 'trainee', ?)
        """, (username, password, email, department))
        cursor.execute("SELECT @@IDENTITY AS user_id")
        user_id = cursor.fetchone().user_id

        # Insert into Trainees table
        cursor.execute("""
            INSERT INTO Trainees (
                user_id, full_name, password, email, position, department, training_status
            ) VALUES (?, ?, ?, ?, ?, ?, 'Not Started')
        """, (user_id, full_name, password, email, position, department))

        conn.commit()
        flash(f'Trainee {full_name} added successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error adding trainee: {str(e)}', 'danger')
        app.logger.error(f"Error adding trainee: {str(e)}", exc_info=True)
    finally:
        conn.close()

    return redirect(url_for('dashboard'))


@app.route('/trainee/update-task/<int:task_id>', methods=['POST'])
@login_required
def update_task(task_id):
    if current_user.role != 'trainee':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE TraineeTasks SET is_completed = 1 WHERE task_id = ? AND user_id = ?", (task_id, current_user.id))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        app.logger.error(f"Task update error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/submit_quiz/<int:task_id>', methods=['POST'])
@login_required
def submit_quiz(task_id):
    if current_user.role != 'trainee':
        flash("Unauthorized access", "danger")
        return redirect(url_for('dashboard'))
    # Implement grading logic here if needed; currently marks complete
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE TraineeTasks SET is_completed = 1 WHERE task_id = ? AND user_id = ?", (task_id, current_user.id))
        conn.commit()
        flash("Quiz submitted successfully!", "success")
    except Exception as e:
        flash(f"Error submitting quiz: {str(e)}", "danger")
    finally:
        conn.close()
    return redirect(url_for('dashboard'))

@app.route('/admin/add-user', methods=['POST'])
@login_required
def add_user():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    form = RegistrationForm()
    if form.validate_on_submit():
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT user_id FROM Users WHERE username = ? OR email = ?
            """, (form.username.data, form.email.data))
            if cursor.fetchone():
                flash('Username or email already exists', 'danger')
                return redirect(url_for('dashboard'))
            cursor.execute("""
                INSERT INTO Users (username, password, email, role, department)
                VALUES (?, ?, ?, ?, ?)
            """, (form.username.data, form.password.data, form.email.data, form.role.data, form.department.data))
            cursor.execute("SELECT @@IDENTITY AS user_id")
            user_id = cursor.fetchone().user_id
            if form.role.data == 'trainee':
                cursor.execute("""
                    INSERT INTO Trainees (
                        user_id, full_name, password, email, position, training_status
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (user_id, form.full_name.data, form.password.data, form.email.data, form.position.data, 'Not Started'))
            elif form.role.data == 'admin':
                cursor.execute("""
                    INSERT INTO Admins (
                        user_id, full_name, email, position, department
                    ) VALUES (?, ?, ?, ?, ?)
                """, (user_id, form.full_name.data, form.email.data, form.position.data, form.department.data))
            elif form.role.data == 'supervisor':
                cursor.execute("""
                    INSERT INTO Supervisors (
                        user_id, full_name, email, position, department
                    ) VALUES (?, ?, ?, ?, ?)
                """, (user_id, form.full_name.data, form.email.data, form.position.data, form.department.data))
            conn.commit()
            flash('User added successfully!', 'success')
        except Exception as e:
            if conn:
                conn.rollback()
            flash(f'Error adding user: {str(e)}', 'danger')
            app.logger.error(f"Add user error: {str(e)}", exc_info=True)
        finally:
            if conn:
                conn.close()
    return redirect(url_for('dashboard'))

@app.route('/admin/update-user/<int:user_id>', methods=['POST'])
@login_required
def update_user(user_id):
    if current_user.role != 'admin':
        flash('Unauthorized access', 'danger')
        return redirect(url_for('dashboard'))
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT u.role, u.username, u.email, u.department,
                   COALESCE(a.full_name, s.full_name, t.full_name) AS full_name,
                   COALESCE(a.position, s.position, t.position) AS position
            FROM Users u
            LEFT JOIN Admins a ON u.user_id = a.user_id
            LEFT JOIN Supervisors s ON u.user_id = s.user_id
            LEFT JOIN Trainees t ON u.user_id = t.user_id
            WHERE u.user_id = ?
        """, (user_id,))
        user_data = cursor.fetchone()
        if not user_data:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        old_role = user_data.role
        new_role = request.form.get('role') or old_role
        username = request.form.get('username') or user_data.username
        email = request.form.get('email') or user_data.email
        department = request.form.get('department') or user_data.department
        full_name = request.form.get('full_name') or user_data.full_name
        position = request.form.get('position') or user_data.position
        new_password = request.form.get('password')
        cursor.execute("""
            UPDATE Users 
            SET username = ?, email = ?, role = ?, department = ?
            WHERE user_id = ?
        """, (username, email, new_role, department, user_id))
        if new_password:
            cursor.execute("UPDATE Users SET password = ? WHERE user_id = ?", (new_password, user_id))
        if old_role != new_role:
            if old_role == 'trainee':
                cursor.execute("DELETE FROM Trainees WHERE user_id = ?", (user_id,))
            elif old_role == 'supervisor':
                cursor.execute("DELETE FROM Supervisors WHERE user_id = ?", (user_id,))
            elif old_role == 'admin':
                cursor.execute("DELETE FROM Admins WHERE user_id = ?", (user_id,))
        def upsert_role_table(table_name):
            cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE user_id = ?", (user_id,))
            exists = cursor.fetchone()[0] > 0
            if exists:
                if table_name == 'Trainees':
                    if new_password:
                        cursor.execute("""
                            UPDATE Trainees SET full_name = ?, email = ?, position = ?, password = ?
                            WHERE user_id = ?
                        """, (full_name, email, position, new_password, user_id))
                    else:
                        cursor.execute("""
                            UPDATE Trainees SET full_name = ?, email = ?, position = ?
                            WHERE user_id = ?
                        """, (full_name, email, position, user_id))
                else:
                    cursor.execute(f"""
                        UPDATE {table_name} SET full_name = ?, email = ?, position = ?, department = ?
                        WHERE user_id = ?
                    """, (full_name, email, position, department, user_id))
            else:
                if table_name == 'Trainees':
                    cursor.execute("""
                        INSERT INTO Trainees (user_id, full_name, email, password, position, training_status)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (user_id, full_name, email, new_password or '', position, 'Not Started'))
                else:
                    cursor.execute(f"""
                        INSERT INTO {table_name} (user_id, full_name, email, position, department)
                        VALUES (?, ?, ?, ?, ?)
                    """, (user_id, full_name, email, position, department))
        if new_role == 'trainee':
            upsert_role_table('Trainees')
        elif new_role == 'supervisor':
            upsert_role_table('Supervisors')
        elif new_role == 'admin':
            upsert_role_table('Admins')
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        app.logger.error(f"Update user error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        flash('Unauthorized access', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1) look up role
        cursor.execute("SELECT role FROM Users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            flash('User not found', 'danger')
            return redirect(url_for('dashboard'))
        role = row[0]

        # 2) delete any dependent TraineeTasks first
        #    (this is the table causing your FK conflict)
        cursor.execute("DELETE FROM TraineeTasks WHERE user_id = ?", (user_id,))

        # 3) delete from the role‐specific table
        if role == 'trainee':
            cursor.execute("DELETE FROM Trainees WHERE user_id = ?", (user_id,))
        elif role == 'supervisor':
            cursor.execute("DELETE FROM Supervisors WHERE user_id = ?", (user_id,))
        elif role == 'admin':
            cursor.execute("DELETE FROM Admins WHERE user_id = ?", (user_id,))

        # 4) finally delete from Users
        cursor.execute("DELETE FROM Users WHERE user_id = ?", (user_id,))

        conn.commit()
        flash('User and related tasks deleted successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting user: {e}', 'danger')
        app.logger.error(f"Delete user error: {e}", exc_info=True)
    finally:
        conn.close()

    return redirect(url_for('dashboard'))


@app.route('/trainee/upload-assignment/<int:task_id>', methods=['POST'])
@login_required
def upload_assignment(task_id):
    if current_user.role != 'trainee':
        flash("Unauthorized", "danger")
        return redirect(url_for('dashboard'))

    file = request.files.get('assignment_file')
    if not file:
        flash("No file selected", "warning")
        return redirect(request.url)

    # Save file
    filename = secure_filename(file.filename)
    user_folder = os.path.join('uploads', str(current_user.id))
    os.makedirs(user_folder, exist_ok=True)
    filepath = os.path.join(user_folder, filename)
    file.save(filepath)

    # Mark task as complete in DB
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE TraineeTasks SET is_completed = 1 WHERE task_id = ? AND user_id = ?", (task_id, current_user.id))
    conn.commit()
    conn.close()

    flash("Assignment uploaded successfully!", "success")
    return redirect(url_for('dashboard'))

@app.route('/trainee/mark-attendance/<int:task_id>')
@login_required
def mark_attendance(task_id):
    if current_user.role != 'trainee':
        flash("Unauthorized", "danger")
        return redirect(url_for('dashboard'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE TraineeTasks SET is_completed = 1 WHERE task_id = ? AND user_id = ?", (task_id, current_user.id))
        conn.commit()
    except Exception as e:
        flash(f"Error marking attendance: {str(e)}", "danger")
    finally:
        conn.close()

    flash("Workshop attendance recorded!", "success")
    return redirect(url_for('dashboard'))

@app.route('/supervisor/trainee/<int:trainee_id>/assign-task', methods=['POST'])
@login_required
def assign_task(trainee_id):
    if current_user.role != 'supervisor':
        flash('Unauthorized access', 'danger')
        return redirect(url_for('home'))

    task_name = request.form.get('task_name')
    task_type = request.form.get('task_type')
    task_url = request.form.get('task_url')

    if not task_name or not task_type:
        flash('Task name and type are required.', 'warning')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO TraineeTasks (user_id, task_name, task_type, task_url, is_completed)
            VALUES (?, ?, ?, ?, 0)
        """, (trainee_id, task_name, task_type, task_url))
        conn.commit()
        flash('Task assigned successfully.', 'success')
    except Exception as e:
        conn.rollback()
        app.logger.error(f"Assign task error: {e}", exc_info=True)
        flash('Failed to assign task.', 'danger')
    finally:
        conn.close()

    return redirect(url_for('dashboard'))

@app.route('/supervisor/trainee/<int:trainee_id>/tasks', methods=['GET'])
@login_required
def view_trainee_tasks(trainee_id):
    if current_user.role != 'supervisor':
        flash('Unauthorized access', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get trainee details
        cursor.execute("SELECT * FROM Trainees WHERE user_id = ?", (trainee_id,))
        trainee = cursor.fetchone()

        # Get all tasks for this trainee
        cursor.execute("""
            SELECT task_id, task_name, task_type, task_url, is_completed
            FROM TraineeTasks
            WHERE user_id = ?
            ORDER BY is_completed
        """, (trainee_id,))
        tasks = cursor.fetchall()

        # Calculate progress
        total_tasks = len(tasks)
        completed_tasks = sum(1 for t in tasks if t.is_completed)
        progress = int((completed_tasks / total_tasks) * 100) if total_tasks > 0 else 0

        return render_template('view_tasks.html',
                            trainee=trainee,
                            tasks=tasks,
                            progress=progress)

    except Exception as e:
        flash(f'Error loading tasks: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))
    finally:
        conn.close()

def generate_permanent_trainee_qr(trainee_id, full_name, department):
    """Generate a permanent unique QR code for a trainee"""
    # Create a permanent unique identifier for the trainee
    permanent_data = f"{trainee_id}-{full_name}-{department}"
    
    # Create SHA-256 hash of the data
    hash_object = hashlib.sha256(permanent_data.encode())
    hash_hex = hash_object.hexdigest()[:12]  # Take first 12 chars of hash
    
    # Format: TRAINEE-ID-HASH (permanent and unique per trainee)
    return f"TRAINEE-{trainee_id}-{hash_hex}"

@app.route('/trainee/get-qr-code')
@login_required
def get_qr_code():
    if current_user.role != 'trainee':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get trainee details with department from Users table
        cursor.execute("""
            SELECT t.trainee_id, t.full_name, u.department 
            FROM Trainees t 
            JOIN Users u ON t.user_id = u.user_id
            WHERE t.user_id = ?
        """, (current_user.id,))
        trainee_data = cursor.fetchone()
        
        if not trainee_data:
            app.logger.error(f"No trainee found for user_id: {current_user.id}")
            if request.headers.get('Accept') == 'application/json':
                return jsonify({'error': 'Trainee not found'}), 404
            flash('Error: Trainee not found', 'danger')
            return redirect(url_for('dashboard'))

        # Check if trainee already has a permanent QR code
        cursor.execute("""
            SELECT qr_code 
            FROM QRCodes 
            WHERE entity_type = 'trainee' 
            AND entity_id = ? 
            AND is_active = 1
        """, (trainee_data.trainee_id,))
        existing_qr = cursor.fetchone()

        if existing_qr:
            # Use existing permanent QR code
            qr_code = existing_qr.qr_code
        else:
            # Generate new permanent QR code
            qr_code = generate_permanent_trainee_qr(
                trainee_data.trainee_id,
                trainee_data.full_name,
                trainee_data.department
            )
            
            # Insert new permanent QR code (no expiration date for permanent codes)
            cursor.execute("""
                INSERT INTO QRCodes (qr_code, entity_type, entity_id, is_active)
                VALUES (?, 'trainee', ?, 1)
            """, (qr_code, trainee_data.trainee_id))
            
            conn.commit()
            app.logger.info(f"Generated permanent QR code for trainee {trainee_data.trainee_id}: {qr_code}")

        # Create QR code image
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_code)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Save QR code to BytesIO
        img_io = BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        img_data = base64.b64encode(img_io.getvalue()).decode()

        response_data = {
            'qr_image': img_data,
            'full_name': trainee_data.full_name.upper(),
            'department': trainee_data.department,
            'qr_code': qr_code
        }

        # Check if request wants JSON
        if request.headers.get('Accept') == 'application/json':
            return jsonify(response_data)
        
        # Otherwise return the template
        return render_template('qr/trainee_qr.html', **response_data)
    
    except Exception as e:
        app.logger.error(f"QR code generation error: {str(e)}", exc_info=True)
        error_msg = f"Error generating QR code: {str(e)}"
        if request.headers.get('Accept') == 'application/json':
            return jsonify({'error': error_msg}), 500
        flash(error_msg, 'danger')
        return redirect(url_for('dashboard'))
    finally:
        if conn:
            conn.close()

@app.route('/attendance/scan-qr')
@login_required
def scan_qr():
    return render_template('qr/scan_qr.html')

@app.route('/attendance/mark', methods=['POST'])
@login_required
def mark_attendance_qr():
    if current_user.role not in ['supervisor', 'admin']:
        return jsonify({'success': False, 'message': 'Unauthorized access'})

    qr_code = request.form.get('qr_code')
    location = request.form.get('location', 'Unknown')
    
    if not qr_code:
        return jsonify({'success': False, 'message': 'No QR code provided'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # First get the QR code details
        cursor.execute("""
            SELECT q.qr_code, q.entity_id, t.full_name as trainee_name, u.department
            FROM QRCodes q
            JOIN Trainees t ON q.entity_id = t.trainee_id
            JOIN Users u ON t.user_id = u.user_id
            WHERE q.qr_code = ? AND q.is_active = 1
        """, (qr_code,))
        qr_data = cursor.fetchone()
        
        if not qr_data:
            return jsonify({'success': False, 'message': 'Invalid or expired QR code'})

        # Get current date and time
        current_time = datetime.now()
        current_date = current_time.date()
        
        # Check if attendance already exists for today
        cursor.execute("""
            SELECT attendance_id, checkin_time, checkout_time 
            FROM TraineeAttendance 
            WHERE trainee_id = ? AND CAST(attendance_date AS DATE) = CAST(GETDATE() AS DATE)
        """, (qr_data.entity_id,))
        existing_attendance = cursor.fetchone()
        
        if existing_attendance and not existing_attendance.checkout_time:
            # This is a checkout
            cursor.execute("""
                UPDATE TraineeAttendance 
                SET checkout_time = ?,
                    checkout_location = ?,
                    checkout_marked_by = ?
                WHERE attendance_id = ?
            """, (current_time, location, current_user.id, existing_attendance.attendance_id))
            attendance_type = 'checkout'
        else:
            # This is a new checkin
            cursor.execute("""
                INSERT INTO TraineeAttendance (
                    trainee_id,
                    attendance_date,
                    checkin_time,
                    checkin_location,
                    checkin_marked_by,
                    qr_code_used
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (qr_data.entity_id, current_date, current_time, location, current_user.id, qr_code))
            attendance_type = 'checkin'

        conn.commit()

        # Get trainer/supervisor name
        cursor.execute("""
            SELECT full_name as marker_name
            FROM Users u
            LEFT JOIN Supervisors s ON u.user_id = s.user_id
            WHERE u.user_id = ?
        """, (current_user.id,))
        marker_data = cursor.fetchone()

        response_data = {
            'success': True,
            'message': f'Attendance {attendance_type} marked successfully',
            'data': {
                'trainee_name': qr_data.trainee_name,
                'department': qr_data.department,
                'attendance_date': current_date.strftime('%Y-%m-%d'),
                'time': current_time.strftime('%H:%M:%S'),
                'location': location,
                'marked_by': marker_data.marker_name if marker_data else 'Unknown',
                'type': attendance_type
            }
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        app.logger.error(f"Attendance marking error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': f'Error marking attendance: {str(e)}'})
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/trainee/dashboard/attendance')
@login_required
def get_trainee_attendance():
    if current_user.role != 'trainee':
        return jsonify({'success': False, 'message': 'Unauthorized access'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get trainee's attendance records
        cursor.execute("""
            SELECT 
                ta.attendance_date,
                ta.checkin_time,
                ta.checkout_time,
                ta.checkin_location,
                ta.checkout_location,
                s_in.full_name as checked_in_by,
                s_out.full_name as checked_out_by
            FROM TraineeAttendance ta
            JOIN Trainees t ON ta.trainee_id = t.trainee_id
            LEFT JOIN Users u_in ON ta.checkin_marked_by = u_in.user_id
            LEFT JOIN Users u_out ON ta.checkout_marked_by = u_out.user_id
            LEFT JOIN Supervisors s_in ON u_in.user_id = s_in.user_id
            LEFT JOIN Supervisors s_out ON u_out.user_id = s_out.user_id
            WHERE t.user_id = ?
            ORDER BY ta.attendance_date DESC, ta.checkin_time DESC
        """, (current_user.id,))
        
        attendance_records = cursor.fetchall()
        
        return jsonify({
            'success': True,
            'data': [{
                'date': record.attendance_date.strftime('%Y-%m-%d'),
                'checkin_time': record.checkin_time.strftime('%H:%M:%S') if record.checkin_time else None,
                'checkout_time': record.checkout_time.strftime('%H:%M:%S') if record.checkout_time else None,
                'checkin_location': record.checkin_location,
                'checkout_location': record.checkout_location,
                'checked_in_by': record.checked_in_by,
                'checked_out_by': record.checked_out_by
            } for record in attendance_records]
        })
        
    except Exception as e:
        app.logger.error(f"Error fetching attendance: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': f'Error fetching attendance: {str(e)}'})
    finally:
        if 'conn' in locals():
            conn.close()

def verify_qrcodes_table():
    """Verify and create QRCodes table if it doesn't exist"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if QRCodes table exists
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[QRCodes]') AND type in (N'U'))
            BEGIN
                CREATE TABLE [dbo].[QRCodes] (
                    [qr_id] INT IDENTITY(1,1) PRIMARY KEY,
                    [qr_code] NVARCHAR(100) UNIQUE NOT NULL,
                    [entity_type] NVARCHAR(20) NOT NULL CHECK (entity_type IN ('trainee', 'station', 'equipment', 'session')),
                    [entity_id] INT NOT NULL,
                    [creation_date] DATETIME DEFAULT GETDATE(),
                    [expiration_date] DATETIME,
                    [is_active] BIT DEFAULT 1
                )
            END
        """)
        conn.commit()
        app.logger.info("QRCodes table verified/created successfully")
    except Exception as e:
        app.logger.error(f"Error verifying QRCodes table: {str(e)}")
        raise e
    finally:
        if conn:
            conn.close()

# Call verify_qrcodes_table when the app starts
with app.app_context():
    verify_qrcodes_table()

if __name__ == '__main__':
    app.run(debug=True)
