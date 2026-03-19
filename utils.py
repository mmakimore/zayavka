from __future__ import annotations

import html
import re
from datetime import datetime
from urllib.parse import quote_plus

from config import BOT_USERNAME


STATUS_LABELS = {
    'pending': '🕓 На модерации',
    'open': '🟢 Открыта',
    'in_progress': '🟡 В работе',
    'closed': '✅ Закрыта',
    'rejected': '❌ Отклонена',
    'archived': '📦 Архив',
    'draft': '📝 Черновик',
}

REPORT_STATUS_LABELS = {
    'open': '🆘 Открыта',
    'closed': '✅ Закрыта',
}

ROLE_LABELS = {
    'customer': 'Заказчик',
    'worker': 'Исполнитель',
    'admin': 'Администратор',
}


def h(value) -> str:
    return html.escape(str(value or ''))


def clip(text: str | None, limit: int = 3900) -> str:
    text = (text or '').strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + '…'


def parse_int(text: str | None) -> int | None:
    raw = ''.join(ch for ch in (text or '') if ch.isdigit())
    if not raw:
        return None
    return int(raw)


def normalize_phone(text: str | None) -> str:
    value = (text or '').strip()
    return re.sub(r'\s+', ' ', value)


def format_dt(value: str | None) -> str:
    if not value:
        return '—'
    try:
        return datetime.fromisoformat(value).strftime('%d.%m.%Y %H:%M')
    except Exception:
        return str(value)


def task_route_url(task: dict) -> str | None:
    lat = task.get('latitude')
    lon = task.get('longitude')
    if lat is not None and lon is not None:
        return f'https://yandex.ru/maps/?rtext=~{lat},{lon}&rtt=auto'
    address = (task.get('address') or '').strip()
    city = (task.get('city') or '').strip()
    target = ', '.join(part for part in [city, address] if part)
    if not target:
        return None
    return f'https://yandex.ru/maps/?text={quote_plus(target)}'


def task_share_url(task_id: int, title: str = '') -> str | None:
    if not BOT_USERNAME:
        return None
    url = f'https://t.me/{BOT_USERNAME}?start=task_{task_id}'
    text = f'Смотри заявку: {title}'.strip()
    return f'https://t.me/share/url?url={quote_plus(url)}&text={quote_plus(text)}'


def task_card(task: dict, full: bool = False) -> str:
    urgent = '🔥 Срочная\n' if int(task.get('is_urgent') or 0) else ''
    text = (
        f'🧾 <b>Заявка #{task["id"]}</b>\n'
        f'{urgent}'
        f'<b>{h(task.get("title"))}</b>\n\n'
        f'🏙 Город: {h(task.get("city"))}\n'
        f'🧰 Категория: {h(task.get("category"))}\n'
        f'💰 Бюджет: {int(task.get("budget") or 0)} ₽\n'
        f'📌 Статус: {STATUS_LABELS.get(task.get("status"), task.get("status") or "—")}\n'
        f'👁 Просмотров: {int(task.get("views_count") or 0)}\n'
        f'💬 Откликов: {int(task.get("responses_count") or 0)}\n'
    )
    if task.get('address'):
        text += f'📍 Адрес: {h(task.get("address"))}\n'
    if task.get('expires_at'):
        text += f'⏳ До: {h(format_dt(task.get("expires_at")))}\n'
    if full:
        text += '\n<b>Описание:</b>\n' + h(task.get('description') or '—') + '\n'
        if task.get('contact_text'):
            text += '\n<b>Контакт:</b>\n' + h(task.get('contact_text')) + '\n'
        if task.get('customer_name'):
            text += f'\n👤 Заказчик: {h(task.get("customer_name"))}\n'
        if task.get('rejection_reason') and task.get('status') == 'rejected':
            text += f'\n❌ Причина отклонения: {h(task.get("rejection_reason"))}\n'
    return clip(text)


def response_card(response: dict, full: bool = True) -> str:
    text = (
        f'💬 <b>Отклик #{response["id"]}</b>\n'
        f'Исполнитель: {h(response.get("worker_name"))}\n'
        f'Город: {h(response.get("worker_city"))}\n'
        f'Статус: {h(response.get("status"))}\n'
        f'⭐ Рейтинг: {response.get("worker_rating") or 0} ({response.get("worker_reviews_count") or 0} отзывов)\n'
    )
    if response.get('offer_price'):
        text += f'Предложение: {int(response.get("offer_price") or 0)} ₽\n'
    if response.get('worker_specialization'):
        text += f'Специализация: {h(response.get("worker_specialization"))}\n'
    if response.get('contact_text'):
        text += f'Контакт: {h(response.get("contact_text"))}\n'
    if full:
        text += '\n<b>Сообщение:</b>\n' + h(response.get('message') or '—')
        if response.get('worker_about'):
            text += '\n\n<b>О себе:</b>\n' + h(response.get('worker_about'))
    return clip(text)


def report_card(report: dict) -> str:
    return clip(
        f'🆘 <b>Жалоба #{report["id"]}</b>\n'
        f'Статус: {REPORT_STATUS_LABELS.get(report.get("status"), report.get("status") or "—")}\n'
        f'От: {h(report.get("reporter_name") or "—")}\n'
        f'На заявку: #{h(report.get("task_id") or "—")} {h(report.get("task_title") or "")}\n'
        f'На пользователя: {h(report.get("target_user_name") or "—")}\n'
        f'Создано: {h(format_dt(report.get("created_at")))}\n\n'
        f'<b>Причина:</b>\n{h(report.get("reason") or "—")}'
    )


def event_card(event: dict) -> str:
    return clip(
        f'📝 {h(format_dt(event.get("created_at")))}\n'
        f'Событие: {h(event.get("event_type"))}\n'
        f'Кто: {h(event.get("actor_name") or "система")}\n'
        f'Детали: {h(event.get("details") or "—")}'
    )


def make_rows(items: list[str], size: int = 2) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]
