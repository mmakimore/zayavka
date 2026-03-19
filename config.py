import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
LOG_DIR = BASE_DIR / 'logs'
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
BOT_USERNAME = os.getenv('BOT_USERNAME', '').lstrip('@')
DATABASE_PATH = os.getenv('DATABASE_PATH', str(DATA_DIR / 'job_bot_v4.db'))
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '').strip()
ADMIN_SESSION_HOURS = int(os.getenv('ADMIN_SESSION_HOURS', '12'))
MAX_PHOTOS_PER_TASK = int(os.getenv('MAX_PHOTOS_PER_TASK', '5'))
MAX_BROADCAST_PER_RUN = int(os.getenv('MAX_BROADCAST_PER_RUN', '2000'))
DEFAULT_PAGE_SIZE = int(os.getenv('DEFAULT_PAGE_SIZE', '5'))
TASK_LIFETIME_DAYS = int(os.getenv('TASK_LIFETIME_DAYS', '14'))
BUMP_COOLDOWN_HOURS = int(os.getenv('BUMP_COOLDOWN_HOURS', '12'))
RATE_LIMIT_SECONDS = float(os.getenv('RATE_LIMIT_SECONDS', '0.7'))
MAX_TEXT_FIELD = int(os.getenv('MAX_TEXT_FIELD', '1200'))
MAX_TITLE_FIELD = int(os.getenv('MAX_TITLE_FIELD', '120'))
MAX_REPORT_REASON = int(os.getenv('MAX_REPORT_REASON', '500'))
AUTO_ARCHIVE_ENABLED = os.getenv('AUTO_ARCHIVE_ENABLED', '1').strip() not in {'0', 'false', 'False'}
AUTO_ARCHIVE_INTERVAL_SECONDS = int(os.getenv('AUTO_ARCHIVE_INTERVAL_SECONDS', '1800'))


def _parse_ids(raw: str) -> set[int]:
    result: set[int] = set()
    for part in (raw or '').replace(' ', '').split(','):
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError:
            continue
    return result


ADMIN_TG_IDS = _parse_ids(os.getenv('ADMIN_TG_IDS', ''))

CITIES = [
    'Воскресенск',
    'Раменское',
    'Бронницы',
    'Коломна',
    'Носковарецкий',
    'Гигант',
    'Лопатинский',
]

CATEGORIES = [
    'Разнорабочий',
    'Электрик',
    'Сантехник',
    'Сварщик',
    'Отделка и ремонт',
    'Грузчики',
    'Уборка',
    'Доставка',
    'Строительство',
    'Спецтехника',
    'Другое',
]

WELCOME_TEXT = (
    '👋 <b>Добро пожаловать в бот заявок заказчик ↔ исполнитель</b>\n\n'
    'Здесь есть 2 роли:\n'
    '• <b>Заказчик</b> — создаёт заявки, прикрепляет фото, выбирает исполнителя.\n'
    '• <b>Исполнитель</b> — ищет заявки, фильтрует их, сохраняет в избранное и откликается.\n\n'
    'Внутри уже есть модерация, фото, маршрут, кнопка поделиться, избранное, жалобы, автоархив, резервные копии, выгрузки и админ-панель.'
)

HELP_TEXT = (
    'ℹ️ <b>Как пользоваться ботом</b>\n\n'
    '1. Нажми /start и зарегистрируйся.\n'
    '2. Заказчик создаёт заявку, может прикрепить фото и адрес.\n'
    '3. Исполнитель открывает поиск, фильтрует заявки, сохраняет в избранное и отправляет отклик.\n'
    '4. Заказчик выбирает исполнителя и закрывает заявку после выполнения.\n'
    '5. При нарушениях можно отправить жалобу, а админ увидит её в панели.\n\n'
    'Команды:\n'
    '/start — старт\n'
    '/admin — вход в админку\n'
    '/ping — проверка, что бот жив\n'
    '/cancel — сброс текущего шага'
)
