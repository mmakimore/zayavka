from __future__ import annotations

import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

from config import ADMIN_SESSION_HOURS, BUMP_COOLDOWN_HOURS, DATABASE_PATH, TASK_LIFETIME_DAYS

os.makedirs(os.path.dirname(DATABASE_PATH) or '.', exist_ok=True)


ALLOWED_TASK_STATUSES = {'draft', 'pending', 'open', 'in_progress', 'closed', 'rejected', 'archived'}
ALLOWED_REPORT_STATUSES = {'open', 'closed'}


def dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


@contextmanager
def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = dict_factory
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA journal_mode = WAL')
    conn.execute('PRAGMA busy_timeout = 7000')
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def utc_now_str() -> str:
    return datetime.utcnow().isoformat(sep=' ', timespec='seconds')


def table_columns(table_name: str) -> set[str]:
    with get_connection() as conn:
        rows = conn.execute(f'PRAGMA table_info({table_name})').fetchall()
    return {row['name'] for row in rows}


def ensure_column(table_name: str, column_name: str, ddl: str) -> None:
    if column_name not in table_columns(table_name):
        with get_connection() as conn:
            conn.execute(f'ALTER TABLE {table_name} ADD COLUMN {ddl}')


def init_db() -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                full_name TEXT,
                phone TEXT,
                role TEXT NOT NULL CHECK(role IN ('customer','worker','admin')),
                city TEXT,
                specialization TEXT,
                about TEXT,
                rating REAL DEFAULT 0,
                reviews_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                is_banned INTEGER DEFAULT 0,
                banned_reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                city TEXT NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                budget INTEGER NOT NULL,
                address TEXT,
                latitude REAL,
                longitude REAL,
                contact_text TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('draft','pending','open','in_progress','closed','rejected','archived')),
                selected_response_id INTEGER,
                rejection_reason TEXT,
                views_count INTEGER DEFAULT 0,
                responses_count INTEGER DEFAULT 0,
                is_urgent INTEGER DEFAULT 0,
                bumped_at TEXT,
                expires_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(customer_id) REFERENCES users(id)
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS task_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS task_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                worker_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                offer_price INTEGER,
                contact_text TEXT,
                status TEXT NOT NULL DEFAULT 'sent'
                    CHECK(status IN ('sent','accepted','rejected','cancelled')),
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(task_id, worker_id),
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY(worker_id) REFERENCES users(id)
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                response_id INTEGER,
                worker_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                text TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(task_id, worker_id),
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY(response_id) REFERENCES task_responses(id) ON DELETE SET NULL,
                FOREIGN KEY(worker_id) REFERENCES users(id),
                FOREIGN KEY(customer_id) REFERENCES users(id)
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(worker_id, task_id),
                FOREIGN KEY(worker_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER NOT NULL,
                task_id INTEGER,
                target_user_id INTEGER,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(reporter_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE SET NULL,
                FOREIGN KEY(target_user_id) REFERENCES users(id) ON DELETE SET NULL
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                actor_user_id INTEGER,
                event_type TEXT NOT NULL,
                details TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS admin_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS admin_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_tg_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                entity_type TEXT,
                entity_id INTEGER,
                details TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cur.execute('CREATE INDEX IF NOT EXISTS idx_tasks_status_city_cat ON tasks(status, city, category)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_tasks_customer ON tasks(customer_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_tasks_bumped ON tasks(bumped_at, created_at)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_responses_task ON task_responses(task_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_responses_worker ON task_responses(worker_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_users_role_city ON users(role, city)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_favorites_worker ON favorites(worker_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status)')

    ensure_column('users', 'is_banned', 'is_banned INTEGER DEFAULT 0')
    ensure_column('users', 'banned_reason', 'banned_reason TEXT')
    ensure_column('tasks', 'views_count', 'views_count INTEGER DEFAULT 0')
    ensure_column('tasks', 'responses_count', 'responses_count INTEGER DEFAULT 0')
    ensure_column('tasks', 'rejection_reason', 'rejection_reason TEXT')
    ensure_column('tasks', 'is_urgent', 'is_urgent INTEGER DEFAULT 0')
    ensure_column('tasks', 'bumped_at', 'bumped_at TEXT')
    ensure_column('tasks', 'expires_at', 'expires_at TEXT')


# ===== Users =====

def get_user_by_tg(telegram_id: int):
    with get_connection() as conn:
        return conn.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,)).fetchone()


def get_user_by_id(user_id: int):
    with get_connection() as conn:
        return conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()


def create_or_update_user(
    telegram_id: int,
    username: str,
    full_name: str,
    role: str,
    city: str | None = None,
    phone: str | None = None,
    specialization: str | None = None,
    about: str | None = None,
):
    current = get_user_by_tg(telegram_id)
    with get_connection() as conn:
        if current:
            conn.execute(
                '''
                UPDATE users
                SET username=?, full_name=?, role=?, city=?, phone=?, specialization=?, about=?, is_active=1, updated_at=CURRENT_TIMESTAMP
                WHERE telegram_id=?
                ''',
                (username, full_name, role, city, phone, specialization, about, telegram_id),
            )
        else:
            conn.execute(
                '''
                INSERT INTO users (telegram_id, username, full_name, role, city, phone, specialization, about)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (telegram_id, username, full_name, role, city, phone, specialization, about),
            )
    return get_user_by_tg(telegram_id)


def update_user_profile(telegram_id: int, **fields):
    allowed = {'city', 'phone', 'specialization', 'about', 'full_name', 'username', 'role', 'is_active', 'is_banned', 'banned_reason'}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_user_by_tg(telegram_id)
    parts = ', '.join([f'{key} = ?' for key in updates])
    params = list(updates.values()) + [telegram_id]
    with get_connection() as conn:
        conn.execute(f'UPDATE users SET {parts}, updated_at=CURRENT_TIMESTAMP WHERE telegram_id=?', params)
    return get_user_by_tg(telegram_id)


def list_users(role: str | None = None, city: str | None = None, limit: int = 20, offset: int = 0):
    query = 'SELECT * FROM users WHERE 1=1'
    params: list = []
    if role and role != 'all':
        query += ' AND role=?'
        params.append(role)
    if city and city != 'all':
        query += ' AND city=?'
        params.append(city)
    query += ' ORDER BY id DESC LIMIT ? OFFSET ?'
    params.extend([limit, offset])
    with get_connection() as conn:
        return conn.execute(query, params).fetchall()


def search_users(query: str, limit: int = 20):
    q = f'%{(query or '').strip()}%'
    with get_connection() as conn:
        return conn.execute(
            '''
            SELECT * FROM users
            WHERE CAST(id AS TEXT)=? OR CAST(telegram_id AS TEXT)=? OR full_name LIKE ? OR username LIKE ? OR phone LIKE ?
            ORDER BY id DESC LIMIT ?
            ''',
            ((query or '').strip(), (query or '').strip(), q, q, q, limit),
        ).fetchall()


def ban_user(user_id: int, reason: str | None = None):
    with get_connection() as conn:
        conn.execute('UPDATE users SET is_banned=1, banned_reason=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (reason, user_id))


def unban_user(user_id: int):
    with get_connection() as conn:
        conn.execute('UPDATE users SET is_banned=0, banned_reason=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?', (user_id,))


# ===== Tasks =====

def create_task(
    customer_id: int,
    city: str,
    category: str,
    title: str,
    description: str,
    budget: int,
    address: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    contact_text: str | None = None,
    photos: Iterable[str] | None = None,
    status: str = 'pending',
):
    if status not in ALLOWED_TASK_STATUSES:
        status = 'pending'
    now = utc_now_str()
    expires_at = (datetime.utcnow() + timedelta(days=TASK_LIFETIME_DAYS)).isoformat(sep=' ', timespec='seconds')
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            '''
            INSERT INTO tasks (customer_id, city, category, title, description, budget, address, latitude, longitude, contact_text, status, bumped_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (customer_id, city, category, title, description, budget, address, latitude, longitude, contact_text, status, now, expires_at),
        )
        task_id = cur.lastrowid
        if photos:
            cur.executemany('INSERT INTO task_photos (task_id, file_id) VALUES (?, ?)', [(task_id, file_id) for file_id in photos])
        cur.execute('INSERT INTO task_events (task_id, actor_user_id, event_type, details) VALUES (?, ?, ?, ?)', (task_id, customer_id, 'created', title[:200]))
    return get_task(task_id)


def get_task(task_id: int):
    with get_connection() as conn:
        task = conn.execute(
            '''
            SELECT t.*, u.full_name AS customer_name, u.telegram_id AS customer_tg, u.phone AS customer_phone, u.username AS customer_username
            FROM tasks t
            JOIN users u ON u.id = t.customer_id
            WHERE t.id = ?
            ''',
            (task_id,),
        ).fetchone()
    if task:
        task['photos'] = get_task_photos(task_id)
    return task


def get_task_photos(task_id: int):
    with get_connection() as conn:
        rows = conn.execute('SELECT file_id FROM task_photos WHERE task_id = ? ORDER BY id', (task_id,)).fetchall()
    return [row['file_id'] for row in rows]


def add_task_view(task_id: int):
    with get_connection() as conn:
        conn.execute('UPDATE tasks SET views_count = COALESCE(views_count, 0) + 1 WHERE id = ?', (task_id,))


def get_tasks(
    city: Optional[str] = None,
    category: Optional[str] = None,
    status: str | None = 'open',
    limit: int = 20,
    offset: int = 0,
    customer_id: int | None = None,
    worker_id_favorites: int | None = None,
):
    query = 'SELECT DISTINCT t.*, u.full_name AS customer_name FROM tasks t JOIN users u ON u.id = t.customer_id '
    params: list = []
    if worker_id_favorites is not None:
        query += 'JOIN favorites f ON f.task_id = t.id '
    query += 'WHERE 1=1'
    if status and status != 'all':
        query += ' AND t.status = ?'
        params.append(status)
    if city and city != 'all':
        query += ' AND t.city = ?'
        params.append(city)
    if category and category != 'all':
        query += ' AND t.category = ?'
        params.append(category)
    if customer_id:
        query += ' AND t.customer_id = ?'
        params.append(customer_id)
    if worker_id_favorites is not None:
        query += ' AND f.worker_id = ?'
        params.append(worker_id_favorites)
    query += ' ORDER BY COALESCE(t.bumped_at, t.created_at) DESC, t.id DESC LIMIT ? OFFSET ?'
    params.extend([limit, offset])
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    for row in rows:
        row['photos'] = get_task_photos(row['id'])
    return rows


def search_tasks(query: str, status: str = 'all', limit: int = 20):
    raw = (query or '').strip()
    with get_connection() as conn:
        if raw.isdigit():
            rows = conn.execute(
                '''
                SELECT t.*, u.full_name AS customer_name
                FROM tasks t JOIN users u ON u.id = t.customer_id
                WHERE t.id = ?
                ORDER BY t.id DESC LIMIT ?
                ''',
                (int(raw), limit),
            ).fetchall()
        else:
            like = f'%{raw}%'
            q = (
                'SELECT t.*, u.full_name AS customer_name FROM tasks t JOIN users u ON u.id=t.customer_id '
                'WHERE (t.title LIKE ? OR t.description LIKE ? OR t.city LIKE ? OR t.category LIKE ?)'
            )
            params: list = [like, like, like, like]
            if status != 'all':
                q += ' AND t.status=?'
                params.append(status)
            q += ' ORDER BY COALESCE(t.bumped_at, t.created_at) DESC LIMIT ?'
            params.append(limit)
            rows = conn.execute(q, params).fetchall()
    for row in rows:
        row['photos'] = get_task_photos(row['id'])
    return rows


def get_customer_tasks(customer_id: int):
    return get_tasks(status='all', customer_id=customer_id, limit=100)


def update_task_status(task_id: int, status: str, selected_response_id: int | None = None, rejection_reason: str | None = None):
    if status not in ALLOWED_TASK_STATUSES:
        return
    with get_connection() as conn:
        if selected_response_id is not None:
            conn.execute(
                'UPDATE tasks SET status=?, selected_response_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                (status, selected_response_id, task_id),
            )
        elif rejection_reason is not None:
            conn.execute(
                'UPDATE tasks SET status=?, rejection_reason=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                (status, rejection_reason, task_id),
            )
        else:
            conn.execute('UPDATE tasks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (status, task_id))


def bump_task(task_id: int, urgent: bool = False) -> tuple[bool, str]:
    task = get_task(task_id)
    if not task:
        return False, 'Заявка не найдена'
    if task['status'] not in {'open', 'pending'}:
        return False, 'Поднимать можно только открытую заявку или заявку на модерации'
    if task.get('bumped_at'):
        try:
            last = datetime.fromisoformat(task['bumped_at'])
            if datetime.utcnow() - last < timedelta(hours=BUMP_COOLDOWN_HOURS):
                return False, f'Поднять ещё рано. Повтори позже.'
        except Exception:
            pass
    with get_connection() as conn:
        conn.execute(
            'UPDATE tasks SET bumped_at=?, is_urgent=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
            (utc_now_str(), 1 if urgent else int(task.get('is_urgent') or 0), task_id),
        )
        conn.execute('INSERT INTO task_events (task_id, actor_user_id, event_type, details) VALUES (?, ?, ?, ?)', (task_id, task['customer_id'], 'bumped', 'manual bump'))
    return True, 'Заявка поднята наверх'


def delete_task(task_id: int):
    with get_connection() as conn:
        conn.execute('DELETE FROM tasks WHERE id=?', (task_id,))


def archive_expired_tasks() -> int:
    now = utc_now_str()
    with get_connection() as conn:
        rows = conn.execute(
            '''
            SELECT id FROM tasks
            WHERE status IN ('open','pending') AND expires_at IS NOT NULL AND expires_at < ?
            ''',
            (now,),
        ).fetchall()
        if rows:
            conn.execute(
                "UPDATE tasks SET status='archived', updated_at=CURRENT_TIMESTAMP WHERE status IN ('open','pending') AND expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
        for row in rows:
            conn.execute('INSERT INTO task_events (task_id, event_type, details) VALUES (?, ?, ?)', (row['id'], 'archived', 'auto archive'))
    return len(rows)


def log_task_event(task_id: int, event_type: str, actor_user_id: int | None = None, details: str | None = None):
    with get_connection() as conn:
        conn.execute(
            'INSERT INTO task_events (task_id, actor_user_id, event_type, details) VALUES (?, ?, ?, ?)',
            (task_id, actor_user_id, event_type, details),
        )


def get_task_events(task_id: int, limit: int = 20):
    with get_connection() as conn:
        return conn.execute(
            '''
            SELECT e.*, u.full_name AS actor_name
            FROM task_events e
            LEFT JOIN users u ON u.id = e.actor_user_id
            WHERE e.task_id=?
            ORDER BY e.id DESC LIMIT ?
            ''',
            (task_id, limit),
        ).fetchall()


# ===== Favorites =====

def is_favorite(worker_id: int, task_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute('SELECT id FROM favorites WHERE worker_id=? AND task_id=?', (worker_id, task_id)).fetchone()
    return bool(row)


def add_favorite(worker_id: int, task_id: int):
    with get_connection() as conn:
        conn.execute('INSERT OR IGNORE INTO favorites (worker_id, task_id) VALUES (?, ?)', (worker_id, task_id))


def remove_favorite(worker_id: int, task_id: int):
    with get_connection() as conn:
        conn.execute('DELETE FROM favorites WHERE worker_id=? AND task_id=?', (worker_id, task_id))


def get_favorite_tasks(worker_id: int, limit: int = 50):
    return get_tasks(status='all', limit=limit, worker_id_favorites=worker_id)


# ===== Responses =====

def create_response(task_id: int, worker_id: int, message: str, offer_price: Optional[int] = None, contact_text: str | None = None):
    with get_connection() as conn:
        cur = conn.cursor()
        exists = cur.execute('SELECT id FROM task_responses WHERE task_id=? AND worker_id=?', (task_id, worker_id)).fetchone()
        if exists:
            cur.execute(
                '''
                UPDATE task_responses
                SET message=?, offer_price=?, contact_text=?, status='sent', updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                ''',
                (message, offer_price, contact_text, exists['id']),
            )
            response_id = exists['id']
        else:
            cur.execute(
                '''
                INSERT INTO task_responses (task_id, worker_id, message, offer_price, contact_text)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (task_id, worker_id, message, offer_price, contact_text),
            )
            response_id = cur.lastrowid
        cur.execute('UPDATE tasks SET responses_count = (SELECT COUNT(*) FROM task_responses WHERE task_id=?) WHERE id=?', (task_id, task_id))
        cur.execute('INSERT INTO task_events (task_id, actor_user_id, event_type, details) VALUES (?, ?, ?, ?)', (task_id, worker_id, 'response_sent', str(response_id)))
    return get_response(response_id)


def get_response(response_id: int):
    with get_connection() as conn:
        return conn.execute(
            '''
            SELECT r.*, u.full_name AS worker_name, u.telegram_id AS worker_tg, u.phone AS worker_phone,
                   u.city AS worker_city, u.specialization AS worker_specialization, u.about AS worker_about,
                   u.rating AS worker_rating, u.reviews_count AS worker_reviews_count, u.username AS worker_username
            FROM task_responses r
            JOIN users u ON u.id = r.worker_id
            WHERE r.id = ?
            ''',
            (response_id,),
        ).fetchone()


def get_task_responses(task_id: int):
    with get_connection() as conn:
        return conn.execute(
            '''
            SELECT r.*, u.full_name AS worker_name, u.telegram_id AS worker_tg, u.phone AS worker_phone,
                   u.city AS worker_city, u.specialization AS worker_specialization, u.about AS worker_about,
                   u.rating AS worker_rating, u.reviews_count AS worker_reviews_count, u.username AS worker_username
            FROM task_responses r
            JOIN users u ON u.id = r.worker_id
            WHERE r.task_id = ?
            ORDER BY r.id DESC
            ''',
            (task_id,),
        ).fetchall()


def get_worker_responses(worker_id: int):
    with get_connection() as conn:
        return conn.execute(
            '''
            SELECT r.*, t.title AS task_title, t.city AS task_city, t.status AS task_status, t.budget AS task_budget
            FROM task_responses r
            JOIN tasks t ON t.id = r.task_id
            WHERE r.worker_id = ?
            ORDER BY r.id DESC
            ''',
            (worker_id,),
        ).fetchall()


def update_response_status(response_id: int, status: str):
    with get_connection() as conn:
        conn.execute('UPDATE task_responses SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (status, response_id))


def accept_response(task_id: int, response_id: int):
    with get_connection() as conn:
        response = conn.execute('SELECT worker_id FROM task_responses WHERE id=? AND task_id=?', (response_id, task_id)).fetchone()
        conn.execute('UPDATE task_responses SET status=CASE WHEN id=? THEN "accepted" ELSE "rejected" END, updated_at=CURRENT_TIMESTAMP WHERE task_id=?', (response_id, task_id))
        conn.execute('UPDATE tasks SET status="in_progress", selected_response_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (response_id, task_id))
        conn.execute('INSERT INTO task_events (task_id, actor_user_id, event_type, details) VALUES (?, ?, ?, ?)', (task_id, response['worker_id'] if response else None, 'worker_selected', str(response_id)))


# ===== Reviews =====

def add_review(task_id: int, response_id: int | None, worker_id: int, customer_id: int, rating: int, text: str | None = None):
    with get_connection() as conn:
        conn.execute(
            '''
            INSERT OR REPLACE INTO reviews (task_id, response_id, worker_id, customer_id, rating, text)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (task_id, response_id, worker_id, customer_id, rating, text),
        )
        stats = conn.execute('SELECT AVG(rating) avg_rating, COUNT(*) cnt FROM reviews WHERE worker_id=?', (worker_id,)).fetchone()
        conn.execute('UPDATE users SET rating=?, reviews_count=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (round(stats['avg_rating'] or 0, 2), stats['cnt'], worker_id))


def get_review_for_task(task_id: int, worker_id: int):
    with get_connection() as conn:
        return conn.execute('SELECT * FROM reviews WHERE task_id=? AND worker_id=?', (task_id, worker_id)).fetchone()


def get_top_workers(limit: int = 10):
    with get_connection() as conn:
        return conn.execute(
            '''
            SELECT * FROM users
            WHERE role='worker'
            ORDER BY rating DESC, reviews_count DESC, id DESC
            LIMIT ?
            ''',
            (limit,),
        ).fetchall()


# ===== Reports =====

def create_report(reporter_id: int, reason: str, task_id: int | None = None, target_user_id: int | None = None):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            '''
            INSERT INTO reports (reporter_id, task_id, target_user_id, reason)
            VALUES (?, ?, ?, ?)
            ''',
            (reporter_id, task_id, target_user_id, reason),
        )
        report_id = cur.lastrowid
    return get_report(report_id)


def get_report(report_id: int):
    with get_connection() as conn:
        return conn.execute(
            '''
            SELECT r.*, rep.full_name AS reporter_name, rep.telegram_id AS reporter_tg,
                   tu.full_name AS target_user_name, t.title AS task_title
            FROM reports r
            LEFT JOIN users rep ON rep.id = r.reporter_id
            LEFT JOIN users tu ON tu.id = r.target_user_id
            LEFT JOIN tasks t ON t.id = r.task_id
            WHERE r.id=?
            ''',
            (report_id,),
        ).fetchone()


def get_reports(status: str = 'open', limit: int = 50):
    query = (
        'SELECT r.*, rep.full_name AS reporter_name, rep.telegram_id AS reporter_tg, '
        'tu.full_name AS target_user_name, t.title AS task_title '
        'FROM reports r '
        'LEFT JOIN users rep ON rep.id = r.reporter_id '
        'LEFT JOIN users tu ON tu.id = r.target_user_id '
        'LEFT JOIN tasks t ON t.id = r.task_id '
    )
    params: list = []
    if status != 'all':
        query += 'WHERE r.status=? '
        params.append(status)
    query += 'ORDER BY r.id DESC LIMIT ?'
    params.append(limit)
    with get_connection() as conn:
        return conn.execute(query, params).fetchall()


def close_report(report_id: int):
    with get_connection() as conn:
        conn.execute('UPDATE reports SET status="closed", updated_at=CURRENT_TIMESTAMP WHERE id=?', (report_id,))


# ===== Admin =====

def create_admin_session(telegram_id: int):
    expires_at = (datetime.utcnow() + timedelta(hours=ADMIN_SESSION_HOURS)).isoformat(sep=' ', timespec='seconds')
    with get_connection() as conn:
        conn.execute('DELETE FROM admin_sessions WHERE telegram_id=?', (telegram_id,))
        conn.execute('INSERT INTO admin_sessions (telegram_id, expires_at) VALUES (?, ?)', (telegram_id, expires_at))


def has_active_admin_session(telegram_id: int) -> bool:
    now = utc_now_str()
    with get_connection() as conn:
        row = conn.execute('SELECT id FROM admin_sessions WHERE telegram_id=? AND expires_at>? ORDER BY id DESC LIMIT 1', (telegram_id, now)).fetchone()
    return bool(row)


def remove_admin_session(telegram_id: int):
    with get_connection() as conn:
        conn.execute('DELETE FROM admin_sessions WHERE telegram_id=?', (telegram_id,))


def log_admin_action(admin_tg_id: int, action: str, entity_type: str | None = None, entity_id: int | None = None, details: str | None = None):
    with get_connection() as conn:
        conn.execute(
            'INSERT INTO admin_actions (admin_tg_id, action, entity_type, entity_id, details) VALUES (?, ?, ?, ?, ?)',
            (admin_tg_id, action, entity_type, entity_id, details),
        )


def get_stats() -> dict:
    with get_connection() as conn:
        stats = {
            'users_total': conn.execute('SELECT COUNT(*) cnt FROM users').fetchone()['cnt'],
            'customers_total': conn.execute("SELECT COUNT(*) cnt FROM users WHERE role='customer'").fetchone()['cnt'],
            'workers_total': conn.execute("SELECT COUNT(*) cnt FROM users WHERE role='worker'").fetchone()['cnt'],
            'banned_total': conn.execute('SELECT COUNT(*) cnt FROM users WHERE is_banned=1').fetchone()['cnt'],
            'tasks_total': conn.execute('SELECT COUNT(*) cnt FROM tasks').fetchone()['cnt'],
            'tasks_pending': conn.execute("SELECT COUNT(*) cnt FROM tasks WHERE status='pending'").fetchone()['cnt'],
            'tasks_open': conn.execute("SELECT COUNT(*) cnt FROM tasks WHERE status='open'").fetchone()['cnt'],
            'tasks_in_progress': conn.execute("SELECT COUNT(*) cnt FROM tasks WHERE status='in_progress'").fetchone()['cnt'],
            'tasks_closed': conn.execute("SELECT COUNT(*) cnt FROM tasks WHERE status='closed'").fetchone()['cnt'],
            'tasks_archived': conn.execute("SELECT COUNT(*) cnt FROM tasks WHERE status='archived'").fetchone()['cnt'],
            'favorites_total': conn.execute('SELECT COUNT(*) cnt FROM favorites').fetchone()['cnt'],
            'reports_open': conn.execute("SELECT COUNT(*) cnt FROM reports WHERE status='open'").fetchone()['cnt'],
            'responses_total': conn.execute('SELECT COUNT(*) cnt FROM task_responses').fetchone()['cnt'],
            'avg_budget': conn.execute('SELECT AVG(budget) avg_val FROM tasks').fetchone()['avg_val'] or 0,
        }
    return stats


# ===== Export / restore =====

def get_all_table_rows(table_name: str):
    with get_connection() as conn:
        return conn.execute(f'SELECT * FROM {table_name}').fetchall()


def backup_database_copy(target_path: str):
    source = Path(DATABASE_PATH)
    if not source.exists():
        raise FileNotFoundError('База данных не найдена')
    shutil.copy2(source, target_path)


def restore_database_from_copy(source_path: str):
    target = Path(DATABASE_PATH)
    backup_path = target.with_suffix('.before_restore.db')
    if target.exists():
        shutil.copy2(target, backup_path)
    shutil.copy2(source_path, target)


def replace_from_excel_rows(
    users: list[dict],
    tasks: list[dict],
    photos: list[dict],
    responses: list[dict],
    reviews: list[dict],
    favorites: list[dict] | None = None,
    reports: list[dict] | None = None,
    task_events: list[dict] | None = None,
    admin_actions: list[dict] | None = None,
):
    favorites = favorites or []
    reports = reports or []
    task_events = task_events or []
    admin_actions = admin_actions or []
    with get_connection() as conn:
        cur = conn.cursor()
        for table in ['task_photos', 'task_responses', 'reviews', 'favorites', 'reports', 'task_events', 'tasks', 'users', 'admin_actions', 'admin_sessions']:
            cur.execute(f'DELETE FROM {table}')

        if users:
            cur.executemany(
                '''
                INSERT INTO users (id, telegram_id, username, full_name, phone, role, city, specialization, about, rating, reviews_count, is_active, is_banned, banned_reason, created_at, updated_at)
                VALUES (:id, :telegram_id, :username, :full_name, :phone, :role, :city, :specialization, :about, :rating, :reviews_count, :is_active, :is_banned, :banned_reason, :created_at, :updated_at)
                ''',
                users,
            )
        if tasks:
            cur.executemany(
                '''
                INSERT INTO tasks (id, customer_id, city, category, title, description, budget, address, latitude, longitude, contact_text, status, selected_response_id, rejection_reason, views_count, responses_count, is_urgent, bumped_at, expires_at, created_at, updated_at)
                VALUES (:id, :customer_id, :city, :category, :title, :description, :budget, :address, :latitude, :longitude, :contact_text, :status, :selected_response_id, :rejection_reason, :views_count, :responses_count, :is_urgent, :bumped_at, :expires_at, :created_at, :updated_at)
                ''',
                tasks,
            )
        if photos:
            cur.executemany('INSERT INTO task_photos (id, task_id, file_id, created_at) VALUES (:id, :task_id, :file_id, :created_at)', photos)
        if responses:
            cur.executemany(
                '''
                INSERT INTO task_responses (id, task_id, worker_id, message, offer_price, contact_text, status, created_at, updated_at)
                VALUES (:id, :task_id, :worker_id, :message, :offer_price, :contact_text, :status, :created_at, :updated_at)
                ''',
                responses,
            )
        if reviews:
            cur.executemany(
                '''
                INSERT INTO reviews (id, task_id, response_id, worker_id, customer_id, rating, text, created_at)
                VALUES (:id, :task_id, :response_id, :worker_id, :customer_id, :rating, :text, :created_at)
                ''',
                reviews,
            )
        if favorites:
            cur.executemany(
                'INSERT INTO favorites (id, worker_id, task_id, created_at) VALUES (:id, :worker_id, :task_id, :created_at)',
                favorites,
            )
        if reports:
            cur.executemany(
                '''
                INSERT INTO reports (id, reporter_id, task_id, target_user_id, reason, status, created_at, updated_at)
                VALUES (:id, :reporter_id, :task_id, :target_user_id, :reason, :status, :created_at, :updated_at)
                ''',
                reports,
            )
        if task_events:
            cur.executemany(
                '''
                INSERT INTO task_events (id, task_id, actor_user_id, event_type, details, created_at)
                VALUES (:id, :task_id, :actor_user_id, :event_type, :details, :created_at)
                ''',
                task_events,
            )
        if admin_actions:
            cur.executemany(
                '''
                INSERT INTO admin_actions (id, admin_tg_id, action, entity_type, entity_id, details, created_at)
                VALUES (:id, :admin_tg_id, :action, :entity_type, :entity_id, :details, :created_at)
                ''',
                admin_actions,
            )

        cur.execute("DELETE FROM sqlite_sequence WHERE name IN ('users','tasks','task_photos','task_responses','reviews','favorites','reports','task_events','admin_actions','admin_sessions')")
