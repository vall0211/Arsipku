from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os

app = Flask(__name__)
app.secret_key = 'rahasia_anda_disini'

# ==================== KONFIGURASI MYSQL ====================
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'db_arsipku'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)

# ==================== KONFIGURASI UPLOAD ====================
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Hanya PDF, max 5MB  ← ubah komentar juga biar konsisten
ALLOWED_EXTENSIONS = {'pdf'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # ← UBAH 1: dari 3 jadi 5

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_file(file):
    if not allowed_file(file.filename):
        return False, 'Hanya file PDF yang diperbolehkan!'
    
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    
    if file_size > MAX_FILE_SIZE:
        return False, f'Ukuran file maksimal 3 MB. File kamu {file_size / (1024*1024):.2f} MB.'  # ← UBAH 2: teks 3 jadi 5
    
    return True, 'OK'

# ==================== HELPER: LOGIN REQUIRED ====================
def login_required(role=None):
    def decorator(f):
        def wrapper(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if role and session.get('role') != role:
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator

# ==================== ROUTES ====================

@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['nama'] = user['nama']
            
            flash(f'Selamat datang, {user["nama"]}!', 'success')
            
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('user_dashboard'))
        else:
            flash('Username atau password salah!', 'danger')
    
    return render_template('login.html')

@app.route('/daftar', methods=['GET', 'POST'])
def daftar():
    if request.method == 'POST':
        nama = request.form['nama']
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        
        cur = mysql.connection.cursor()
        try:
            cur.execute("""
                INSERT INTO users (username, password, role, nama) 
                VALUES (%s, %s, 'user', %s)
            """, (username, password, nama))
            mysql.connection.commit()
            flash('Akun berhasil dibuat! Silakan login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            mysql.connection.rollback()
            flash('Username sudah digunakan!', 'danger')
        finally:
            cur.close()
    
    return render_template('daftar.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Anda telah logout.', 'info')
    return redirect(url_for('login'))

# ==================== ADMIN ROUTES ====================

@app.route('/admin/dashboard')
@login_required(role='admin')
def admin_dashboard():
    cur = mysql.connection.cursor()
    
    cur.execute("SELECT COUNT(*) as total FROM dokumen")
    total_dokumen = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as total FROM users WHERE role = 'user'")
    total_user = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as total FROM kategori")
    total_kategori = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as total FROM dokumen WHERE tanggal_uplaod = CURDATE()")
    dokumen_hari_ini = cur.fetchone()['total']
    
    cur.execute("""
        SELECT d.id, d.judul, d.file, d.tanggal_uplaod, 
               u.nama as nama_user, k.nama as nama_kategori
        FROM dokumen d
        JOIN users u ON d.user_id = u.id
        JOIN kategori k ON d.kategori_id = k.id
        ORDER BY d.tanggal_uplaod DESC
        LIMIT 5
    """)
    dokumen_terbaru = cur.fetchall()
    cur.close()
    
    return render_template('admin/admin_dashboard.html',
                         total_dokumen=total_dokumen,
                         total_user=total_user,
                         total_kategori=total_kategori,
                         dokumen_hari_ini=dokumen_hari_ini,
                         dokumen_terbaru=dokumen_terbaru,
                         nama=session.get('nama'))

@app.route('/admin/dokumen')
@login_required(role='admin')
def admin_dokumen():
    page = request.args.get('page', 1, type=int)
    kategori_filter = request.args.get('kategori', '', type=str)  # ⬅️ TAMBAH INI
    per_page = 5
    
    cur = mysql.connection.cursor()
    
    # ⬇️ QUERY COUNT dengan filter kategori
    if kategori_filter:
        cur.execute("""
            SELECT COUNT(*) as total FROM dokumen d
            JOIN kategori k ON d.kategori_id = k.id
            WHERE k.nama = %s
        """, (kategori_filter,))
    else:
        cur.execute("SELECT COUNT(*) as total FROM dokumen")
    
    total_dokumen = cur.fetchone()['total']
    total_pages = (total_dokumen + per_page - 1) // per_page
    
    if page < 1:
        page = 1
    if total_pages > 0 and page > total_pages:
        page = total_pages
    
    offset = (page - 1) * per_page
    
    # ⬇️ QUERY DATA dengan filter kategori
    if kategori_filter:
        cur.execute("""
            SELECT d.id, d.judul, d.file, d.tanggal_uplaod,
                   u.nama as nama_user, k.nama as nama_kategori
            FROM dokumen d
            JOIN users u ON d.user_id = u.id
            JOIN kategori k ON d.kategori_id = k.id
            WHERE k.nama = %s
            ORDER BY d.tanggal_uplaod DESC
            LIMIT %s OFFSET %s
        """, (kategori_filter, per_page, offset))
    else:
        cur.execute("""
            SELECT d.id, d.judul, d.file, d.tanggal_uplaod,
                   u.nama as nama_user, k.nama as nama_kategori
            FROM dokumen d
            JOIN users u ON d.user_id = u.id
            JOIN kategori k ON d.kategori_id = k.id
            ORDER BY d.tanggal_uplaod DESC
            LIMIT %s OFFSET %s
        """, (per_page, offset))
    
    dokumen = cur.fetchall()
    
    cur.execute("SELECT * FROM kategori")
    kategori = cur.fetchall()
    cur.close()
    
    return render_template('admin/admin_dokumen.html',
                         dokumen=dokumen,
                         kategori=kategori,
                         nama=session.get('nama'),
                         page=page,
                         total_pages=total_pages,
                         total_dokumen=total_dokumen,
                         kategori_filter=kategori_filter)  # ⬅️ KIRIM KE TEMPLATE

@app.route('/admin/dokumen/hapus/<int:id>')
@login_required(role='admin')
def hapus_dokumen(id):
    cur = mysql.connection.cursor()
    
    cur.execute("SELECT file FROM dokumen WHERE id = %s", (id,))
    data = cur.fetchone()
    
    if data:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], data['file'])
        if os.path.exists(file_path):
            os.remove(file_path)
        
        cur.execute("DELETE FROM dokumen WHERE id = %s", (id,))
        mysql.connection.commit()
        flash('Dokumen berhasil dihapus!', 'success')
    
    cur.close()
    return redirect(url_for('admin_dokumen'))

# ==================== USER ROUTES ====================

# ⬇️⬇️⬇️ ROUTE INI YANG DIUPDATE UNTUK PAGINATION ⬇️⬇️⬇️
@app.route('/user/dashboard')
@login_required(role='user')
def user_dashboard():
    # Ambil parameter halaman dari URL, default halaman 1
    page = request.args.get('page', 1, type=int)
    per_page = 5  # 10 dokumen per halaman
    
    cur = mysql.connection.cursor()
    
    # Hitung total dokumen user untuk pagination
    cur.execute("SELECT COUNT(*) as total FROM dokumen WHERE user_id = %s", (session['user_id'],))
    total_dokumen = cur.fetchone()['total']
    
    # Hitung total halaman
    total_pages = (total_dokumen + per_page - 1) // per_page
    
    # Pastikan halaman valid
    if page < 1:
        page = 1
    if total_pages > 0 and page > total_pages:
        page = total_pages
    
    # Hitung offset
    offset = (page - 1) * per_page
    
    cur.execute("""
        SELECT COUNT(*) as total FROM dokumen 
        WHERE user_id = %s AND tanggal_uplaod = CURDATE()
    """, (session['user_id'],))
    dokumen_hari_ini = cur.fetchone()['total']
    
    # Ambil dokumen untuk halaman ini (dengan LIMIT dan OFFSET)
    cur.execute("""
        SELECT d.id, d.judul, d.file, d.tanggal_uplaod, k.nama as nama_kategori
        FROM dokumen d
        JOIN kategori k ON d.kategori_id = k.id
        WHERE d.user_id = %s
        ORDER BY d.tanggal_uplaod DESC
        LIMIT %s OFFSET %s
    """, (session['user_id'], per_page, offset))
    dokumen = cur.fetchall()
    
    # Ambil kategori untuk dropdown upload
    cur.execute("SELECT * FROM kategori")
    kategori = cur.fetchall()
    cur.close()
    
    return render_template('user/user_dashboard.html',
                         dokumen=dokumen,
                         total_dokumen=total_dokumen,
                         dokumen_hari_ini=dokumen_hari_ini,
                         nama=session.get('nama'),
                         kategori=kategori,
                         page=page,
                         total_pages=total_pages)

@app.route('/user/dokumen/upload', methods=['POST'])
@login_required(role='user')
def user_upload_dokumen():
    judul = request.form['judul']
    kategori_id = request.form['kategori_id']
    file = request.files['file']
    
    if not file or file.filename == '':
        flash('Tidak ada file yang dipilih!', 'danger')
        return redirect(url_for('user_dashboard'))
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT id FROM kategori WHERE id = %s", (kategori_id,))
    if not cur.fetchone():
        cur.close()
        flash('Kategori tidak valid!', 'danger')
        return redirect(url_for('user_dashboard'))
    
    valid, msg = validate_file(file)
    if not valid:
        cur.close()
        flash(msg, 'danger')
        return redirect(url_for('user_dashboard'))
    
    filename = secure_filename(file.filename)
    import time
    unique_filename = f"{int(time.time())}_{filename}"
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
    
    cur.execute("""
        INSERT INTO dokumen (judul, file, tanggal_uplaod, user_id, kategori_id)
        VALUES (%s, %s, CURDATE(), %s, %s)
    """, (judul, unique_filename, session['user_id'], kategori_id))
    mysql.connection.commit()
    cur.close()
    
    flash('Dokumen berhasil diunggah!', 'success')
    return redirect(url_for('user_dashboard'))

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True)