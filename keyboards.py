from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from config import CATEGORIES, CITIES
from utils import make_rows, task_route_url, task_share_url


def main_menu(role: str | None = None, is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    if not role:
        rows = [[KeyboardButton(text='🚀 Начать')], [KeyboardButton(text='ℹ️ Помощь')]]
    elif role == 'customer':
        rows = [
            [KeyboardButton(text='➕ Создать заявку')],
            [KeyboardButton(text='📋 Мои заявки'), KeyboardButton(text='👤 Мой профиль')],
            [KeyboardButton(text='ℹ️ Помощь')],
        ]
    elif role == 'worker':
        rows = [
            [KeyboardButton(text='🔎 Искать заявки')],
            [KeyboardButton(text='⭐ Избранное'), KeyboardButton(text='📨 Мои отклики')],
            [KeyboardButton(text='👤 Мой профиль'), KeyboardButton(text='🏆 Топ исполнителей')],
            [KeyboardButton(text='ℹ️ Помощь')],
        ]
    else:
        rows = [[KeyboardButton(text='👤 Мой профиль')], [KeyboardButton(text='ℹ️ Помощь')]]

    if is_admin:
        rows.append([KeyboardButton(text='🛠 Админ-панель')])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def role_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🧑‍💼 Заказчик', callback_data='reg_role:customer')],
            [InlineKeyboardButton(text='🧑‍🔧 Исполнитель', callback_data='reg_role:worker')],
        ]
    )


def cities_kb(prefix: str, include_all: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    items = ['Все города'] + CITIES if include_all else CITIES
    for row in make_rows(items, 2):
        buttons.append([
            InlineKeyboardButton(text=item, callback_data=f'{prefix}:{"all" if item == "Все города" else item}') for item in row
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def categories_kb(prefix: str, include_all: bool = False) -> InlineKeyboardMarkup:
    items = ['Все категории'] + CATEGORIES if include_all else CATEGORIES
    buttons = []
    for row in make_rows(items, 2):
        buttons.append([
            InlineKeyboardButton(text=item, callback_data=f'{prefix}:{"all" if item == "Все категории" else item}') for item in row
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def skip_kb(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='⏭ Пропустить', callback_data=callback_data)]])


def done_photos_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Готово', callback_data='task_photos_done')]])


def task_actions_kb(task: dict, viewer_role: str, can_manage: bool = False, is_favorite: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if viewer_role == 'worker' and task.get('status') == 'open':
        rows.append([InlineKeyboardButton(text='💬 Откликнуться', callback_data=f'respond:{task["id"]}')])
        rows.append([
            InlineKeyboardButton(text='⭐ Убрать из избранного' if is_favorite else '⭐ В избранное', callback_data=f'favorite_toggle:{task["id"]}')
        ])
        rows.append([InlineKeyboardButton(text='🆘 Пожаловаться', callback_data=f'report_task:{task["id"]}')])
    if can_manage:
        rows.append([InlineKeyboardButton(text='👀 Отклики', callback_data=f'task_responses:{task["id"]}')])
        if task.get('status') in {'open', 'pending'}:
            rows.append([InlineKeyboardButton(text='📣 Поднять заявку', callback_data=f'task_bump:{task["id"]}')])
        if task.get('status') in {'open', 'in_progress'}:
            rows.append([InlineKeyboardButton(text='✅ Закрыть заявку', callback_data=f'task_close:{task["id"]}')])
    route_url = task_route_url(task)
    if route_url:
        rows.append([InlineKeyboardButton(text='🗺 Построить маршрут', url=route_url)])
    share_url = task_share_url(task['id'], task.get('title', ''))
    if share_url:
        rows.append([InlineKeyboardButton(text='📤 Поделиться', url=share_url)])
    rows.append([InlineKeyboardButton(text='🔙 Назад', callback_data='back_to_list')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_task_manage_kb(task_id: int, status: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text='👀 Отклики', callback_data=f'task_responses:{task_id}')]]
    if status in {'open', 'pending'}:
        rows.append([InlineKeyboardButton(text='📣 Поднять заявку', callback_data=f'task_bump:{task_id}')])
    if status in {'open', 'in_progress'}:
        rows.append([InlineKeyboardButton(text='✅ Закрыть заявку', callback_data=f'task_close:{task_id}')])
    rows.append([InlineKeyboardButton(text='🔙 К моим заявкам', callback_data='my_tasks_back')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def response_actions_kb(response_id: int, task_id: int, status: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if status == 'sent':
        rows.append([InlineKeyboardButton(text='✅ Выбрать исполнителя', callback_data=f'accept_response:{task_id}:{response_id}')])
        rows.append([InlineKeyboardButton(text='❌ Отклонить', callback_data=f'reject_response:{task_id}:{response_id}')])
    rows.append([InlineKeyboardButton(text='🔙 К откликам', callback_data=f'task_responses:{task_id}')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rate_keyboard(task_id: int, worker_id: int, response_id: int | None) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(text='⭐', callback_data=f'rate:{task_id}:{worker_id}:{response_id or 0}:1'),
        InlineKeyboardButton(text='⭐⭐', callback_data=f'rate:{task_id}:{worker_id}:{response_id or 0}:2'),
        InlineKeyboardButton(text='⭐⭐⭐', callback_data=f'rate:{task_id}:{worker_id}:{response_id or 0}:3'),
        InlineKeyboardButton(text='⭐⭐⭐⭐', callback_data=f'rate:{task_id}:{worker_id}:{response_id or 0}:4'),
        InlineKeyboardButton(text='⭐⭐⭐⭐⭐', callback_data=f'rate:{task_id}:{worker_id}:{response_id or 0}:5'),
    ]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_login_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔐 Войти в админку', callback_data='admin_login')]])


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🕓 Заявки на модерации', callback_data='admin_pending')],
            [InlineKeyboardButton(text='📋 Все заявки', callback_data='admin_all_tasks')],
            [InlineKeyboardButton(text='👥 Пользователи', callback_data='admin_users')],
            [InlineKeyboardButton(text='🧑‍🔧 Исполнители', callback_data='admin_workers')],
            [InlineKeyboardButton(text='🆘 Жалобы', callback_data='admin_reports')],
            [InlineKeyboardButton(text='🔎 Поиск', callback_data='admin_search')],
            [InlineKeyboardButton(text='📊 Статистика', callback_data='admin_stats')],
            [InlineKeyboardButton(text='📢 Рассылка', callback_data='admin_broadcast')],
            [InlineKeyboardButton(text='💾 Выгрузить базу', callback_data='admin_export_db')],
            [InlineKeyboardButton(text='📊 Выгрузить Excel', callback_data='admin_export_excel')],
            [InlineKeyboardButton(text='♻️ Восстановить базу', callback_data='admin_restore')],
            [InlineKeyboardButton(text='🚪 Выйти', callback_data='admin_logout')],
        ]
    )


def admin_task_actions_kb(task_id: int, status: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if status == 'pending':
        rows.append([InlineKeyboardButton(text='✅ Одобрить', callback_data=f'admin_task_approve:{task_id}')])
        rows.append([InlineKeyboardButton(text='❌ Отклонить', callback_data=f'admin_task_reject:{task_id}')])
    if status in {'open', 'pending'}:
        rows.append([InlineKeyboardButton(text='📣 Поднять', callback_data=f'admin_task_bump:{task_id}')])
    rows.append([InlineKeyboardButton(text='📝 История', callback_data=f'admin_task_events:{task_id}')])
    rows.append([InlineKeyboardButton(text='👀 Отклики', callback_data=f'admin_task_responses:{task_id}')])
    rows.append([InlineKeyboardButton(text='🗑 Удалить', callback_data=f'admin_task_delete:{task_id}')])
    rows.append([InlineKeyboardButton(text='🔙 Панель', callback_data='admin_panel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_actions_kb(user_id: int, is_banned: bool, role: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if is_banned:
        rows.append([InlineKeyboardButton(text='🔓 Разбанить', callback_data=f'admin_unban:{user_id}')])
    else:
        rows.append([InlineKeyboardButton(text='🚫 Бан', callback_data=f'admin_ban:{user_id}')])
    rows.append([InlineKeyboardButton(text='🆘 Жалобы на пользователя', callback_data=f'admin_user_reports:{user_id}')])
    rows.append([InlineKeyboardButton(text='🔙 К списку', callback_data=f'admin_list_role:{role}')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_restore_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='📦 Из файла базы (.db)', callback_data='admin_restore_db')],
            [InlineKeyboardButton(text='📊 Из Excel (.xlsx)', callback_data='admin_restore_excel_file')],
            [InlineKeyboardButton(text='🔙 Панель', callback_data='admin_panel')],
        ]
    )


def admin_broadcast_target_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='👥 Всем', callback_data='broadcast_target:all')],
            [InlineKeyboardButton(text='🧑‍💼 Только заказчикам', callback_data='broadcast_target:customer')],
            [InlineKeyboardButton(text='🧑‍🔧 Только исполнителям', callback_data='broadcast_target:worker')],
            [InlineKeyboardButton(text='🔙 Панель', callback_data='admin_panel')],
        ]
    )


def admin_report_actions_kb(report_id: int, status: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if status == 'open':
        rows.append([InlineKeyboardButton(text='✅ Закрыть жалобу', callback_data=f'admin_report_close:{report_id}')])
    rows.append([InlineKeyboardButton(text='🔙 Панель', callback_data='admin_panel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)
