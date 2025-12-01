import logging
import random
import json
import time
import signal
import sys
from typing import Dict, Any, List
from datetime import datetime
from uuid import uuid4
import os
import requests
import threading
from concurrent.futures import ThreadPoolExecutor

# --- Настройка логирования ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO,
    handlers=[
        logging.FileHandler('santa_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Обработчик остановки бота ---
def signal_handler(sig, frame):
    print("\n\n🛑 Бот останавливается...")
    save_data()
    print("💾 Данные сохранены")
    print("👋 До свидания!")
    sys.exit(0)

# signal.signal(signal.SIGINT, signal_handler)

# --- Получаем токен из переменных окружения Scalingo ---
BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    print("❌ ОШИБКА: Токен бота не найден!")
    print("Добавьте переменную окружения BOT_TOKEN в Scalingo:")
    print("1. Зайдите в Dashboard Scalingo")
    print("2. Выберите ваше приложение")
    print("3. Environment > Add variable")
    print("4. Name: BOT_TOKEN")
    print("5. Value: ваш_токен_от_BotFather")
    print("\nПолучить токен можно у @BotFather в Telegram")
    sys.exit(1)

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Проверяем валидность токена
def check_bot_token():
    try:
        response = requests.get(f"{BASE_URL}/getMe", timeout=10)
        if response.status_code == 200:
            bot_data = response.json()
            if bot_data.get('ok'):
                logger.info(f"✅ Бот @{bot_data['result']['username']} успешно подключен!")
                return True
            else:
                logger.error("❌ Неверный токен бота")
                return False
        else:
            logger.error(f"❌ Ошибка подключения: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"❌ Ошибка проверки токена: {e}")
        return False

# Константы
BUDGET_OPTIONS = [500, 750, 1000, 1250, 1500, 2500]

# --- Классы данных ---
class Participant:
    def __init__(self, user_id: int, full_name: str, username: str = ""):
        self.user_id = user_id
        self.full_name = full_name
        self.username = username
        self.wishlist = ""
        self.anti_wishlist = ""
        self.target_id = None

    def to_dict(self):
        return {
            'user_id': self.user_id,
            'full_name': self.full_name,
            'username': self.username,
            'wishlist': self.wishlist,
            'anti_wishlist': self.anti_wishlist,
            'target_id': self.target_id
        }

    @classmethod
    def from_dict(cls, data):
        participant = cls(data['user_id'], data['full_name'], data.get('username', ''))
        participant.wishlist = data['wishlist']
        participant.anti_wishlist = data['anti_wishlist']
        participant.target_id = data['target_id']
        return participant

class Room:
    def __init__(self, room_id: str, title: str, admin_id: int, budget: int, gift_date: str):
        self.room_id = room_id
        self.title = title
        self.admin_id = admin_id
        self.budget = budget
        self.gift_date = gift_date
        self.participants = {}
        self.raffle_done = False
        self.is_active = True
        self.join_code = str(uuid4())[:6].upper()

    def get_invite_link(self, bot_username: str) -> str:
        return f"https://t.me/{bot_username}?start={self.room_id}"

    def to_dict(self):
        return {
            'room_id': self.room_id,
            'title': self.title,
            'admin_id': self.admin_id,
            'budget': self.budget,
            'gift_date': self.gift_date,
            'raffle_done': self.raffle_done,
            'is_active': self.is_active,
            'join_code': self.join_code,
            'participants': {str(k): v.to_dict() for k, v in self.participants.items()}
        }

    @classmethod
    def from_dict(cls, data):
        room = cls(
            data['room_id'],
            data['title'],
            data['admin_id'],
            data['budget'],
            data['gift_date']
        )
        room.raffle_done = data['raffle_done']
        room.is_active = data['is_active']
        room.join_code = data.get('join_code', str(uuid4())[:6].upper())
        room.participants = {
            int(k): Participant.from_dict(v) for k, v in data['participants'].items()
        }
        return room

# --- Глобальные хранилища ---
rooms = {}
user_rooms = {}  # user_id -> room_id (активная комната)
user_states = {}
join_codes = {}
processing_lock = threading.Lock()
last_updates = {}

executor = ThreadPoolExecutor(max_workers=20)

def save_data():
    with processing_lock:
        data = {
            'rooms': {k: v.to_dict() for k, v in rooms.items()},
            'user_rooms': user_rooms
        }
        try:
            with open('santa_data.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения: {e}")

def load_data():
    global rooms, user_rooms, join_codes
    try:
        if os.path.exists('santa_data.json'):
            with open('santa_data.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                rooms = {k: Room.from_dict(v) for k, v in data['rooms'].items()}
                user_rooms = {int(k): v for k, v in data['user_rooms'].items()}
                
                for room_id, room in rooms.items():
                    join_codes[room.join_code] = room_id
                
            logger.info("✅ Данные успешно загружены")
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки: {e}")

# --- Функции для работы с Telegram API ---
def send_message(chat_id, text, reply_markup=None, parse_mode=None, retry_count=3):
    url = f"{BASE_URL}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup
    if parse_mode:
        payload['parse_mode'] = parse_mode
    
    for attempt in range(retry_count):
        try:
            response = requests.post(url, json=payload, timeout=15)
            if response.status_code == 200:
                return True
            elif response.status_code == 429:
                retry_after = response.json().get('parameters', {}).get('retry_after', 5)
                logger.warning(f"⚠️ Rate limit, waiting {retry_after} seconds")
                time.sleep(retry_after)
                continue
            else:
                logger.error(f"❌ Ошибка отправки сообщения: {response.status_code}")
                if attempt < retry_count - 1:
                    time.sleep(1)
                    continue
        except Exception as e:
            logger.error(f"❌ Ошибка отправки сообщения: {e}")
            if attempt < retry_count - 1:
                time.sleep(1)
                continue
    
    return False

def edit_message_text(chat_id, message_id, text, reply_markup=None):
    url = f"{BASE_URL}/editMessageText"
    payload = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"❌ Ошибка редактирования сообщения: {e}")
        return False

def answer_callback_query(callback_query_id, text=None):
    url = f"{BASE_URL}/answerCallbackQuery"
    payload = {
        'callback_query_id': callback_query_id
    }
    if text:
        payload['text'] = text
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"❌ Ошибка ответа на callback: {e}")
        return False

# --- Функция для форматирования ссылки на пользователя ---
def format_user_mention(user_id, full_name, username=None, show_name=True):
    """Форматирует упоминание пользователя с отображением имени"""
    if username:
        mention = f'@{username}'
    else:
        # Экранируем HTML-символы в имени
        safe_name = full_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        mention = f'<a href="tg://user?id={user_id}">{safe_name}</a>'
    
    # Добавляем имя пользователя рядом с упоминанием
    if show_name and full_name:
        safe_display_name = full_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return f"{mention} ({safe_display_name})"
    else:
        return mention

# --- Клавиатуры ---
def create_main_keyboard(user_id):
    keyboard = [["🎯 Создать комнату", "🔍 Присоединиться"]]
    
    # Получаем все комнаты пользователя (где он является участником)
    user_room_ids = []
    for room_id, room in rooms.items():
        if user_id in room.participants:
            user_room_ids.append(room_id)
    
    if user_room_ids:
        # Если есть только одна комната - показываем её кнопку
        if len(user_room_ids) == 1:
            room_id = user_room_ids[0]
            if room_id in rooms:
                room = rooms[room_id]
                room_button = f"🏠 {room.title[:15]}..." if len(room.title) > 15 else f"🏠 {room.title}"
                keyboard.append([room_button])
        else:
            # Если несколько комнат - показываем кнопку смены комнаты
            keyboard.append(["🔄 Сменить комнату"])
        
        # Добавляем остальные кнопки для текущей активной комнаты
        current_room_id = user_rooms.get(user_id)
        if current_room_id and current_room_id in rooms:
            room = rooms[current_room_id]
            
            # Кнопки для организатора
            if room.admin_id == user_id:
                keyboard.append(["🎲 Жеребьевка", "👥 Участники"])
                keyboard.append(["📨 Пригласить", "⚙️ Управление"])
            
            # Общие кнопки для всех участников
            keyboard.append(["👤 Мой профиль"])
            if room.raffle_done:
                keyboard.append(["🎁 Мой получатель"])
            
            keyboard.append(["🚪 Выйти"])
    
    return {
        'keyboard': keyboard,
        'resize_keyboard': True
    }

def create_back_keyboard():
    return {
        'keyboard': [["🔙 Назад"]],
        'resize_keyboard': True
    }

def create_budget_keyboard():
    keyboard = []
    for i in range(0, len(BUDGET_OPTIONS), 2):
        row = []
        for budget in BUDGET_OPTIONS[i:i+2]:
            row.append({
                'text': f"{budget} руб.",
                'callback_data': f"budget_{budget}"
            })
        keyboard.append(row)
    return {'inline_keyboard': keyboard}

def create_confirmation_keyboard():
    return {
        'inline_keyboard': [
            [{'text': "✅ Создать", 'callback_data': "create_confirm"}],
            [{'text': "🔙 Назад", 'callback_data': "create_back"}]
        ]
    }

def create_join_decision_keyboard():
    return {
        'inline_keyboard': [
            [{'text': "✅ Присоединиться", 'callback_data': "join_yes"}],
            [{'text': "❌ Отказаться", 'callback_data': "join_no"}]
        ]
    }

def create_profile_confirmation_keyboard():
    return {
        'inline_keyboard': [
            [{'text': "✅ Подтвердить", 'callback_data': "profile_confirm"}],
            [{'text': "✏️ Редактировать", 'callback_data': "profile_edit"}],
            [{'text': "🔙 Назад", 'callback_data': "profile_back"}]
        ]
    }

def create_edit_profile_keyboard():
    return {
        'inline_keyboard': [
            [{'text': "👤 ФИО", 'callback_data': "edit_name"}],
            [{'text': "🎁 Пожелания", 'callback_data': "edit_wish"}],
            [{'text': "🚫 Анти-пожелания", 'callback_data': "edit_anti_wish"}],
            [{'text': "🔙 Назад", 'callback_data': "edit_back"}]
        ]
    }

def create_room_management_keyboard():
    return {
        'inline_keyboard': [
            [{'text': "🗑️ Удалить комнату", 'callback_data': "delete_room"}],
            [{'text': "📊 Статистика", 'callback_data': "room_stats"}],
            [{'text': "🔙 Назад", 'callback_data': "manage_back"}]
        ]
    }

def create_room_switch_keyboard(user_id):
    keyboard = []
    
    # Получаем все комнаты пользователя
    user_room_ids = []
    for room_id, room in rooms.items():
        if user_id in room.participants:
            user_room_ids.append(room_id)
    
    for room_id in user_room_ids:
        if room_id in rooms:
            room = rooms[room_id]
            role = "👑" if room.admin_id == user_id else "👤"
            room_name = room.title[:20] + "..." if len(room.title) > 20 else room.title
            keyboard.append([{
                'text': f"{role} {room_name}",
                'callback_data': f"switch_{room_id}"
            }])
    
    keyboard.append([{'text': "🔙 Назад", 'callback_data': "switch_back"}])
    return {'inline_keyboard': keyboard}

# --- Функция проверки даты ---
def is_date_passed(gift_date_str):
    """Проверяет, наступила ли уже указанная дата"""
    try:
        gift_date = datetime.strptime(gift_date_str, '%d.%m.%Y').date()
        current_date = datetime.now().date()
        return current_date >= gift_date
    except ValueError:
        return False

# --- Вспомогательные функции ---
def get_user_rooms(user_id):
    """Получает все комнаты пользователя"""
    user_room_ids = []
    for room_id, room in rooms.items():
        if user_id in room.participants:
            user_room_ids.append(room_id)
    return user_room_ids

def set_active_room(user_id, room_id):
    """Устанавливает активную комнату для пользователя"""
    user_rooms[user_id] = room_id
    save_data()

def update_participant_info(user_id, full_name, username):
    """Обновляет информацию о пользователе во всех комнатах"""
    for room in rooms.values():
        if user_id in room.participants:
            participant = room.participants[user_id]
            participant.full_name = full_name
            if username:
                participant.username = username

# --- Обработчики сообщений ---
def handle_start(message, user_id):
    # Получаем информацию о пользователе
    from_user = message.get('from', {})
    username = from_user.get('username', '')
    first_name = from_user.get('first_name', '')
    last_name = from_user.get('last_name', '')
    
    # Формируем полное имя
    full_name = first_name
    if last_name:
        full_name += f" {last_name}"
    if not full_name:
        full_name = f"User_{user_id}"
    
    # Обновляем информацию о пользователе
    update_participant_info(user_id, full_name, username)
    
    text_parts = message.get('text', '').split()
    
    if len(text_parts) > 1:
        room_id = text_parts[1]
        if room_id in rooms and rooms[room_id].is_active:
            # ПРОВЕРКА ДАТЫ ПЕРЕД ПРИСОЕДИНЕНИЕМ
            room = rooms[room_id]
            if is_date_passed(room.gift_date):
                send_message(
                    user_id,
                    f"❌ К сожалению, дата обмена подарками ({room.gift_date}) уже наступила.\n"
                    f"Присоединиться к этой комнате больше нельзя."
                )
                return
            
            user_states[user_id] = {
                'state': 'joining_room',
                'room_id': room_id
            }
            
            keyboard = create_join_decision_keyboard()
            
            send_message(
                user_id,
                f"🎅 Вас пригласили в Тайного Санту!\n\n"
                f"Комната: {room.title}\n"
                f"Бюджет: {room.budget} руб.\n"
                f"Дата: {room.gift_date}\n\n"
                f"Хотите присоединиться?",
                reply_markup=keyboard
            )
            return
    
    user_states[user_id] = {'state': 'main_menu'}
    send_message(
        user_id,
        f"🎅 Привет! Я бот для организации Тайного Санты!\n"
        f"Создайте комнату или присоединитесь к существующей.",
        reply_markup=create_main_keyboard(user_id)
    )

def handle_text_message(message, user_id):
    # Обновляем информацию о пользователе
    from_user = message.get('from', {})
    username = from_user.get('username', '')
    first_name = from_user.get('first_name', '')
    last_name = from_user.get('last_name', '')
    
    full_name = first_name
    if last_name:
        full_name += f" {last_name}"
    if not full_name:
        full_name = f"User_{user_id}"
    
    update_participant_info(user_id, full_name, username)
    
    text = message.get('text', '')
    state_data = user_states.get(user_id, {})
    state = state_data.get('state', 'main_menu')
    
    if text in ["🎯 Создать комнату", "🔍 Присоединиться", "🎲 Жеребьевка", "👥 Участники", 
                "📨 Пригласить", "⚙️ Управление", "👤 Мой профиль", "🎁 Мой получатель", 
                "🔄 Сменить комнату", "🚪 Выйти"]:
        logger.info(f"👤 {user_id}: {text}")
    
    if state == 'main_menu':
        if text == "🎯 Создать комнату":
            user_states[user_id] = {'state': 'creating_room', 'step': 'title'}
            send_message(user_id, "🏠 Как назовем комнату?", reply_markup=create_back_keyboard())
        
        elif text == "🔍 Присоединиться":
            user_states[user_id] = {'state': 'joining_by_code', 'step': 'enter_code'}
            send_message(user_id, "🔢 Введите код комнаты для присоединения:", reply_markup=create_back_keyboard())
        
        elif text == "🔙 Назад":
            send_message(user_id, "Главное меню:", reply_markup=create_main_keyboard(user_id))
        
        elif text.startswith("🏠 "):
            if user_id in user_rooms:
                room_id = user_rooms[user_id]
                room = rooms[room_id]
                show_room_info(user_id, room)
            else:
                send_message(user_id, "❌ Вы не состоите в комнате")
        
        elif text == "🔄 Сменить комнату":
            handle_switch_room(user_id)
        
        elif text == "🎲 Жеребьевка":
            handle_raffle(user_id)
        
        elif text == "👥 Участники":
            handle_show_participants(user_id)
        
        elif text == "📨 Пригласить":
            handle_invite_players(user_id)
        
        elif text == "⚙️ Управление":
            handle_room_management(user_id)
        
        elif text == "👤 Мой профиль":
            handle_show_my_profile(user_id)
        
        elif text == "🎁 Мой получатель":
            handle_show_recipient(user_id)
        
        elif text == "🚪 Выйти":
            handle_leave_room(user_id)
        else:
            send_message(user_id, "Используйте кнопки меню для навигации", reply_markup=create_main_keyboard(user_id))
    
    elif state == 'creating_room':
        if text == "🔙 Назад":
            user_states[user_id] = {'state': 'main_menu'}
            send_message(user_id, "✅ Создание комнаты отменено", reply_markup=create_main_keyboard(user_id))
            return
        
        step = state_data.get('step')
        
        if step == 'title':
            if text.strip():
                user_states[user_id] = {
                    'state': 'creating_room',
                    'step': 'budget',
                    'title': text.strip()
                }
                keyboard = create_budget_keyboard()
                send_message(user_id, "💰 Выберите бюджет подарков:", reply_markup=keyboard)
            else:
                send_message(user_id, "❌ Название не может быть пустым. Введите название комнаты:")
        
        elif step == 'date':
            try:
                datetime.strptime(text, '%d.%m.%Y')
                user_states[user_id]['date'] = text
                show_room_confirmation(user_id)
            except ValueError:
                send_message(user_id, "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ:")
    
    elif state == 'joining_by_code':
        if text == "🔙 Назад":
            user_states[user_id] = {'state': 'main_menu'}
            send_message(user_id, "✅ Присоединение отменено", reply_markup=create_main_keyboard(user_id))
            return
        
        step = state_data.get('step')
        
        if step == 'enter_code':
            code = text.strip().upper()
            if code in join_codes:
                room_id = join_codes[code]
                if room_id in rooms and rooms[room_id].is_active:
                    # ПРОВЕРКА ДАТЫ ПЕРЕД ПРИСОЕДИНЕНИЕМ
                    room = rooms[room_id]
                    if is_date_passed(room.gift_date):
                        send_message(
                            user_id,
                            f"❌ К сожалению, дата обмена подарками ({room.gift_date}) уже наступила.\n"
                            f"Присоединиться к этой комнате больше нельзя."
                        )
                        return
                    
                    user_states[user_id] = {
                        'state': 'joining_room',
                        'room_id': room_id
                    }
                    
                    keyboard = create_join_decision_keyboard()
                    
                    send_message(
                        user_id,
                        f"🎅 Найдена комната!\n\n"
                        f"Комната: {room.title}\n"
                        f"Бюджет: {room.budget} руб.\n"
                        f"Дата: {room.gift_date}\n\n"
                        f"Хотите присоединиться?",
                        reply_markup=keyboard
                    )
                else:
                    send_message(user_id, "❌ Комната не найдена или удалена")
            else:
                send_message(user_id, "❌ Неверный код комнаты. Попробуйте еще раз:")
    
    elif state == 'joining_profile':
        if text == "🔙 Назад":
            user_states[user_id] = {'state': 'main_menu'}
            send_message(user_id, "✅ Регистрация отменена", reply_markup=create_main_keyboard(user_id))
            return
        
        step = state_data.get('step')
        
        if step == 'name':
            if text.strip():
                user_states[user_id] = {
                    'state': 'joining_profile',
                    'step': 'wish',
                    'name': text.strip(),
                    'room_id': state_data['room_id']
                }
                send_message(user_id, "🎁 Что бы вы хотели получить в подарок?", reply_markup=create_back_keyboard())
            else:
                send_message(user_id, "❌ Имя не может быть пустым. Введите ваше ФИО:")
        
        elif step == 'wish':
            user_states[user_id] = {
                'state': 'joining_profile', 
                'step': 'anti_wish',
                'name': state_data['name'],
                'wish': text,
                'room_id': state_data['room_id']
            }
            send_message(user_id, "🚫 А что точно НЕ хотите получать?", reply_markup=create_back_keyboard())
        
        elif step == 'anti_wish':
            show_profile_confirmation(user_id, state_data['name'], state_data['wish'], text)
    
    elif state == 'editing_profile':
        if text == "🔙 Назад":
            user_states[user_id] = {'state': 'main_menu'}
            send_message(user_id, "✅ Редактирование отменено", reply_markup=create_main_keyboard(user_id))
            return
        
        field = state_data.get('editing_field')
        room_id = user_rooms.get(user_id)
        
        if room_id and room_id in rooms:
            room = rooms[room_id]
            participant = room.participants.get(user_id)
            
            if participant and not room.raffle_done:
                if field == 'name':
                    participant.full_name = text
                    send_message(user_id, "✅ ФИО обновлено!")
                elif field == 'wish':
                    participant.wishlist = text
                    send_message(user_id, "✅ Пожелания обновлены!")
                elif field == 'anti_wish':
                    participant.anti_wishlist = text
                    send_message(user_id, "✅ Анти-пожелания обновлены!")
                
                save_data()
                handle_show_my_profile(user_id)
            else:
                send_message(user_id, "❌ Редактирование недоступно после жеребьевки")
        else:
            send_message(user_id, "❌ Ошибка: комната не найдена")
        
        user_states[user_id] = {'state': 'main_menu'}

def handle_callback_query(callback_query, user_id):
    try:
        # Обновляем информацию о пользователе из callback
        from_user = callback_query.get('from', {})
        username = from_user.get('username', '')
        first_name = from_user.get('first_name', '')
        last_name = from_user.get('last_name', '')
        
        full_name = first_name
        if last_name:
            full_name += f" {last_name}"
        if not full_name:
            full_name = f"User_{user_id}"
        
        update_participant_info(user_id, full_name, username)
        
        data = callback_query.get('data', '')
        message = callback_query.get('message', {})
        message_id = message.get('message_id')
        chat_id = message.get('chat', {}).get('id')
        
        # Всегда отвечаем на callback query
        answer_callback_query(callback_query['id'])
        
        logger.info(f"👤 {user_id}: callback {data}")
        
        if data.startswith('budget_'):
            try:
                budget = int(data.split('_')[1])
                # Получаем текущее состояние
                state_data = user_states.get(user_id, {})
                
                # Сохраняем бюджет и переходим к следующему шагу
                user_states[user_id] = {
                    'state': 'creating_room',
                    'step': 'date',
                    'title': state_data.get('title', ''),
                    'budget': budget
                }
                
                # Редактируем сообщение с запросом даты
                success = edit_message_text(
                    chat_id, 
                    message_id, 
                    f"💰 Бюджет: {budget} руб.\n\n📅 Введите дату обмена подарками (ДД.ММ.ГГГГ):",
                    reply_markup=create_back_keyboard()
                )
                
                if not success:
                    # Если не удалось отредактировать, отправляем новое сообщение
                    send_message(
                        user_id,
                        f"💰 Бюджет: {budget} руб.\n\n📅 Введите дату обмена подарками (ДД.ММ.ГГГГ):",
                        reply_markup=create_back_keyboard()
                    )
                    
            except Exception as e:
                logger.error(f"❌ Ошибка обработки бюджета: {e}")
                send_message(user_id, "❌ Ошибка выбора бюджета. Попробуйте еще раз.")
        
        elif data in ['create_confirm', 'create_back']:
            if data == 'create_back':
                user_states[user_id] = {'state': 'creating_room', 'step': 'title'}
                edit_message_text(chat_id, message_id, "🔄 Начинаем заново...\n🏠 Как назовем комнату?", reply_markup=create_back_keyboard())
            else:
                create_room_final(user_id, chat_id, message_id)
        
        elif data in ['join_yes', 'join_no', 'profile_back']:
            if data in ['join_no', 'profile_back']:
                user_states[user_id] = {'state': 'main_menu'}
                edit_message_text(chat_id, message_id, "✅ Присоединение отменено.")
                send_message(user_id, "Главное меню:", reply_markup=create_main_keyboard(user_id))
            else:
                room_id = user_states[user_id].get('room_id')
                if room_id and room_id in rooms:
                    # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА ДАТЫ ПЕРЕД РЕГИСТРАЦИЕЙ
                    room = rooms[room_id]
                    if is_date_passed(room.gift_date):
                        edit_message_text(
                            chat_id, 
                            message_id, 
                            f"❌ К сожалению, дата обмена подарками ({room.gift_date}) уже наступила.\n"
                            f"Присоединиться к этой комнате больше нельзя."
                        )
                        user_states[user_id] = {'state': 'main_menu'}
                        return
                    
                    if user_id in rooms[room_id].participants:
                        edit_message_text(chat_id, message_id, "❌ Вы уже участник этой комнаты!")
                        user_states[user_id] = {'state': 'main_menu'}
                        return
                    
                    user_states[user_id] = {
                        'state': 'joining_profile',
                        'step': 'name',
                        'room_id': room_id
                    }
                    edit_message_text(chat_id, message_id, "👤 Регистрация:\nВведите ваше ФИО:", reply_markup=create_back_keyboard())
                else:
                    edit_message_text(chat_id, message_id, "❌ Ошибка: комната не найдена")
                    user_states[user_id] = {'state': 'main_menu'}
        
        elif data in ['profile_confirm', 'profile_edit']:
            if data == 'profile_confirm':
                join_room_final(user_id, chat_id, message_id)
            else:
                keyboard = create_edit_profile_keyboard()
                edit_message_text(chat_id, message_id, "✏️ Что вы хотите изменить?", reply_markup=keyboard)
        
        elif data.startswith('edit_'):
            if data == 'edit_back':
                state_data = user_states.get(user_id, {})
                show_profile_confirmation(user_id, state_data.get('name'), state_data.get('wish'), state_data.get('anti_wish'))
            else:
                user_states[user_id] = {
                    'state': 'editing_profile',
                    'editing_field': data
                }
                field_names = {
                    'edit_name': 'ФИО',
                    'edit_wish': 'пожелания',
                    'edit_anti_wish': 'анти-пожелания'
                }
                edit_message_text(chat_id, message_id, f"Введите новые {field_names[data]}:", reply_markup=create_back_keyboard())
        
        elif data.startswith('switch_'):
            room_id = data.split('_')[1]
            if room_id in rooms:
                set_active_room(user_id, room_id)
                room = rooms[room_id]
                edit_message_text(chat_id, message_id, f"✅ Переключились на комнату: {room.title}")
                send_message(user_id, "Главное меню:", reply_markup=create_main_keyboard(user_id))
            else:
                edit_message_text(chat_id, message_id, "❌ Комната не найдена")
        
        elif data == 'switch_back':
            edit_message_text(chat_id, message_id, "Главное меню:")
            send_message(user_id, "Выберите действие:", reply_markup=create_main_keyboard(user_id))
        
        elif data == 'delete_room':
            handle_delete_room(user_id, chat_id, message_id)
        
        elif data in ['manage_back', 'room_stats']:
            if data == 'manage_back':
                edit_message_text(chat_id, message_id, "Главное меню:")
                send_message(user_id, "Выберите действие:", reply_markup=create_main_keyboard(user_id))
            else:
                handle_room_stats(user_id, chat_id, message_id)
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки callback: {e}")
        # Пытаемся отправить сообщение об ошибке пользователю
        try:
            send_message(user_id, "❌ Произошла ошибка. Попробуйте еще раз.")
        except:
            pass

def show_room_confirmation(user_id):
    state_data = user_states.get(user_id, {})
    title = state_data.get('title', 'Не указано')
    budget = state_data.get('budget', 0)
    date = state_data.get('date', 'Не указана')
    
    keyboard = create_confirmation_keyboard()
    
    send_message(
        user_id,
        f"🔍 Проверьте настройки комнаты:\n\n"
        f"🏠 Название: {title}\n"
        f"💰 Бюджет: {budget} руб.\n"
        f"📅 Дата: {date}\n\n"
        f"Всё верно?",
        reply_markup=keyboard
    )

def create_room_final(user_id, chat_id, message_id):
    state_data = user_states.get(user_id, {})
    
    title = state_data.get('title')
    budget = state_data.get('budget')
    date = state_data.get('date')
    
    if not all([title, budget, date]):
        edit_message_text(chat_id, message_id, "❌ Ошибка: не все данные заполнены. Начните заново.")
        user_states[user_id] = {'state': 'main_menu'}
        return
    
    room_id = str(uuid4())[:8]
    room = Room(room_id, title, user_id, budget, date)
    
    rooms[room_id] = room
    set_active_room(user_id, room_id)  # Устанавливаем активную комнату
    join_codes[room.join_code] = room_id
    
    user_states[user_id] = {
        'state': 'joining_profile',
        'step': 'name', 
        'room_id': room_id,
        'is_admin': True
    }
    
    save_data()
    
    edit_message_text(
        chat_id,
        message_id,
        f"🎉 Комната создана!\n\n"
        f"🏠 {title}\n"
        f"💰 Бюджет: {budget} руб.\n"
        f"📅 Дата: {date}\n\n"
        f"Теперь заполните свой профиль:"
    )
    
    send_message(user_id, "👤 Введите ваше ФИО:", reply_markup=create_back_keyboard())

def show_profile_confirmation(user_id, name, wish, anti_wish):
    user_states[user_id] = {
        'state': 'joining_profile_confirm',
        'name': name,
        'wish': wish,
        'anti_wish': anti_wish,
        'room_id': user_states[user_id].get('room_id')
    }
    
    keyboard = create_profile_confirmation_keyboard()
    
    send_message(
        user_id,
        f"👤 Ваш профиль:\n\n"
        f"ФИО: {name}\n"
        f"🎁 Хочу: {wish}\n"
        f"🚫 Не хочу: {anti_wish}\n\n"
        f"Всё верно?",
        reply_markup=keyboard
    )

def join_room_final(user_id, chat_id, message_id):
    state_data = user_states.get(user_id, {})
    room_id = state_data.get('room_id')
    is_admin = state_data.get('is_admin', False)
    
    if not room_id or room_id not in rooms:
        edit_message_text(chat_id, message_id, "❌ Ошибка: комната не найдена")
        user_states[user_id] = {'state': 'main_menu'}
        return
    
    room = rooms[room_id]
    
    name = state_data.get('name')
    wish = state_data.get('wish', '')
    anti_wish = state_data.get('anti_wish', '')
    
    if not name:
        edit_message_text(chat_id, message_id, "❌ Ошибка: имя не указано")
        user_states[user_id] = {'state': 'main_menu'}
        return
    
    # Получаем информацию о пользователе для username
    from_user = user_states.get(user_id, {}).get('from_user', {})
    username = from_user.get('username', '')
    
    participant = Participant(user_id, name, username)
    participant.wishlist = wish
    participant.anti_wishlist = anti_wish
    
    room.participants[user_id] = participant
    if not is_admin:
        set_active_room(user_id, room_id)  # Устанавливаем активную комнату
    
    user_states[user_id] = {'state': 'main_menu'}
    save_data()
    
    if is_admin:
        edit_message_text(chat_id, message_id, f"✅ Ваш профиль сохранен! Комната готова к использованию.")
    else:
        edit_message_text(chat_id, message_id, f"🎄 Вы присоединились к комнате \"{room.title}\"! Ожидайте жеребьевки.")
    
    send_message(user_id, "Главное меню:", reply_markup=create_main_keyboard(user_id))

def handle_show_my_profile(user_id):
    if user_id not in user_rooms:
        send_message(user_id, "❌ Вы не в комнате.")
        return
    
    room_id = user_rooms[user_id]
    room = rooms[room_id]
    participant = room.participants.get(user_id)
    
    if not participant:
        send_message(user_id, "❌ Профиль не найден.")
        return
    
    profile_text = (
        f"👤 Ваш профиль:\n\n"
        f"ФИО: {participant.full_name}\n"
        f"🎁 Хочу: {participant.wishlist}\n"
        f"🚫 Не хочу: {participant.anti_wishlist}\n\n"
        f"Комната: {room.title}"
    )
    
    if not room.raffle_done:
        keyboard = create_edit_profile_keyboard()
        send_message(user_id, profile_text, reply_markup=keyboard)
    else:
        send_message(user_id, profile_text + "\n\n❌ Редактирование недоступно после жеребьевки")

def handle_room_management(user_id):
    if user_id not in user_rooms:
        send_message(user_id, "❌ Вы не в комнате.")
        return
    
    room_id = user_rooms[user_id]
    room = rooms[room_id]
    
    if room.admin_id != user_id:
        send_message(user_id, "❌ Только организатор может управлять комнатой.")
        return
    
    keyboard = create_room_management_keyboard()
    
    send_message(
        user_id,
        f"⚙️ Управление комнатой: {room.title}\n\n"
        f"Участников: {len(room.participants)}\n"
        f"Статус жеребьевки: {'✅ Проведена' if room.raffle_done else '❌ Не проведена'}",
        reply_markup=keyboard
    )

def handle_delete_room(user_id, chat_id, message_id):
    if user_id not in user_rooms:
        edit_message_text(chat_id, message_id, "❌ Вы не в комнате.")
        return
    
    room_id = user_rooms[user_id]
    room = rooms[room_id]
    
    if room.admin_id != user_id:
        edit_message_text(chat_id, message_id, "❌ Только организатор может удалить комнату.")
        return
    
    for participant_id in room.participants:
        if participant_id != user_id:
            send_message(participant_id, f"❌ Комната \"{room.title}\" была удалена организатором.")
    
    for participant_id in room.participants:
        if participant_id in user_rooms and user_rooms[participant_id] == room_id:
            del user_rooms[participant_id]
    
    if room.join_code in join_codes:
        del join_codes[room.join_code]
    
    del rooms[room_id]
    save_data()
    
    edit_message_text(chat_id, message_id, "🗑️ Комната удалена.")
    send_message(user_id, "Главное меню:", reply_markup=create_main_keyboard(user_id))

def handle_room_stats(user_id, chat_id, message_id):
    if user_id not in user_rooms:
        edit_message_text(chat_id, message_id, "❌ Вы не в комнате.")
        return
    
    room_id = user_rooms[user_id]
    room = rooms[room_id]
    
    admin = room.participants.get(room.admin_id)
    admin_mention = format_user_mention(room.admin_id, admin.full_name if admin else "Неизвестно", admin.username if admin else "")
    
    stats_text = (
        f"📊 Статистика комнаты: {room.title}\n\n"
        f"👥 Участников: {len(room.participants)}\n"
        f"💰 Бюджет: {room.budget} руб.\n"
        f"📅 Дата: {room.gift_date}\n"
        f"🎲 Жеребьевка: {'✅ Проведена' if room.raffle_done else '❌ Не проведена'}\n"
        f"🔑 Код для вступления: {room.join_code}\n\n"
        f"Организатор:\n{admin_mention}"
    )
    
    edit_message_text(chat_id, message_id, stats_text, parse_mode='HTML')

def handle_switch_room(user_id):
    user_room_ids = get_user_rooms(user_id)
    
    if len(user_room_ids) <= 1:
        send_message(user_id, "❌ Вы состоите только в одной комнате.")
        return
    
    keyboard = create_room_switch_keyboard(user_id)
    send_message(user_id, "🔄 Выберите комнату для переключения:", reply_markup=keyboard)

def show_room_info(user_id, room):
    role = "👑 Организатор" if room.admin_id == user_id else "👤 Участник"
    
    admin = room.participants.get(room.admin_id)
    admin_mention = format_user_mention(room.admin_id, admin.full_name if admin else "Неизвестно", admin.username if admin else "")
    
    info_text = (
        f"🏠 Информация о комнате:\n\n"
        f"Название: {room.title}\n"
        f"Роль: {role}\n"
        f"💰 Бюджет: {room.budget} руб.\n"
        f"📅 Дата: {room.gift_date}\n"
        f"👥 Участников: {len(room.participants)}\n"
        f"🎲 Жеребьевка: {'✅ Проведена' if room.raffle_done else '❌ Не проведена'}\n"
        f"🔑 Код для друзей: {room.join_code}\n\n"
        f"Организатор:\n{admin_mention}"
    )
    
    send_message(user_id, info_text, parse_mode='HTML')

def handle_raffle(user_id):
    if user_id not in user_rooms:
        send_message(user_id, "❌ Вы не в комнате.")
        return
    
    room_id = user_rooms[user_id]
    room = rooms[room_id]
    
    if room.admin_id != user_id:
        send_message(user_id, "❌ Только организатор может проводить жеребьевку.")
        return
    
    if room.raffle_done:
        send_message(user_id, "❌ Жеребьевка уже проведена.")
        return
    
    if len(room.participants) < 2:
        send_message(user_id, f"❌ Нужно минимум 2 участника. Сейчас: {len(room.participants)}")
        return
    
    participant_ids = list(room.participants.keys())
    targets = participant_ids.copy()
    
    max_attempts = 100
    for attempt in range(max_attempts):
        random.shuffle(targets)
        valid = True
        for i, pid in enumerate(participant_ids):
            if pid == targets[i]:
                valid = False
                break
        if valid:
            break
    else:
        targets = participant_ids[1:] + [participant_ids[0]]
    
    for i, pid in enumerate(participant_ids):
        room.participants[pid].target_id = targets[i]
    
    room.raffle_done = True
    save_data()
    
    print("\n" + "="*50)
    print("🎲 ЖЕРЕБЬЕВКА ПРОВЕДЕНА!")
    print(f"Комната: {room.title}")
    print(f"Участников: {len(participant_ids)}")
    print("-" * 50)
    
    for i, pid in enumerate(participant_ids):
        giver = room.participants[pid]
        receiver = room.participants[targets[i]]
        print(f"{giver.full_name} -> {receiver.full_name}")
    
    print("="*50 + "\n")
    
    def send_raffle_result(pid):
        participant = room.participants[pid]
        target = room.participants[participant.target_id]
        
        target_mention = format_user_mention(target.user_id, target.full_name, target.username)
        
        message_text = (
            f"🎉 Жеребьевка проведена!\n\n"
            f"🎁 Вы дарите подарок: {target_mention}\n\n"
            f"Пожелания:\n{target.wishlist or 'Не указано'}\n\n"
            f"Не дарить:\n{target.anti_wishlist or 'Не указано'}\n\n"
            f"💰 Бюджет: {room.budget} руб.\n"
            f"Удачи в выборе подарка! 🎄"
        )
        
        return send_message(pid, message_text, parse_mode='HTML')
    
    futures = [executor.submit(send_raffle_result, pid) for pid in participant_ids]
    success_count = sum(1 for future in futures if future.result())
    
    send_message(user_id, f"✅ Жеребьевка проведена! Уведомления отправлены {success_count}/{len(participant_ids)} участникам.")

def handle_show_participants(user_id):
    if user_id not in user_rooms:
        send_message(user_id, "❌ Вы не в комнате.")
        return
    
    room_id = user_rooms[user_id]
    room = rooms[room_id]
    
    participants_list = []
    for participant in room.participants.values():
        role = "👑" if participant.user_id == room.admin_id else "👤"
        user_mention = format_user_mention(participant.user_id, participant.full_name, participant.username)
        participants_list.append(f"{role} {user_mention}")
    
    participants_text = "\n".join(participants_list)
    
    send_message(
        user_id,
        f"👥 Участники комнаты \"{room.title}\":\n\n{participants_text}\n\n"
        f"Всего: {len(room.participants)} человек",
        parse_mode='HTML'
    )

def handle_invite_players(user_id):
    if user_id not in user_rooms:
        send_message(user_id, "❌ Вы не в комнате.")
        return
    
    room_id = user_rooms[user_id]
    room = rooms[room_id]
    
    try:
        bot_info = requests.get(f"{BASE_URL}/getMe").json()
        bot_username = bot_info['result']['username']
    except:
        bot_username = "your_bot"
    
    invite_link = room.get_invite_link(bot_username)
    
    send_message(
        user_id,
        f"📨 Пригласите друзей в комнату \"{room.title}\":\n\n"
        f"🔗 Ссылка:\n<code>{invite_link}</code>\n\n"
        f"🔑 Или код:\n<code>{room.join_code}</code>\n\n"
        f"👥 Участников: {len(room.participants)}",
        parse_mode='HTML'
    )

def handle_show_recipient(user_id):
    if user_id not in user_rooms:
        send_message(user_id, "❌ Вы не в комнате.")
        return
    
    room_id = user_rooms[user_id]
    room = rooms[room_id]
    
    if not room.raffle_done:
        send_message(user_id, "❌ Жеребьевка еще не проводилась.")
        return
    
    participant = room.participants[user_id]
    if not participant.target_id:
        send_message(user_id, "❌ Информация о получателе не найдена.")
        return
    
    target = room.participants[participant.target_id]
    target_mention = format_user_mention(target.user_id, target.full_name, target.username)
    
    message_text = (
        f"🎁 Ваш получатель: {target_mention}\n\n"
        f"🎁 Пожелания:\n{target.wishlist or 'Не указано'}\n\n"
        f"🚫 Не дарить:\n{target.anti_wishlist or 'Не указано'}\n\n"
        f"💰 Бюджет: {room.budget} руб.\n"
        f"Удачи в выборе подарка! 🎄"
    )
    
    send_message(user_id, message_text, parse_mode='HTML')

def handle_leave_room(user_id):
    if user_id not in user_rooms:
        send_message(user_id, "❌ Вы не в комнате.")
        return
    
    room_id = user_rooms[user_id]
    room = rooms[room_id]
    
    if room.admin_id == user_id:
        send_message(user_id, "❌ Организатор не может выйти из комнаты. Используйте удаление комнаты в управлении.")
        return
    
    del room.participants[user_id]
    del user_rooms[user_id]
    
    user_room_count = get_user_rooms(user_id)
    if len(user_room_count) == 0:
        user_states[user_id] = {'state': 'main_menu'}
    
    save_data()
    send_message(user_id, "👋 Вы вышли из комнаты.")
    send_message(user_id, "Главное меню:", reply_markup=create_main_keyboard(user_id))

def process_update(update):
    try:
        update_id = update.get('update_id')
        
        if update_id in last_updates:
            return
        
        last_updates[update_id] = time.time()
        
        current_time = time.time()
        for uid, timestamp in list(last_updates.items()):
            if current_time - timestamp > 300:
                del last_updates[uid]
        
        if 'message' in update:
            message = update['message']
            user_id = message['from']['id']
            if 'text' in message and message['text'].startswith('/start'):
                handle_start(message, user_id)
            elif 'text' in message:
                handle_text_message(message, user_id)
        
        elif 'callback_query' in update:
            callback_query = update['callback_query']
            user_id = callback_query['from']['id']
            handle_callback_query(callback_query, user_id)
            
    except Exception as e:
        logger.error(f"❌ Ошибка обработки update: {e}")

def main():
    offset = 0
    while True:  # ← ВАЖНО: бесконечный цикл!
        try:
            # Получаем обновления от Telegram
            response = requests.get(f"{BASE_URL}/getUpdates", params={
                'offset': offset + 1,
                'timeout': 25,
                'limit': 50
            })
            # ... обработка ...
        except Exception as e:
            # ... обработка ошибок ...
            time.sleep(5)
    print("Загрузка данных...")
    load_data()
    
    print("Проверка токена бота...")
    if not check_bot_token():
        print("❌ ОШИБКА: Неверный токен бота!")
        print("Убедитесь, что:")
        print("1. Вы получили токен от @BotFather")
        print("2. Токен введен правильно")
        print("3. Бот активирован (нажата кнопка START в боте)")
        input("Нажмите Enter для выхода...")
        return
    
    print("✅ Бот успешно запущен!")
    print("📝 Логи сохраняются в santa_bot.log")
    print("🛑 Для остановки нажмите Ctrl+C")
    print("⚡ Режим: высокая производительность")
    print("⏳ Ожидание сообщений...")
    
    offset = 0
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while True:
        try:
            url = f"{BASE_URL}/getUpdates"
            params = {
                'offset': offset + 1,  # Исправление: offset + 1 чтобы избежать дублирования
                'timeout': 25,
                'limit': 50
            }
            response = requests.get(url, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    updates = data.get('result', [])
                    consecutive_errors = 0
                    
                    if updates:
                        for update in updates:
                            current_offset = update['update_id']
                            if current_offset > offset:
                                offset = current_offset
                            process_update(update)
                        
                        if len(updates) > 10:
                            logger.info(f"📨 Обработано {len(updates)} сообщений")
                    else:
                        time.sleep(0.1)
                else:
                    consecutive_errors += 1
                    logger.error(f"❌ Ошибка API: {data}")
            else:
                consecutive_errors += 1
                logger.error(f"❌ Ошибка HTTP: {response.status_code}")
                if consecutive_errors >= max_consecutive_errors:
                    logger.error("🔴 Слишком много ошибок подряд, перезапуск через 10 секунд...")
                    time.sleep(10)
                    consecutive_errors = 0
            
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"❌ Ошибка в главном цикле: {e}")
            time.sleep(5)

# В КОНЦЕ SantOS.py

def start_bot():
    """Функция для запуска бота"""
    print("Загрузка данных...")
    load_data()
    
    print("Проверка токена бота...")
    if not check_bot_token():
        print("❌ ОШИБКА: Неверный токен бота!")
        return
    
    print("✅ Бот успешно запущен!")
    print("📝 Логи сохраняются в santa_bot.log")
    print("⚡ Режим: высокая производительности")
    print("⏳ Ожидание сообщений...")
    
    offset = 0
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while True:
        try:
            url = f"{BASE_URL}/getUpdates"
            params = {
                'offset': offset + 1,
                'timeout': 25,
                'limit': 50
            }
            response = requests.get(url, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    updates = data.get('result', [])
                    consecutive_errors = 0
                    
                    if updates:
                        for update in updates:
                            current_offset = update['update_id']
                            if current_offset > offset:
                                offset = current_offset
                            process_update(update)
                        
                        if len(updates) > 10:
                            logger.info(f"📨 Обработано {len(updates)} сообщений")
                    else:
                        time.sleep(0.1)
                else:
                    consecutive_errors += 1
                    logger.error(f"❌ Ошибка API: {data}")
            else:
                consecutive_errors += 1
                logger.error(f"❌ Ошибка HTTP: {response.status_code}")
                if consecutive_errors >= max_consecutive_errors:
                    logger.error("🔴 Слишком много ошибок подряд, перезапуск через 10 секунд...")
                    time.sleep(10)
                    consecutive_errors = 0
            
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"❌ Ошибка в главном цикле: {e}")
            time.sleep(5)
            
if __name__ == "__main__":
    start_bot()
