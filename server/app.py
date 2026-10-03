import os
import uuid
import time
import sqlite3
from datetime import datetime
from functools import wraps
from flask import (
    Flask, request, jsonify, session,
    send_from_directory, g
)
from werkzeug.utils import secure_filename

# ─── App Setup ────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder='static', static_url_path='/static')

app.secret_key = os.environ.get('SECRET_KEY', 'wowbox-secret-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB max upload

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
PASSWORD = os.environ.get('WOWBOX_PASSWORD', 'wowbox123')
AGENT_KEY = os.environ.get('AGENT_KEY', 'agent-secret-key-change-me')
DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wowbox.db')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'heic', 'heif'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─── Database ─────────────────────────────────────────────────────────────────

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    """Initialize the database schema."""
    db = sqlite3.connect(DATABASE)
    db.execute('''
        CREATE TABLE IF NOT EXISTS print_queue (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            error TEXT
        )
    ''')
    db.commit()
    db.close()

# Initialize DB on startup
init_db()

# ─── Auth Helpers ─────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

def agent_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get('X-Agent-Key')
        if key != AGENT_KEY:
            return jsonify({'error': 'Invalid agent key'}), 403
        return f(*args, **kwargs)
    return decorated

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ─── Public Routes ────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    if data and data.get('password') == PASSWORD:
        session['authenticated'] = True
        session.permanent = True
        return jsonify({'success': True})
    return jsonify({'error': 'סיסמה שגויה'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('authenticated', None)
    return jsonify({'success': True})

@app.route('/api/check-auth')
def check_auth():
    return jsonify({'authenticated': session.get('authenticated', False)})

# ─── Authenticated Routes ─────────────────────────────────────────────────────

@app.route('/api/upload', methods=['POST'])
@login_required
def upload():
    if 'image' not in request.files:
        return jsonify({'error': 'לא נבחרה תמונה'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'לא נבחר קובץ'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'סוג קובץ לא נתמך. השתמש ב-JPG, PNG, GIF, WEBP או HEIC'}), 400

    # Generate unique filename
    file_id = str(uuid.uuid4())
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{file_id}.{ext}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)

    file.save(filepath)

    # Add to print queue
    now = datetime.utcnow().isoformat()
    db = get_db()
    db.execute(
        'INSERT INTO print_queue (id, filename, original_name, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
        (file_id, filename, file.filename, 'pending', now, now)
    )
    db.commit()

    return jsonify({
        'success': True,
        'id': file_id,
        'message': 'התמונה התקבלה ונוספה לתור ההדפסה'
    })

@app.route('/api/queue')
@login_required
def get_queue():
    db = get_db()
    rows = db.execute(
        'SELECT * FROM print_queue ORDER BY created_at DESC LIMIT 50'
    ).fetchall()

    queue = []
    for row in rows:
        queue.append({
            'id': row['id'],
            'filename': row['filename'],
            'original_name': row['original_name'],
            'status': row['status'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
            'error': row['error']
        })

    return jsonify({'queue': queue})

@app.route('/api/queue/<item_id>', methods=['DELETE'])
@login_required
def cancel_item(item_id):
    db = get_db()
    item = db.execute('SELECT * FROM print_queue WHERE id = ?', (item_id,)).fetchone()

    if not item:
        return jsonify({'error': 'פריט לא נמצא'}), 404

    if item['status'] not in ('pending',):
        return jsonify({'error': 'ניתן לבטל רק פריטים בהמתנה'}), 400

    # Delete file
    filepath = os.path.join(UPLOAD_FOLDER, item['filename'])
    if os.path.exists(filepath):
        os.remove(filepath)

    db.execute('DELETE FROM print_queue WHERE id = ?', (item_id,))
    db.commit()

    return jsonify({'success': True})

@app.route('/api/queue/clear', methods=['POST'])
@login_required
def clear_completed():
    """Clear all completed and failed items from the queue."""
    db = get_db()
    
    # Get files to delete
    items = db.execute(
        "SELECT filename FROM print_queue WHERE status IN ('completed', 'failed')"
    ).fetchall()
    
    for item in items:
        filepath = os.path.join(UPLOAD_FOLDER, item['filename'])
        if os.path.exists(filepath):
            os.remove(filepath)
    
    db.execute("DELETE FROM print_queue WHERE status IN ('completed', 'failed')")
    db.commit()

    return jsonify({'success': True})

@app.route('/api/thumbnail/<item_id>')
@login_required
def get_thumbnail(item_id):
    """Serve the uploaded image for preview/thumbnail."""
    db = get_db()
    item = db.execute('SELECT filename FROM print_queue WHERE id = ?', (item_id,)).fetchone()

    if not item:
        return jsonify({'error': 'Not found'}), 404

    filepath = os.path.join(UPLOAD_FOLDER, item['filename'])
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404

    return send_from_directory(UPLOAD_FOLDER, item['filename'])

# ─── Agent Routes ─────────────────────────────────────────────────────────────

@app.route('/api/agent/next')
@agent_required
def agent_next():
    """Get the next pending print job for the agent."""
    db = get_db()
    item = db.execute(
        'SELECT * FROM print_queue WHERE status = ? ORDER BY created_at ASC LIMIT 1',
        ('pending',)
    ).fetchone()

    if not item:
        return jsonify({'has_job': False})

    # Mark as printing
    now = datetime.utcnow().isoformat()
    db.execute(
        'UPDATE print_queue SET status = ?, updated_at = ? WHERE id = ?',
        ('printing', now, item['id'])
    )
    db.commit()

    return jsonify({
        'has_job': True,
        'id': item['id'],
        'filename': item['filename'],
        'original_name': item['original_name']
    })

@app.route('/api/agent/download/<filename>')
@agent_required
def agent_download(filename):
    """Download the image file for printing."""
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/api/agent/status', methods=['POST'])
@agent_required
def agent_status():
    """Update the status of a print job."""
    data = request.get_json()
    job_id = data.get('id')
    status = data.get('status')  # 'completed' or 'failed'
    error = data.get('error')

    if not job_id or status not in ('completed', 'failed'):
        return jsonify({'error': 'Invalid request'}), 400

    now = datetime.utcnow().isoformat()
    db = get_db()
    db.execute(
        'UPDATE print_queue SET status = ?, updated_at = ?, error = ? WHERE id = ?',
        (status, now, error, job_id)
    )
    db.commit()

    return jsonify({'success': True})

@app.route('/api/agent/heartbeat')
@agent_required
def agent_heartbeat():
    """Agent health check endpoint."""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat()
    })

# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
