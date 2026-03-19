from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Message

import database as db
from config import (
    ADMIN_TG_IDS,
    DEFAULT_PAGE_SIZE,
    HELP_TEXT,
    MAX_PHOTOS_PER_TASK,
    MAX_REPORT_REASON,
    MAX_TEXT_FIELD,
    MAX_TITLE_FIELD,
    WELCOME_TEXT,
)
from keyboards import (
    admin_login_kb,
    categories_kb,
    cities_kb,
    done_photos_kb,
    main_menu,
    my_task_manage_kb,
    rate_keyboard,
    response_actions_kb,
    role_kb,
    skip_kb,
    task_actions_kb,
)
from utils import ROLE_LABELS, h, parse_int, response_card, task_card

router = Router()
logger = logging.getLogger(__name__)


class RegistrationStates(StatesGroup):
    waiting_phone = State()
    waiting_specialization = State()
    waiting_about = State()


class CreateTaskStates(StatesGroup):
    waiting_city = State()
    waiting_category = State()
    waiting_title = State()
    waiting_description = State()
    waiting_budget = State()
    waiting_address = State()
    waiting_location = State()
    waiting_photos = State()
    waiting_contact = State()


class BrowseStates(StatesGroup):
    waiting_city = State()
    waiting_category = State()


class RespondTaskStates(StatesGroup):
    waiting_message = State()
    waiting_price = State()
    waiting_contact = State()


class ReviewStates(StatesGroup):
    waiting_text = State()


class ReportStates(StatesGroup):
    waiting_reason = State()


# ===== Helpers =====

def is_admin_tg(tg_id: int) -> bool:
    return tg_id in ADMIN_TG_IDS or db.has_active_admin_session(tg_id)


async def user_menu(message: Message, user: dict | None = None):
    if not user:
        user = db.get_user_by_tg(message.from_user.id)
    role = user['role'] if user else None
    await message.answer('Меню открыто.', reply_markup=main_menu(role, is_admin_tg(message.from_user.id)))


async def ensure_registered_message(message: Message):
    user = db.get_user_by_tg(message.from_user.id)
    if not user:
        await message.answer('Сначала нажми /start и зарегистрируйся.', reply_markup=main_menu())
        return None
    if user.get('is_banned'):
        await message.answer(f'Ваш аккаунт заблокирован. Причина: {user.get("banned_reason") or "не указана"}')
        return None
    return user


async def ensure_registered_callback(callback: CallbackQuery):
    user = db.get_user_by_tg(callback.from_user.id)
    if not user:
        await callback.answer('Сначала зарегистрируйся через /start', show_alert=True)
        return None
    if user.get('is_banned'):
        await callback.answer('Ваш аккаунт заблокирован.', show_alert=True)
        return None
    return user


async def notify_admins(bot, text: str, reply_markup=None):
    receivers = set(ADMIN_TG_IDS)
    for admin in db.list_users(role='admin', limit=1000):
        receivers.add(admin['telegram_id'])
    for tg_id in receivers:
        try:
            await bot.send_message(tg_id, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        except Exception:
            logger.exception('Failed to notify admin %s', tg_id)


async def notify_user(bot, tg_id: int | None, text: str, reply_markup=None):
    if not tg_id:
        return
    try:
        await bot.send_message(tg_id, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    except Exception:
        logger.exception('Failed to notify user %s', tg_id)


async def show_task_details(target: Message | CallbackQuery, task_id: int, viewer_role: str | None = None, viewer_user: dict | None = None):
    task = db.get_task(task_id)
    if not task:
        if isinstance(target, CallbackQuery):
            await target.answer('Заявка не найдена', show_alert=True)
        else:
            await target.answer('Заявка не найдена')
        return

    if not viewer_user:
        tg_id = target.from_user.id if isinstance(target, (Message, CallbackQuery)) else None
        viewer_user = db.get_user_by_tg(tg_id) if tg_id else None
    viewer_role = viewer_role or (viewer_user['role'] if viewer_user else None)
    can_manage = bool(viewer_user and (viewer_user['id'] == task['customer_id'] or is_admin_tg(viewer_user['telegram_id'])))
    is_fav = bool(viewer_user and viewer_user['role'] == 'worker' and db.is_favorite(viewer_user['id'], task_id))

    if viewer_user and viewer_user['role'] == 'worker' and task['status'] == 'open':
        db.add_task_view(task_id)
        task = db.get_task(task_id)

    caption = task_card(task, full=True)
    markup = task_actions_kb(task, viewer_role or 'customer', can_manage=can_manage, is_favorite=is_fav)

    chat_id = target.message.chat.id if isinstance(target, CallbackQuery) else target.chat.id
    bot = target.message.bot if isinstance(target, CallbackQuery) else target.bot
    photos = task.get('photos') or []
    if photos:
        if len(photos) > 1:
            remaining = photos[1:10]
            if remaining:
                media = [InputMediaPhoto(media=file_id) for file_id in remaining]
                await bot.send_media_group(chat_id=chat_id, media=media)
        if isinstance(target, CallbackQuery):
            await target.message.answer_photo(photos[0], caption=caption, reply_markup=markup, parse_mode=ParseMode.HTML)
        else:
            await target.answer_photo(photos[0], caption=caption, reply_markup=markup, parse_mode=ParseMode.HTML)
    else:
        if isinstance(target, CallbackQuery):
            await target.message.answer(caption, reply_markup=markup, parse_mode=ParseMode.HTML)
        else:
            await target.answer(caption, reply_markup=markup, parse_mode=ParseMode.HTML)


async def send_browse_list(message: Message | CallbackQuery, state: FSMContext, source: str = 'browse'):
    data = await state.get_data()
    city = data.get(f'{source}_city', 'all')
    category = data.get(f'{source}_category', 'all')
    page = int(data.get(f'{source}_page', 0) or 0)
    if source == 'favorites':
        user = db.get_user_by_tg(message.from_user.id if isinstance(message, Message) else message.from_user.id)
        tasks = db.get_favorite_tasks(user['id'], limit=100) if user else []
        tasks = tasks[page * DEFAULT_PAGE_SIZE:(page + 1) * DEFAULT_PAGE_SIZE]
        title = '⭐ <b>Избранные заявки</b>'
    else:
        tasks = db.get_tasks(city=city, category=category, status='open', limit=DEFAULT_PAGE_SIZE, offset=page * DEFAULT_PAGE_SIZE)
        title = '🔎 <b>Поиск заявок</b>'

    text = f'{title}\n\n'
    if source != 'favorites':
        text += f'Город: {h(city)}\nКатегория: {h(category)}\nСтраница: {page + 1}\n\n'
    else:
        text += f'Страница: {page + 1}\n\n'
    if not tasks:
        text += 'Подходящих заявок пока нет.'
    else:
        text += 'Выбери заявку:\n'

    buttons: list[list[InlineKeyboardButton]] = []
    if source != 'favorites':
        buttons.append([
            InlineKeyboardButton(text=f'🏙 {city}', callback_data='browse_city_menu'),
            InlineKeyboardButton(text=f'🧰 {category}', callback_data='browse_category_menu'),
        ])
    for task in tasks:
        badge = '🔥 ' if int(task.get('is_urgent') or 0) else ''
        buttons.append([InlineKeyboardButton(text=f'{badge}#{task["id"]} · {task["title"][:24]} · {task["budget"]}₽', callback_data=f'open_task:{task["id"]}')])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text='⬅️', callback_data=f'{source}_page:prev'))
    nav.append(InlineKeyboardButton(text='🔄', callback_data=f'{source}_page:refresh'))
    if len(tasks) == DEFAULT_PAGE_SIZE:
        nav.append(InlineKeyboardButton(text='➡️', callback_data=f'{source}_page:next'))
    buttons.append(nav)
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)

    if isinstance(message, CallbackQuery):
        await message.message.answer(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        await message.answer()
    else:
        await message.answer(text, reply_markup=markup, parse_mode=ParseMode.HTML)


async def send_my_tasks_list(message: Message):
    user = await ensure_registered_message(message)
    if not user or user['role'] != 'customer':
        return
    tasks = db.get_customer_tasks(user['id'])
    if not tasks:
        await message.answer('У тебя пока нет заявок.')
        return
    buttons = []
    for task in tasks[:20]:
        buttons.append([InlineKeyboardButton(text=f'#{task["id"]} · {task["title"][:28]} · {task["status"]}', callback_data=f'open_task:{task["id"]}')])
    buttons.append([InlineKeyboardButton(text='🔙 Меню', callback_data='ignore')])
    await message.answer('📋 <b>Мои заявки</b>\nВыбери нужную:', reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)


# ===== System =====

@router.message(Command('ping'))
async def ping_cmd(message: Message):
    await message.answer('✅ Бот работает')


@router.message(Command('cancel'))
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    user = db.get_user_by_tg(message.from_user.id)
    await message.answer('Текущий шаг сброшен.', reply_markup=main_menu(user['role'], is_admin_tg(message.from_user.id)) if user else main_menu())


# ===== Start / help / profile =====

@router.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    parts = (message.text or '').split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ''
    user = db.get_user_by_tg(message.from_user.id)
    if user:
        await message.answer(
            f'С возвращением, <b>{h(user["full_name"])}</b>!\nРоль: {ROLE_LABELS.get(user["role"], user["role"])}',
            reply_markup=main_menu(user['role'], is_admin_tg(message.from_user.id)),
            parse_mode=ParseMode.HTML,
        )
        if arg.startswith('task_'):
            task_id = parse_int(arg)
            if task_id:
                await show_task_details(message, task_id, viewer_user=user)
        return

    await message.answer(WELCOME_TEXT, reply_markup=main_menu())
    if arg.startswith('task_'):
        task_id = parse_int(arg)
        if task_id:
            task = db.get_task(task_id)
            if task and task['status'] == 'open':
                await message.answer('После регистрации ты сможешь сразу открыть эту заявку.')
    await message.answer('Выбери роль для регистрации:', reply_markup=role_kb())
    if ADMIN_TG_IDS or db.has_active_admin_session(message.from_user.id):
        await message.answer('Доступ в админку:', reply_markup=admin_login_kb())


@router.message(F.text == '🚀 Начать')
async def quick_start(message: Message):
    user = db.get_user_by_tg(message.from_user.id)
    if user:
        await user_menu(message, user)
        return
    await message.answer('Выбери роль для регистрации:', reply_markup=role_kb())


@router.message(F.text == 'ℹ️ Помощь')
async def help_cmd(message: Message):
    await message.answer(HELP_TEXT, parse_mode=ParseMode.HTML)


@router.message(F.text == '👤 Мой профиль')
async def profile_cmd(message: Message):
    user = await ensure_registered_message(message)
    if not user:
        return
    text = (
        f'👤 <b>Профиль</b>\n\n'
        f'Имя: {h(user["full_name"])}\n'
        f'Роль: {ROLE_LABELS.get(user["role"], user["role"])}\n'
        f'Город: {h(user.get("city") or "—")}\n'
        f'Телефон: {h(user.get("phone") or "—")}\n'
    )
    if user['role'] == 'worker':
        text += (
            f'Специализация: {h(user.get("specialization") or "—")}\n'
            f'О себе: {h(user.get("about") or "—")}\n'
            f'Рейтинг: {user.get("rating") or 0} ({user.get("reviews_count") or 0} отзывов)\n'
        )
    if user.get('is_banned'):
        text += f'\n🚫 Заблокирован: {h(user.get("banned_reason") or "да")}\n'
    await message.answer(text, reply_markup=main_menu(user['role'], is_admin_tg(message.from_user.id)), parse_mode=ParseMode.HTML)


@router.message(F.text == '🏆 Топ исполнителей')
async def top_workers(message: Message):
    user = await ensure_registered_message(message)
    if not user:
        return
    workers = db.get_top_workers(limit=10)
    if not workers:
        await message.answer('Пока ещё нет рейтинга исполнителей.')
        return
    text = '🏆 <b>Топ исполнителей</b>\n\n'
    for idx, worker in enumerate(workers, 1):
        text += f'{idx}. {h(worker.get("full_name"))} — ⭐ {worker.get("rating") or 0} ({worker.get("reviews_count") or 0} отзывов)\n'
    await message.answer(text, parse_mode=ParseMode.HTML)


# ===== Registration =====

@router.callback_query(F.data.startswith('reg_role:'))
async def choose_role(callback: CallbackQuery, state: FSMContext):
    role = callback.data.split(':', 1)[1]
    await state.update_data(role=role)
    await callback.message.edit_text('Выбери свой город:', reply_markup=cities_kb('reg_city'))
    await callback.answer()


@router.callback_query(F.data.startswith('reg_city:'))
async def choose_reg_city(callback: CallbackQuery, state: FSMContext):
    city = callback.data.split(':', 1)[1]
    data = await state.get_data()
    await state.update_data(city=city)
    if data.get('role') == 'worker':
        await callback.message.edit_text('Напиши специализацию. Например: электрик, сварщик, разнорабочий.')
        await state.set_state(RegistrationStates.waiting_specialization)
    else:
        await callback.message.edit_text('Отправь номер телефона для связи текстом.')
        await state.set_state(RegistrationStates.waiting_phone)
    await callback.answer()


@router.message(RegistrationStates.waiting_specialization)
async def reg_worker_specialization(message: Message, state: FSMContext):
    text = (message.text or '').strip()
    if len(text) < 2:
        await message.answer('Напиши специализацию чуть подробнее.')
        return
    await state.update_data(specialization=text[:120])
    await message.answer('Коротко напиши о себе: опыт, что умеешь, как работаешь.')
    await state.set_state(RegistrationStates.waiting_about)


@router.message(RegistrationStates.waiting_about)
async def reg_worker_about(message: Message, state: FSMContext):
    text = (message.text or '').strip()
    if len(text) < 5:
        await message.answer('Нужно чуть подробнее описать себя.')
        return
    await state.update_data(about=text[:MAX_TEXT_FIELD])
    await message.answer('Теперь отправь номер телефона или @username для связи.')
    await state.set_state(RegistrationStates.waiting_phone)


@router.message(RegistrationStates.waiting_phone)
async def reg_phone(message: Message, state: FSMContext):
    phone = (message.text or '').strip()
    if len(phone) < 5:
        await message.answer('Укажи контакт нормально: телефон или Telegram.')
        return
    data = await state.get_data()
    user = db.create_or_update_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username or '',
        full_name=message.from_user.full_name,
        role=data['role'],
        city=data['city'],
        phone=phone[:120],
        specialization=data.get('specialization'),
        about=data.get('about'),
    )
    await state.clear()
    await message.answer('Регистрация завершена ✅', reply_markup=main_menu(user['role'], is_admin_tg(message.from_user.id)))


# ===== Create task =====

@router.message(F.text == '➕ Создать заявку')
async def start_create_task(message: Message, state: FSMContext):
    user = await ensure_registered_message(message)
    if not user:
        return
    if user['role'] != 'customer':
        await message.answer('Эта функция доступна только заказчику.')
        return
    await state.clear()
    await state.set_state(CreateTaskStates.waiting_city)
    await message.answer('Выбери город заявки:', reply_markup=cities_kb('task_city'))


@router.callback_query(F.data.startswith('task_city:'))
async def task_city(callback: CallbackQuery, state: FSMContext):
    await state.update_data(city=callback.data.split(':', 1)[1], photos=[])
    await state.set_state(CreateTaskStates.waiting_category)
    await callback.message.edit_text('Теперь выбери категорию работы:', reply_markup=categories_kb('task_category'))
    await callback.answer()


@router.callback_query(F.data.startswith('task_category:'))
async def task_category(callback: CallbackQuery, state: FSMContext):
    await state.update_data(category=callback.data.split(':', 1)[1])
    await state.set_state(CreateTaskStates.waiting_title)
    await callback.message.edit_text('Напиши короткий заголовок заявки.\nНапример: «Нужен сварщик на 1 день»')
    await callback.answer()


@router.message(CreateTaskStates.waiting_title)
async def task_title(message: Message, state: FSMContext):
    text = (message.text or '').strip()
    if len(text) < 5:
        await message.answer('Заголовок слишком короткий.')
        return
    await state.update_data(title=text[:MAX_TITLE_FIELD])
    await state.set_state(CreateTaskStates.waiting_description)
    await message.answer('Опиши задачу подробнее.')


@router.message(CreateTaskStates.waiting_description)
async def task_description(message: Message, state: FSMContext):
    text = (message.text or '').strip()
    if len(text) < 10:
        await message.answer('Описание слишком короткое.')
        return
    await state.update_data(description=text[:MAX_TEXT_FIELD])
    await state.set_state(CreateTaskStates.waiting_budget)
    await message.answer('Укажи цену в рублях, только числом.')


@router.message(CreateTaskStates.waiting_budget)
async def task_budget(message: Message, state: FSMContext):
    value = parse_int(message.text)
    if not value or value <= 0:
        await message.answer('Нужно ввести цену числом. Например: 5000')
        return
    await state.update_data(budget=value)
    await state.set_state(CreateTaskStates.waiting_address)
    await message.answer('Напиши адрес или ориентир.')
    await message.answer('Если адрес пока не нужен, нажми пропустить.', reply_markup=skip_kb('task_skip_address'))


@router.callback_query(F.data == 'task_skip_address')
async def task_skip_address(callback: CallbackQuery, state: FSMContext):
    await state.update_data(address=None)
    await state.set_state(CreateTaskStates.waiting_location)
    await callback.message.answer('Теперь можешь отправить геолокацию для кнопки маршрута или нажми пропустить.', reply_markup=skip_kb('task_skip_location'))
    await callback.answer()


@router.message(CreateTaskStates.waiting_address)
async def task_address(message: Message, state: FSMContext):
    await state.update_data(address=(message.text or '').strip()[:200])
    await state.set_state(CreateTaskStates.waiting_location)
    await message.answer('Теперь можешь отправить геолокацию для кнопки маршрута или нажми пропустить.', reply_markup=skip_kb('task_skip_location'))


@router.callback_query(F.data == 'task_skip_location')
async def task_skip_location(callback: CallbackQuery, state: FSMContext):
    await state.update_data(latitude=None, longitude=None)
    await state.set_state(CreateTaskStates.waiting_photos)
    await callback.message.answer(f'Теперь можешь прикрепить до {MAX_PHOTOS_PER_TASK} фото. Отправляй по одному или нажми «Готово».', reply_markup=done_photos_kb())
    await callback.answer()


@router.message(CreateTaskStates.waiting_location, F.location)
async def task_location(message: Message, state: FSMContext):
    await state.update_data(latitude=message.location.latitude, longitude=message.location.longitude)
    await state.set_state(CreateTaskStates.waiting_photos)
    await message.answer(f'Геолокация сохранена. Теперь можешь прикрепить до {MAX_PHOTOS_PER_TASK} фото. Отправляй по одному или нажми «Готово».', reply_markup=done_photos_kb())


@router.message(CreateTaskStates.waiting_location)
async def task_location_invalid(message: Message):
    await message.answer('Нужно отправить геолокацию или нажать «Пропустить».')


@router.message(CreateTaskStates.waiting_photos, F.photo)
async def task_add_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = list(data.get('photos', []))
    if len(photos) >= MAX_PHOTOS_PER_TASK:
        await message.answer('Лимит фото уже достигнут. Нажми «Готово».', reply_markup=done_photos_kb())
        return
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer(f'Фото добавлено ({len(photos)}/{MAX_PHOTOS_PER_TASK}). Можешь отправить ещё или нажать «Готово».', reply_markup=done_photos_kb())


@router.callback_query(F.data == 'task_photos_done')
async def task_photos_done(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CreateTaskStates.waiting_contact)
    await callback.message.answer('Оставь контакт для связи текстом: телефон, Telegram, WhatsApp. Или нажми пропустить.', reply_markup=skip_kb('task_skip_contact'))
    await callback.answer()


@router.message(CreateTaskStates.waiting_photos)
async def task_wait_photos(message: Message):
    await message.answer('Жду фото или кнопку «Готово».')


@router.callback_query(F.data == 'task_skip_contact')
async def task_skip_contact(callback: CallbackQuery, state: FSMContext):
    await _finish_task_creation(callback.message, state, '', callback.from_user.id)
    await callback.answer()


@router.message(CreateTaskStates.waiting_contact)
async def task_contact(message: Message, state: FSMContext):
    await _finish_task_creation(message, state, (message.text or '').strip()[:200])


async def _finish_task_creation(message: Message, state: FSMContext, contact_text: str, actor_tg_id: int | None = None):
    data = await state.get_data()
    actor_tg_id = actor_tg_id or message.from_user.id
    user = db.get_user_by_tg(actor_tg_id)
    task = db.create_task(
        customer_id=user['id'],
        city=data['city'],
        category=data['category'],
        title=data['title'],
        description=data['description'],
        budget=int(data['budget']),
        address=data.get('address'),
        latitude=data.get('latitude'),
        longitude=data.get('longitude'),
        contact_text=contact_text,
        photos=data.get('photos', []),
        status='pending',
    )
    await state.clear()
    await message.answer(f'✅ Заявка #{task["id"]} создана и отправлена на модерацию.', reply_markup=main_menu('customer', is_admin_tg(actor_tg_id)))
    await notify_admins(message.bot, f'🆕 Новая заявка на модерации\n\n{task_card(task, full=False)}')


# ===== Browse / open task =====

@router.message(F.text == '🔎 Искать заявки')
async def browse_tasks(message: Message, state: FSMContext):
    user = await ensure_registered_message(message)
    if not user:
        return
    if user['role'] != 'worker':
        await message.answer('Искать заявки может только исполнитель.')
        return
    await state.update_data(browse_city='all', browse_category='all', browse_page=0)
    await send_browse_list(message, state, source='browse')


@router.message(F.text == '⭐ Избранное')
async def favorites_menu(message: Message, state: FSMContext):
    user = await ensure_registered_message(message)
    if not user:
        return
    if user['role'] != 'worker':
        await message.answer('Избранное доступно только исполнителю.')
        return
    await state.update_data(favorites_page=0)
    await send_browse_list(message, state, source='favorites')


@router.callback_query(F.data == 'browse_city_menu')
async def browse_city_menu(callback: CallbackQuery):
    await callback.message.answer('Выбери город:', reply_markup=cities_kb('browse_city_set', include_all=True))
    await callback.answer()


@router.callback_query(F.data == 'browse_category_menu')
async def browse_category_menu(callback: CallbackQuery):
    await callback.message.answer('Выбери категорию:', reply_markup=categories_kb('browse_category_set', include_all=True))
    await callback.answer()


@router.callback_query(F.data.startswith('browse_city_set:'))
async def set_browse_city(callback: CallbackQuery, state: FSMContext):
    await state.update_data(browse_city=callback.data.split(':', 1)[1], browse_page=0)
    await send_browse_list(callback, state, source='browse')


@router.callback_query(F.data.startswith('browse_category_set:'))
async def set_browse_category(callback: CallbackQuery, state: FSMContext):
    await state.update_data(browse_category=callback.data.split(':', 1)[1], browse_page=0)
    await send_browse_list(callback, state, source='browse')


@router.callback_query(F.data.startswith('browse_page:'))
async def browse_page(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(':', 1)[1]
    data = await state.get_data()
    page = int(data.get('browse_page', 0) or 0)
    if action == 'next':
        page += 1
    elif action == 'prev' and page > 0:
        page -= 1
    await state.update_data(browse_page=page)
    await send_browse_list(callback, state, source='browse')


@router.callback_query(F.data.startswith('favorites_page:'))
async def favorites_page(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(':', 1)[1]
    data = await state.get_data()
    page = int(data.get('favorites_page', 0) or 0)
    if action == 'next':
        page += 1
    elif action == 'prev' and page > 0:
        page -= 1
    await state.update_data(favorites_page=page)
    await send_browse_list(callback, state, source='favorites')


@router.callback_query(F.data.startswith('open_task:'))
async def open_task(callback: CallbackQuery):
    user = await ensure_registered_callback(callback)
    if not user:
        return
    task_id = int(callback.data.split(':', 1)[1])
    await show_task_details(callback, task_id, viewer_user=user)
    await callback.answer()


@router.callback_query(F.data == 'back_to_list')
async def back_to_list(callback: CallbackQuery, state: FSMContext):
    user = await ensure_registered_callback(callback)
    if not user:
        return
    if user['role'] == 'worker':
        data = await state.get_data()
        source = 'favorites' if 'favorites_page' in data else 'browse'
        await send_browse_list(callback, state, source=source)
    else:
        await callback.message.answer('Возвращайся в меню.')
    await callback.answer()


# ===== Favorites / report / my tasks =====

@router.callback_query(F.data.startswith('favorite_toggle:'))
async def favorite_toggle(callback: CallbackQuery):
    user = await ensure_registered_callback(callback)
    if not user:
        return
    if user['role'] != 'worker':
        await callback.answer('Только для исполнителя', show_alert=True)
        return
    task_id = int(callback.data.split(':', 1)[1])
    if db.is_favorite(user['id'], task_id):
        db.remove_favorite(user['id'], task_id)
        await callback.answer('Удалено из избранного')
    else:
        db.add_favorite(user['id'], task_id)
        await callback.answer('Добавлено в избранное')
    await show_task_details(callback, task_id, viewer_user=user)


@router.callback_query(F.data.startswith('report_task:'))
async def start_report_task(callback: CallbackQuery, state: FSMContext):
    user = await ensure_registered_callback(callback)
    if not user:
        return
    task_id = int(callback.data.split(':', 1)[1])
    task = db.get_task(task_id)
    if not task:
        await callback.answer('Заявка не найдена', show_alert=True)
        return
    await state.clear()
    await state.update_data(report_task_id=task_id, report_target_user_id=task['customer_id'])
    await state.set_state(ReportStates.waiting_reason)
    await callback.message.answer('Опиши причину жалобы.')
    await callback.answer()


@router.message(ReportStates.waiting_reason)
async def save_report(message: Message, state: FSMContext):
    user = await ensure_registered_message(message)
    if not user:
        return
    reason = (message.text or '').strip()
    if len(reason) < 5:
        await message.answer('Напиши причину подробнее.')
        return
    if len(reason) > MAX_REPORT_REASON:
        reason = reason[:MAX_REPORT_REASON]
    data = await state.get_data()
    report = db.create_report(
        reporter_id=user['id'],
        task_id=data.get('report_task_id'),
        target_user_id=data.get('report_target_user_id'),
        reason=reason,
    )
    await state.clear()
    await message.answer('Жалоба отправлена администраторам ✅')
    await notify_admins(message.bot, f'🆘 Новая жалоба\n\nID: #{report["id"]}\nНа заявку: #{report.get("task_id") or "—"}\nПричина:\n{h(report.get("reason"))}')


@router.message(F.text == '📋 Мои заявки')
async def my_tasks(message: Message):
    await send_my_tasks_list(message)


@router.callback_query(F.data == 'my_tasks_back')
async def my_tasks_back(callback: CallbackQuery):
    await send_my_tasks_list(callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith('task_bump:'))
async def task_bump(callback: CallbackQuery):
    user = await ensure_registered_callback(callback)
    if not user:
        return
    task_id = int(callback.data.split(':', 1)[1])
    task = db.get_task(task_id)
    if not task or user['id'] != task['customer_id']:
        await callback.answer('Нет доступа', show_alert=True)
        return
    ok, msg = db.bump_task(task_id)
    await callback.message.answer(('✅ ' if ok else '⚠️ ') + msg)
    await callback.answer()


@router.callback_query(F.data.startswith('task_responses:'))
async def task_responses(callback: CallbackQuery):
    user = await ensure_registered_callback(callback)
    if not user:
        return
    task_id = int(callback.data.split(':', 1)[1])
    task = db.get_task(task_id)
    if not task:
        await callback.answer('Заявка не найдена', show_alert=True)
        return
    if user['id'] != task['customer_id'] and not is_admin_tg(callback.from_user.id):
        await callback.answer('Нет доступа', show_alert=True)
        return
    responses = db.get_task_responses(task_id)
    if not responses:
        await callback.message.answer('На эту заявку пока нет откликов.')
        await callback.answer()
        return
    for response in responses[:20]:
        markup = response_actions_kb(response['id'], task_id, response['status']) if user['id'] == task['customer_id'] else None
        await callback.message.answer(response_card(response), reply_markup=markup, parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data.startswith('accept_response:'))
async def accept_response(callback: CallbackQuery):
    user = await ensure_registered_callback(callback)
    if not user:
        return
    _, task_id_str, response_id_str = callback.data.split(':')
    task_id = int(task_id_str)
    response_id = int(response_id_str)
    task = db.get_task(task_id)
    response = db.get_response(response_id)
    if not task or not response or user['id'] != task['customer_id']:
        await callback.answer('Нет доступа', show_alert=True)
        return
    db.accept_response(task_id, response_id)
    await callback.message.answer('✅ Исполнитель выбран. Заявка переведена в статус «В работе».')
    await notify_user(callback.bot, response.get('worker_tg'), f'🎉 Вас выбрали исполнителем по заявке #{task_id}.')
    await callback.answer()


@router.callback_query(F.data.startswith('reject_response:'))
async def reject_response(callback: CallbackQuery):
    user = await ensure_registered_callback(callback)
    if not user:
        return
    _, task_id_str, response_id_str = callback.data.split(':')
    task_id = int(task_id_str)
    response_id = int(response_id_str)
    task = db.get_task(task_id)
    response = db.get_response(response_id)
    if not task or not response or user['id'] != task['customer_id']:
        await callback.answer('Нет доступа', show_alert=True)
        return
    db.update_response_status(response_id, 'rejected')
    await callback.message.answer('Отклик отклонён.')
    await notify_user(callback.bot, response.get('worker_tg'), f'По заявке #{task_id} ваш отклик отклонён.')
    await callback.answer()


@router.callback_query(F.data.startswith('task_close:'))
async def task_close(callback: CallbackQuery):
    user = await ensure_registered_callback(callback)
    if not user:
        return
    task_id = int(callback.data.split(':', 1)[1])
    task = db.get_task(task_id)
    if not task:
        await callback.answer('Заявка не найдена', show_alert=True)
        return
    if user['id'] != task['customer_id'] and not is_admin_tg(callback.from_user.id):
        await callback.answer('Нет доступа', show_alert=True)
        return
    db.update_task_status(task_id, 'closed')
    db.log_task_event(task_id, 'closed', user['id'], 'closed by customer')
    await callback.message.answer('✅ Заявка закрыта.')
    if task.get('selected_response_id') and user['id'] == task['customer_id']:
        response = db.get_response(task['selected_response_id'])
        if response and not db.get_review_for_task(task_id, response['worker_id']):
            await callback.message.answer('Оцени исполнителя:', reply_markup=rate_keyboard(task_id, response['worker_id'], response['id']))
        await notify_user(callback.bot, response.get('worker_tg'), f'Заявка #{task_id} закрыта заказчиком.')
    await callback.answer()


# ===== Responses by worker =====

@router.callback_query(F.data.startswith('respond:'))
async def start_response(callback: CallbackQuery, state: FSMContext):
    user = await ensure_registered_callback(callback)
    if not user:
        return
    if user['role'] != 'worker':
        await callback.answer('Откликаться может только исполнитель', show_alert=True)
        return
    task_id = int(callback.data.split(':', 1)[1])
    task = db.get_task(task_id)
    if not task or task['status'] != 'open':
        await callback.answer('Эта заявка уже недоступна', show_alert=True)
        return
    await state.clear()
    await state.update_data(task_id=task_id)
    await state.set_state(RespondTaskStates.waiting_message)
    await callback.message.answer('Напиши сообщение заказчику: что умеешь, когда готов выйти, почему выбрать тебя.')
    await callback.answer()


@router.message(RespondTaskStates.waiting_message)
async def response_message(message: Message, state: FSMContext):
    text = (message.text or '').strip()
    if len(text) < 5:
        await message.answer('Сообщение слишком короткое.')
        return
    await state.update_data(response_message=text[:MAX_TEXT_FIELD])
    await state.set_state(RespondTaskStates.waiting_price)
    await message.answer('Укажи свою цену или нажми пропустить.', reply_markup=skip_kb('response_skip_price'))


@router.callback_query(F.data == 'response_skip_price')
async def response_skip_price(callback: CallbackQuery, state: FSMContext):
    await state.update_data(response_price=None)
    await state.set_state(RespondTaskStates.waiting_contact)
    await callback.message.answer('Оставь контакт для связи или нажми пропустить.', reply_markup=skip_kb('response_skip_contact'))
    await callback.answer()


@router.message(RespondTaskStates.waiting_price)
async def response_price(message: Message, state: FSMContext):
    price = parse_int(message.text)
    if price is None:
        await message.answer('Укажи цену числом или нажми пропустить.')
        return
    await state.update_data(response_price=price)
    await state.set_state(RespondTaskStates.waiting_contact)
    await message.answer('Оставь контакт для связи или нажми пропустить.', reply_markup=skip_kb('response_skip_contact'))


@router.callback_query(F.data == 'response_skip_contact')
async def response_skip_contact(callback: CallbackQuery, state: FSMContext):
    await _finish_response(callback.message, state, '', callback.from_user.id)
    await callback.answer()


@router.message(RespondTaskStates.waiting_contact)
async def response_contact(message: Message, state: FSMContext):
    await _finish_response(message, state, (message.text or '').strip()[:200])


async def _finish_response(message: Message, state: FSMContext, contact_text: str, actor_tg_id: int | None = None):
    data = await state.get_data()
    actor_tg_id = actor_tg_id or message.from_user.id
    user = db.get_user_by_tg(actor_tg_id)
    response = db.create_response(
        task_id=int(data['task_id']),
        worker_id=user['id'],
        message=data['response_message'],
        offer_price=data.get('response_price'),
        contact_text=contact_text,
    )
    task = db.get_task(int(data['task_id']))
    await state.clear()
    await message.answer('✅ Отклик отправлен заказчику.', reply_markup=main_menu('worker', is_admin_tg(actor_tg_id)))
    await notify_user(message.bot, task.get('customer_tg'), f'💬 Новый отклик на заявку #{task["id"]}:\n\n{response_card(response, full=False)}')


@router.message(F.text == '📨 Мои отклики')
async def my_responses(message: Message):
    user = await ensure_registered_message(message)
    if not user:
        return
    if user['role'] != 'worker':
        await message.answer('Эта функция доступна только исполнителю.')
        return
    responses = db.get_worker_responses(user['id'])
    if not responses:
        await message.answer('У тебя пока нет откликов.')
        return
    text = '📨 <b>Мои отклики</b>\n\n'
    for response in responses[:20]:
        text += (
            f'#{response["id"]} · заявка #{response["task_id"]}\n'
            f'{h(response["task_title"])}\n'
            f'{h(response["task_city"])} · {int(response["task_budget"] or 0)} ₽\n'
            f'Статус отклика: {h(response["status"])} · Статус заявки: {h(response["task_status"])}\n\n'
        )
    await message.answer(text, parse_mode=ParseMode.HTML)


# ===== Reviews =====

@router.callback_query(F.data.startswith('rate:'))
async def rate_worker(callback: CallbackQuery, state: FSMContext):
    user = await ensure_registered_callback(callback)
    if not user:
        return
    _, task_id_str, worker_id_str, response_id_str, rating_str = callback.data.split(':')
    task_id = int(task_id_str)
    worker_id = int(worker_id_str)
    response_id = int(response_id_str)
    rating = int(rating_str)
    await state.update_data(review_task_id=task_id, review_worker_id=worker_id, review_response_id=response_id or None, review_rating=rating)
    await state.set_state(ReviewStates.waiting_text)
    await callback.message.answer('Напиши короткий отзыв или нажми пропустить.', reply_markup=skip_kb('review_skip_text'))
    await callback.answer()


@router.callback_query(F.data == 'review_skip_text')
async def review_skip_text(callback: CallbackQuery, state: FSMContext):
    await _save_review(callback.message, state, '', callback.from_user.id)
    await callback.answer()


@router.message(ReviewStates.waiting_text)
async def review_text(message: Message, state: FSMContext):
    await _save_review(message, state, (message.text or '').strip()[:MAX_TEXT_FIELD])


async def _save_review(message: Message, state: FSMContext, text: str, actor_tg_id: int | None = None):
    actor_tg_id = actor_tg_id or message.from_user.id
    user = db.get_user_by_tg(actor_tg_id)
    data = await state.get_data()
    db.add_review(
        task_id=int(data['review_task_id']),
        response_id=int(data['review_response_id']) if data.get('review_response_id') else None,
        worker_id=int(data['review_worker_id']),
        customer_id=user['id'],
        rating=int(data['review_rating']),
        text=text,
    )
    await state.clear()
    await message.answer('Спасибо, отзыв сохранён ✅')


@router.callback_query(F.data == 'ignore')
async def ignore_callback(callback: CallbackQuery):
    await callback.answer()
