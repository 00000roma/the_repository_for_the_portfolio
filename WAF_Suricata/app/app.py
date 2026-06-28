import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, request, render_template, redirect, url_for
import psycopg2

app = Flask(__name__)

# Настройка логирования
log_dir = '/var/log/app'
os.makedirs(log_dir, exist_ok=True)

logger = logging.getLogger('my_app')
logger.setLevel(logging.DEBUG)
fh = RotatingFileHandler(f'{log_dir}/app.log', maxBytes=10000, backupCount=3)
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
logger.addHandler(fh)

# Подключение к БД

def get_db_connection():
    conn = psycopg2.connect(
        host=os.environ.get('DB_HOST', 'db'),
        database=os.environ.get('DB_NAME', 'mydb'),
        user=os.environ.get('DB_USER', 'user'),
        password=os.environ.get('DB_PASS', 'strong_password')
    )
    return conn

# Главная страница

@app.route('/')
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, title, content FROM notes ORDER BY id DESC;')
    notes = cur.fetchall()
    cur.close()
    conn.close()
    logger.info(f'Главная страница загружена, показано {len(notes)} записей')
    return render_template('index.html', notes=notes)

# Добавление заметки

@app.route('/add', methods=['POST'])
def add_note():
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    if not title or not content:
        logger.warning('Попытка добавить пустую заметку')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('INSERT INTO notes (title, content) VALUES (%s, %s);', (title, content))
    conn.commit()
    cur.close()
    conn.close()
    logger.info(f'Добавлена заметка: "{title}"')
    return redirect(url_for('index'))

# Удаление заметки

@app.route('/delete/<int:note_id>', methods=['POST'])
def delete_note(note_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM notes WHERE id = %s;', (note_id,))
    conn.commit()
    cur.close()
    conn.close()
    logger.info(f'Удалена заметка ID {note_id}')
    return redirect(url_for('index'))

# Запуск

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)