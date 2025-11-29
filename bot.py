import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import json
import os
from typing import Dict, List
from datetime import datetime
import requests

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# База данных
Base = declarative_base()

class Button(Base):
    __tablename__ = 'buttons'
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    parent_id = Column(Integer, default=0)
    message_text = Column(Text)
    buttons = Column(Text)  # JSON список кнопок
    photo_url = Column(Text)  # URL фото для кнопки
    price = Column(Float, default=0.0)  # Цена для баланса

class Admin(Base):
    __tablename__ = 'admins'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    permissions = Column(String(255), default="limited")  # all, limited

class UserBalance(Base):
    __tablename__ = 'user_balances'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    balance = Column(Float, default=0.0)

class CompletedTasks(Base):
    __tablename__ = 'completed_tasks'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    button_id = Column(Integer)
    completed_at = Column(DateTime, default=datetime.now)
    screenshot_sent = Column(Boolean, default=False)
    approved = Column(Boolean, default=False)

class Referral(Base):
    __tablename__ = 'referrals'
    id = Column(Integer, primary_key=True)
    referrer_id = Column(Integer)  # Кто пригласил
    referred_id = Column(Integer)  # Кого пригласили
    created_at = Column(DateTime, default=datetime.now)
    first_task_completed = Column(Boolean, default=False)

class SubGramManager:
    def __init__(self, secret_key: str):
        self.secret_key = secret_key
        self.base_url = "https://api.subgram.org"
        self.headers = {
            "Auth": secret_key,
            "Content-Type": "application/json"
        }
    
    def add_bot(self, bot_token: str, max_sponsors: int = 4, time_purge: int = 180, 
                text_op: str = None, forbidden_themes: List[str] = None) -> Dict:
        """Добавляет бота в SubGram систему"""
        data = {
            "action": "add",
            "bot_token": bot_token,
            "max_sponsors": max_sponsors,
            "time_purge": time_purge,
            "get_links": 0,
            "show_quiz": 1,
            "gender_question": 1,
            "age_question": 0
        }
        
        if text_op:
            data["text_op"] = text_op
        
        if forbidden_themes:
            data["forbidden_themes"] = forbidden_themes
        
        response = requests.post(f"{self.base_url}/bots", headers=self.headers, json=data)
        return response.json()
    
    def update_bot(self, bot_id: int, is_on: int = None, **kwargs) -> Dict:
        """Обновляет настройки бота в SubGram"""
        data = {
            "action": "update",
            "bot_id": bot_id
        }
        
        if is_on is not None:
            data["is_on"] = is_on
        
        for key, value in kwargs.items():
            data[key] = value
        
        response = requests.post(f"{self.base_url}/bots", headers=self.headers, json=data)
        return response.json()
    
    def get_bot_info(self, bot_id: int) -> Dict:
        """Получает информацию о боте"""
        data = {
            "action": "info",
            "bot_id": bot_id
        }
        
        response = requests.post(f"{self.base_url}/bots", headers=self.headers, json=data)
        return response.json()
    
    def get_sponsors(self, api_key: str, user_id: int, chat_id: int, first_name: str = None, 
                    username: str = None, language_code: str = None, is_premium: bool = None,
                    action: str = "subscribe", gender: str = None, age: int = None,
                    max_sponsors: int = None, exclude_resource_ids: List[str] = None) -> Dict:
        """Получает список спонсоров для пользователя"""
        headers = self.headers.copy()
        headers["Auth"] = api_key
        
        data = {
            "user_id": user_id,
            "chat_id": chat_id,
            "action": action
        }
        
        # Добавляем опциональные параметры
        if first_name:
            data["first_name"] = first_name
        if username:
            data["username"] = username
        if language_code:
            data["language_code"] = language_code
        if is_premium is not None:
            data["is_premium"] = is_premium
        if gender:
            data["gender"] = gender
        if age:
            data["age"] = age
        if max_sponsors:
            data["max_sponsors"] = max_sponsors
        if exclude_resource_ids:
            data["exclude_resource_ids"] = exclude_resource_ids
        
        response = requests.post(f"{self.base_url}/get-sponsors", headers=headers, json=data)
        return response.json()
    
    def check_user_subscriptions(self, api_key: str, user_id: int, links: List[str] = None) -> Dict:
        """Проверяет подписки пользователя"""
        headers = self.headers.copy()
        headers["Auth"] = api_key
        
        data = {
            "user_id": user_id
        }
        
        if links:
            data["links"] = links
        
        response = requests.post(f"{self.base_url}/get-user-subscriptions", headers=headers, json=data)
        return response.json()

class BotManager:
    def __init__(self):
        self.engine = create_engine('sqlite:///bot_data.db')
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

    def is_admin(self, user_id: int) -> bool:
        admin = self.session.query(Admin).filter(Admin.user_id == user_id).first()
        return user_id in ADMIN_IDS or admin is not None

    def get_admin_permissions(self, user_id: int) -> str:
        if user_id in ADMIN_IDS:
            return "all"
        admin = self.session.query(Admin).filter(Admin.user_id == user_id).first()
        return admin.permissions if admin else "none"

    def add_admin(self, user_id: int, permissions: str = "limited"):
        if not self.is_admin(user_id):
            admin = Admin(user_id=user_id, permissions=permissions)
            self.session.add(admin)
            self.session.commit()
            return True
        return False

    def update_admin_permissions(self, user_id: int, permissions: str):
        admin = self.session.query(Admin).filter(Admin.user_id == user_id).first()
        if admin:
            admin.permissions = permissions
            self.session.commit()
            return True
        return False

    def remove_admin(self, user_id: int):
        if user_id in ADMIN_IDS:
            return False
        admin = self.session.query(Admin).filter(Admin.user_id == user_id).first()
        if admin:
            self.session.delete(admin)
            self.session.commit()
            return True
        return False

    def create_button(self, name: str, parent_id: int, message_text: str, buttons: list, photo_url: str = None, price: float = 0.0):
        button = Button(
            name=name,
            parent_id=parent_id,
            message_text=message_text,
            buttons=json.dumps(buttons, ensure_ascii=False),
            photo_url=photo_url,
            price=price
        )
        self.session.add(button)
        self.session.commit()
        return button.id

    def get_button(self, button_id: int):
        return self.session.query(Button).filter(Button.id == button_id).first()

    def get_child_buttons(self, parent_id: int):
        return self.session.query(Button).filter(Button.parent_id == parent_id).all()

    def get_all_buttons(self):
        return self.session.query(Button).all()

    def delete_button(self, button_id: int):
        button = self.get_button(button_id)
        if button:
            self.session.delete(button)
            self.session.commit()
            return True
        return False

    def get_user_balance(self, user_id: int) -> float:
        balance = self.session.query(UserBalance).filter(UserBalance.user_id == user_id).first()
        if balance:
            return balance.balance
        else:
            new_balance = UserBalance(user_id=user_id, balance=0.0)
            self.session.add(new_balance)
            self.session.commit()
            return 0.0

    def update_user_balance(self, user_id: int, amount: float):
        balance = self.session.query(UserBalance).filter(UserBalance.user_id == user_id).first()
        if balance:
            balance.balance += amount
        else:
            balance = UserBalance(user_id=user_id, balance=amount)
            self.session.add(balance)
        self.session.commit()
        return balance.balance

    def has_completed_task(self, user_id: int, button_id: int) -> bool:
        task = self.session.query(CompletedTasks).filter(
            CompletedTasks.user_id == user_id,
            CompletedTasks.button_id == button_id
        ).first()
        return task is not None

    def add_completed_task(self, user_id: int, button_id: int):
        if not self.has_completed_task(user_id, button_id):
            task = CompletedTasks(user_id=user_id, button_id=button_id)
            self.session.add(task)
            self.session.commit()
            return True
        return False

    def set_task_screenshot_sent(self, user_id: int, button_id: int):
        task = self.session.query(CompletedTasks).filter(
            CompletedTasks.user_id == user_id,
            CompletedTasks.button_id == button_id
        ).first()
        if task:
            task.screenshot_sent = True
            self.session.commit()
            return True
        return False

    def approve_task(self, user_id: int, button_id: int):
        task = self.session.query(CompletedTasks).filter(
            CompletedTasks.user_id == user_id,
            CompletedTasks.button_id == button_id
        ).first()
        if task and not task.approved:
            task.approved = True
            button = self.get_button(button_id)
            if button and button.price > 0:
                self.update_user_balance(user_id, button.price)
            self.session.commit()
            return True
        return False

    def add_referral(self, referrer_id: int, referred_id: int):
        existing = self.session.query(Referral).filter(
            Referral.referred_id == referred_id
        ).first()
        if not existing and referrer_id != referred_id:
            referral = Referral(referrer_id=referrer_id, referred_id=referred_id)
            self.session.add(referral)
            self.session.commit()
            return True
        return False

    def get_referrer(self, referred_id: int):
        referral = self.session.query(Referral).filter(
            Referral.referred_id == referred_id
        ).first()
        return referral.referrer_id if referral else None

    def mark_first_task_completed(self, referred_id: int):
        referral = self.session.query(Referral).filter(
            Referral.referred_id == referred_id
        ).first()
        if referral and not referral.first_task_completed:
            referral.first_task_completed = True
            self.session.commit()
            return True
        return False

    def get_all_users(self):
        users = self.session.query(UserBalance).all()
        return [user.user_id for user in users]

    def get_user_subgram_data(self, user_id: int):
        """Получает данные пользователя для SubGram"""
        user_data = self.session.query(UserSubGramData).filter(UserSubGramData.user_id == user_id).first()
        return user_data

    def update_user_subgram_data(self, user_id: int, gender: str = None, age: int = None):
        """Обновляет данные пользователя для SubGram"""
        user_data = self.session.query(UserSubGramData).filter(UserSubGramData.user_id == user_id).first()
        if not user_data:
            user_data = UserSubGramData(user_id=user_id, gender=gender, age=age)
            self.session.add(user_data)
        else:
            if gender:
                user_data.gender = gender
            if age:
                user_data.age = age
        self.session.commit()
        return user_data

# Добавим модель для хранения данных SubGram пользователя
class UserSubGramData(Base):
    __tablename__ = 'user_subgram_data'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    gender = Column(String(10))  # male, female
    age = Column(Integer)
    updated_at = Column(DateTime, default=datetime.now)

# Конфигурация
BOT_TOKEN = "7803868173:AAF7MrQCePuVzxJyOdm9DzzFnL3817S2100"
ADMIN_IDS = [8358009538]
REFERRAL_BONUS = 10.0
REFERRER_BONUS_PERCENT = 0.1

# SubGram настройки
SUBGRAM_SECRET_KEY = "f1dc509d4996cb3fcf7a5c1ba28dffdb69d6d1a5f275d79cd639ff57a4a70395"
SUBGRAM_BOT_API_KEY = None  # Будет установлен автоматически

# Инициализация менеджеров
bot_manager = BotManager()
subgram_manager = SubGramManager(SUBGRAM_SECRET_KEY)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = update.effective_user
    
    # Обработка реферальной ссылки
    if context.args:
        try:
            referrer_id = int(context.args[0])
            if bot_manager.add_referral(referrer_id, user_id):
                bot_manager.update_user_balance(user_id, REFERRAL_BONUS)
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 По вашей ссылке зарегистрировался новый пользователь! Вы получите {REFERRER_BONUS_PERCENT*100}% от его первого заработка."
                    )
                except Exception as e:
                    logger.error(f"Error notifying referrer: {e}")
        except ValueError:
            pass
    
    # Проверяем подписки через SubGram
    if SUBGRAM_BOT_API_KEY:
        subgram_result = await check_subgram_subscriptions(update, context, user)
        if subgram_result == "blocked":
            return  # Пользователь не прошел проверку
    
    if bot_manager.is_admin(user_id):
        keyboard = [
            [InlineKeyboardButton("📋 Админ панель", callback_data="admin_panel")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Добро пожаловать! Вы администратор.",
            reply_markup=reply_markup
        )
    else:
        await show_main_menu(update, context)

async def check_subgram_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    """Проверяет подписки пользователя через SubGram"""
    try:
        user_id = user.id
        chat_id = update.effective_chat.id
        
        # Получаем данные пользователя для SubGram
        user_data = bot_manager.get_user_subgram_data(user_id)
        
        result = subgram_manager.get_sponsors(
            api_key=SUBGRAM_BOT_API_KEY,
            user_id=user_id,
            chat_id=chat_id,
            first_name=user.first_name,
            username=user.username,
            language_code=user.language_code,
            is_premium=user.is_premium,
            gender=user_data.gender if user_data else None,
            age=user_data.age if user_data else None
        )
        
        logger.info(f"SubGram response: {result}")
        
        if result.get("status") == "ok":
            # Пользователь прошел проверку
            return "passed"
        
        elif result.get("status") == "warning":
            # Нужно подписаться на каналы
            await show_subgram_sponsors(update, context, result)
            return "blocked"
        
        elif result.get("status") == "register":
            # Нужно заполнить анкету
            await show_subgram_registration(update, context, result)
            return "blocked"
        
        elif result.get("status") in ["gender", "age"]:
            # Нужно указать пол/возраст
            await ask_user_info(update, context, result.get("status"))
            return "blocked"
        
        else:
            # Ошибка или другие статусы - пропускаем пользователя
            return "passed"
            
    except Exception as e:
        logger.error(f"Error checking SubGram subscriptions: {e}")
        return "passed"  # В случае ошибки пропускаем пользователя

async def show_subgram_sponsors(update: Update, context: ContextTypes.DEFAULT_TYPE, subgram_result):
    """Показывает спонсоров для подписки"""
    sponsors = subgram_result.get("additional", {}).get("sponsors", [])
    
    if not sponsors:
        await send_message(update, context, "❌ Ошибка при получении списка каналов.")
        return
    
    message_text = "📢 Для доступа к боту необходимо подписаться на следующие каналы:\n\n"
    
    keyboard = []
    for sponsor in sponsors:
        if sponsor.get("available_now", False) and sponsor.get("status") == "unsubscribed":
            message_text += f"• {sponsor.get('resource_name', 'Канал')}\n"
            keyboard.append([InlineKeyboardButton(
                f"✅ {sponsor.get('button_text', 'Подписаться')} - {sponsor.get('resource_name', 'Канал')}",
                url=sponsor.get('link', '')
            )])
    
    keyboard.append([InlineKeyboardButton("🔁 Проверить подписки", callback_data="check_subscriptions")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_message(update, context, message_text, reply_markup)

async def show_subgram_registration(update: Update, context: ContextTypes.DEFAULT_TYPE, subgram_result):
    """Показывает форму регистрации SubGram"""
    registration_url = subgram_result.get("additional", {}).get("registration_url", "")
    
    if not registration_url:
        await send_message(update, context, "❌ Ошибка при получении формы регистрации.")
        return
    
    keyboard = [
        [InlineKeyboardButton(
            "✅ Пройти быструю регистрацию",
            web_app=WebAppInfo(url=registration_url)
        )],
        [InlineKeyboardButton("🔁 Проверить подписки", callback_data="check_subscriptions")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message(update, context, 
        "Для продолжения, пожалуйста, укажите ваш пол и возраст в форме регистрации.",
        reply_markup
    )

async def ask_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE, info_type: str):
    """Запрашивает у пользователя дополнительную информацию"""
    if info_type == "gender":
        keyboard = [
            [InlineKeyboardButton("👨 Мужской", callback_data="set_gender_male")],
            [InlineKeyboardButton("👩 Женский", callback_data="set_gender_female")],
            [InlineKeyboardButton("🔁 Проверить подписки", callback_data="check_subscriptions")]
        ]
        message_text = "Пожалуйста, укажите ваш пол:"
    else:  # age
        keyboard = [
            [InlineKeyboardButton("🔞 До 18", callback_data="set_age_17")],
            [InlineKeyboardButton("👤 18-24", callback_data="set_age_21")],
            [InlineKeyboardButton("👨 25-34", callback_data="set_age_30")],
            [InlineKeyboardButton("👴 35+", callback_data="set_age_35")],
            [InlineKeyboardButton("🔁 Проверить подписки", callback_data="check_subscriptions")]
        ]
        message_text = "Пожалуйста, укажите ваш возраст:"
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_message(update, context, message_text, reply_markup)

async def handle_user_info_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор пола/возраста пользователем"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data.startswith("set_gender_"):
        gender = data.split("_")[2]  # male или female
        bot_manager.update_user_subgram_data(user_id, gender=gender)
        await send_message(update, context, f"✅ Пол сохранен: {'Мужской' if gender == 'male' else 'Женский'}")
        
    elif data.startswith("set_age_"):
        age_str = data.split("_")[2]
        age_map = {"17": 17, "21": 21, "30": 30, "35": 35}
        age = age_map.get(age_str, 25)
        bot_manager.update_user_subgram_data(user_id, age=age)
        await send_message(update, context, f"✅ Возраст сохранен: {age} лет")
    
    # После сохранения данных проверяем подписки снова
    await check_subscriptions_callback(update, context)

async def check_subscriptions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки проверки подписок"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    subgram_result = await check_subgram_subscriptions(update, context, user)
    
    if subgram_result == "passed":
        await send_message(update, context, "✅ Отлично! Теперь у вас есть доступ к боту.")
        await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = bot_manager.get_child_buttons(0)
    
    if not buttons:
        keyboard = [
            [InlineKeyboardButton("💰 Баланс", callback_data="balance")],
            [InlineKeyboardButton("👥 Реферальная система", callback_data="referral")],
            [InlineKeyboardButton("📞 Связь с администратором", callback_data="contact_admin")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_message(update, context, "Добро пожаловать! Меню находится в разработке.", reply_markup)
        return

    keyboard = []
    for button in buttons:
        keyboard.append([InlineKeyboardButton(button.name, callback_data=f"button_{button.id}")])
    
    keyboard.append([InlineKeyboardButton("💰 Баланс", callback_data="balance")])
    keyboard.append([InlineKeyboardButton("👥 Реферальная система", callback_data="referral")])
    
    user_id = update.effective_user.id
    if bot_manager.is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ Админ панель", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_message(update, context, "🏠 Главное меню", reply_markup)

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = bot_manager.get_user_balance(user_id)
    
    keyboard = [
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message(update, context, f"💰 Ваш баланс: {balance:.2f} руб.", reply_markup)

async def show_referral_system(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    
    message_text = f"""
👥 Реферальная система

🔗 Ваша реферальная ссылка:
`{referral_link}`

💰 Бонусы:
• Приглашенный друг получает {REFERRAL_BONUS} руб.
• Вы получаете {REFERRER_BONUS_PERCENT*100}% от первого заработка приглашенного

Приглашайте друзей и зарабатывайте вместе!
    """
    
    keyboard = [
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message(update, context, message_text, reply_markup)

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == "main_menu":
        await show_main_menu(update, context)
    
    elif data == "admin_panel":
        await show_admin_panel(update, context)
    
    elif data == "contact_admin":
        await send_message(update, context, "📞 Свяжитесь с администратором: @MoneyMovesAdmin1")
    
    elif data == "balance":
        await show_balance(update, context)
    
    elif data == "referral":
        await show_referral_system(update, context)
    
    elif data == "check_subscriptions":
        await check_subscriptions_callback(update, context)
    
    elif data.startswith("set_gender_") or data.startswith("set_age_"):
        await handle_user_info_selection(update, context)
    
    elif data.startswith("start_task_"):
        button_id = int(data.split("_")[2])
        button = bot_manager.get_button(button_id)
        
        if button and button.price > 0:
            if bot_manager.has_completed_task(user_id, button_id):
                await send_message(update, context, "❌ Вы уже выполняли это задание!")
                return
            
            bot_manager.add_completed_task(user_id, button_id)
            context.user_data['awaiting_screenshot'] = True
            context.user_data['task_button_id'] = button_id
            
            keyboard = [
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await send_message(update, context, 
                f"✅ Вы начали задание!\n\n"
                f"После выполнения задания отправьте скриншот подтверждения в этот чат.\n"
                f"Администратор проверит его и начислит {button.price:.2f} руб. на ваш баланс.",
                reply_markup)
    
    elif data.startswith("button_"):
        button_id = int(data.split("_")[1])
        button = bot_manager.get_button(button_id)
        
        if button:
            if button.photo_url and button.price > 0:
                await show_task_page(update, context, button)
                return
            
            child_buttons_data = json.loads(button.buttons) if button.buttons else []
            child_buttons = bot_manager.get_child_buttons(button_id)
            
            keyboard = []
            
            for child_button in child_buttons:
                keyboard.append([InlineKeyboardButton(child_button.name, callback_data=f"button_{child_button.id}")])
            
            for btn_data in child_buttons_data:
                if "url" in btn_data:
                    keyboard.append([InlineKeyboardButton(btn_data["name"], url=btn_data["url"])])
                else:
                    keyboard.append([InlineKeyboardButton(btn_data["name"], callback_data=btn_data["callback_data"])])
            
            if button.parent_id != 0:
                keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f"button_{button.parent_id}")])
            keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await send_message(update, context, button.message_text, reply_markup)
    
    # Админские callback'ы
    elif data == "subgram_management":
        await subgram_management(update, context)
    elif data == "subgram_register":
        await subgram_register_bot(update, context)
    elif data == "subgram_info":
        await subgram_bot_info(update, context)
    elif data == "subgram_settings":
        await subgram_settings(update, context)
    elif data == "add_button":
        await admin_add_button(update, context)
    elif data == "list_buttons":
        await admin_list_buttons(update, context)
    elif data == "delete_button":
        await admin_delete_button(update, context)
    elif data == "broadcast":
        await admin_broadcast(update, context)
    elif data == "manage_admins":
        await manage_admins(update, context)
    elif data == "add_admin":
        await admin_add_admin(update, context)
    elif data == "list_admins":
        await list_admins(update, context)
    elif data == "change_admin_perms":
        await change_admin_permissions(update, context)
    elif data.startswith("delete_btn_"):
        await handle_delete_button(update, context)
    elif data.startswith("remove_admin_"):
        await handle_remove_admin(update, context)
    elif data.startswith("parent_"):
        await handle_parent_selection(update, context)

async def show_task_page(update: Update, context: ContextTypes.DEFAULT_TYPE, button: Button):
    user_id = update.effective_user.id
    has_completed = bot_manager.has_completed_task(user_id, button.id)
    
    message_text = f"{button.message_text}\n\n💰 Стоимость: {button.price:.2f} руб."
    
    if has_completed:
        message_text += "\n\n✅ Вы уже выполнили это задание"
    
    child_buttons_data = json.loads(button.buttons) if button.buttons else []
    
    keyboard = []
    
    if not has_completed:
        keyboard.append([InlineKeyboardButton("🎯 Начать задание", callback_data=f"start_task_{button.id}")])
    
    for btn_data in child_buttons_data:
        if "url" in btn_data:
            keyboard.append([InlineKeyboardButton(btn_data["name"], url=btn_data["url"])])
    
    if button.parent_id != 0:
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f"button_{button.parent_id}")])
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        if update.callback_query:
            if button.photo_url:
                await update.callback_query.edit_message_media(
                    media=InputFile(button.photo_url) if not button.photo_url.startswith('http') else button.photo_url,
                    caption=message_text,
                    reply_markup=reply_markup
                )
            else:
                await update.callback_query.edit_message_text(
                    text=message_text,
                    reply_markup=reply_markup
                )
        else:
            if button.photo_url:
                await update.message.reply_photo(
                    photo=button.photo_url,
                    caption=message_text,
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text(
                    text=message_text,
                    reply_markup=reply_markup
                )
    except Exception as e:
        logger.error(f"Error sending task page: {e}")
        await send_message(update, context, message_text, reply_markup)

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if context.user_data.get('awaiting_screenshot') and (update.message.photo or update.message.document):
        button_id = context.user_data.get('task_button_id')
        button = bot_manager.get_button(button_id)
        
        if button:
            bot_manager.set_task_screenshot_sent(user_id, button_id)
            context.user_data.pop('awaiting_screenshot', None)
            context.user_data.pop('task_button_id', None)
            
            await update.message.reply_text(
                "✅ Скриншот отправлен на проверку администратору!\n"
                "Мы проверим его в ближайшее время и начислим деньги на ваш баланс."
            )
            
            admins = bot_manager.session.query(Admin).all()
            admin_ids = [admin.user_id for admin in admins] + ADMIN_IDS
            
            for admin_id in admin_ids:
                try:
                    if update.message.photo:
                        await context.bot.send_photo(
                            chat_id=admin_id,
                            photo=update.message.photo[-1].file_id,
                            caption=f"📸 Скриншот для проверки\n\n"
                                   f"👤 Пользователь: {user_id}\n"
                                   f"📁 Задание: {button.name}\n"
                                   f"💰 Сумма: {button.price:.2f} руб.\n\n"
                                   f"Для подтверждения используйте команду:\n"
                                   f"/approve_task {user_id} {button_id}"
                        )
                    elif update.message.document:
                        await context.bot.send_document(
                            chat_id=admin_id,
                            document=update.message.document.file_id,
                            caption=f"📸 Скриншот для проверки\n\n"
                                   f"👤 Пользователь: {user_id}\n"
                                   f"📁 Задание: {button.name}\n"
                                   f"💰 Сумма: {button.price:.2f} руб.\n\n"
                                   f"Для подтверждения используйте команду:\n"
                                   f"/approve_task {user_id} {button_id}"
                        )
                except Exception as e:
                    logger.error(f"Error notifying admin {admin_id}: {e}")

async def approve_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not bot_manager.is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text("Использование: /approve_task <user_id> <button_id>")
        return
    
    try:
        target_user_id = int(context.args[0])
        button_id = int(context.args[1])
        
        button = bot_manager.get_button(button_id)
        if not button:
            await update.message.reply_text("❌ Задание не найдено.")
            return
        
        if bot_manager.approve_task(target_user_id, button_id):
            referrer_id = bot_manager.get_referrer(target_user_id)
            if referrer_id and bot_manager.mark_first_task_completed(target_user_id):
                bonus_amount = button.price * REFERRER_BONUS_PERCENT
                bot_manager.update_user_balance(referrer_id, bonus_amount)
                
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 Ваш реферал выполнил первое задание! Вы получили {bonus_amount:.2f} руб. бонуса."
                    )
                except Exception as e:
                    logger.error(f"Error notifying referrer: {e}")
            
            await update.message.reply_text(
                f"✅ Задание подтверждено!\n"
                f"Пользователь {target_user_id} получил {button.price:.2f} руб."
            )
            
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"✅ Ваш скриншот проверен! На ваш баланс зачислено {button.price:.2f} руб."
                )
            except Exception as e:
                logger.error(f"Error notifying user: {e}")
        else:
            await update.message.reply_text("❌ Не удалось подтвердить задание. Возможно, оно уже подтверждено.")
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат аргументов.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📞 Написать администратору", url="https://t.me/MoneyMovesAdmin1")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Привет!\nмне нужна помощь :",
        reply_markup=reply_markup
    )

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_balance(update, context)

# SubGram функции админ-панели
async def subgram_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if bot_manager.get_admin_permissions(user_id) != "all":
        await send_message(update, context, "❌ У вас нет прав для управления SubGram.")
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ Зарегистрировать бота в SubGram", callback_data="subgram_register")],
        [InlineKeyboardButton("ℹ️ Информация о боте", callback_data="subgram_info")],
        [InlineKeyboardButton("⚙️ Настройки SubGram", callback_data="subgram_settings")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message(update, context, "🎯 Управление SubGram интеграцией", reply_markup)

async def subgram_register_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if bot_manager.get_admin_permissions(user_id) != "all":
        await send_message(update, context, "❌ У вас нет прав для управления SubGram.")
        return
    
    try:
        result = subgram_manager.add_bot(
            bot_token=BOT_TOKEN,
            max_sponsors=4,
            time_purge=180,
            text_op="Подпишитесь на каналы ниже чтобы получить доступ к контенту!",
            forbidden_themes=["adult", "crypto"]
        )
        
        if result.get("status") == "ok":
            global SUBGRAM_BOT_API_KEY
            SUBGRAM_BOT_API_KEY = result["result"]["api_key"]
            message = f"""
✅ Бот успешно зарегистрирован в SubGram!

🔑 API Key: `{SUBGRAM_BOT_API_KEY}`

Теперь вы можете использовать проверку подписок в своем боте.
"""
        else:
            message = f"❌ Ошибка регистрации: {result.get('message', 'Неизвестная ошибка')}"
            
    except Exception as e:
        message = f"❌ Ошибка при регистрации: {str(e)}"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="subgram_management")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message(update, context, message, reply_markup)

async def subgram_bot_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if bot_manager.get_admin_permissions(user_id) != "all":
        await send_message(update, context, "❌ У вас нет прав для управления SubGram.")
        return
    
    if not SUBGRAM_BOT_API_KEY:
        await send_message(update, context, "❌ Бот не зарегистрирован в SubGram.")
        return
    
    try:
        bot_id = int(BOT_TOKEN.split(':')[0])
        bot_info = subgram_manager.get_bot_info(bot_id)
        
        if bot_info.get("status") == "ok":
            result = bot_info["result"]
            message = f"""
📊 Информация о боте в SubGram:

🆔 ID: {result['bot_id']}
📛 Имя: {result['bot_name']}
👤 Юзернейм: @{result['bot_nickname']}
📊 Прибыль: {result['profit']} руб.
🔧 Статус: {'Включен' if result['is_on'] else 'Выключен'}
"""
        else:
            message = f"❌ Ошибка получения информации: {bot_info.get('message')}"
            
    except Exception as e:
        message = f"❌ Ошибка: {str(e)}"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="subgram_management")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message(update, context, message, reply_markup)

async def subgram_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if bot_manager.get_admin_permissions(user_id) != "all":
        await send_message(update, context, "❌ У вас нет прав для управления SubGram.")
        return
    
    keyboard = [
        [InlineKeyboardButton("🔧 Обновить настройки", callback_data="subgram_update_settings")],
        [InlineKeyboardButton("🔙 Назад", callback_data="subgram_management")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message(update, context, 
        "⚙️ Настройки SubGram:\n\n"
        "Здесь вы можете изменить настройки интеграции с SubGram.",
        reply_markup
    )

# Остальные функции админ-панели (оставлены без изменений)
async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    permissions = bot_manager.get_admin_permissions(user_id)
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить кнопку", callback_data="add_button")],
        [InlineKeyboardButton("📋 Список кнопок", callback_data="list_buttons")],
        [InlineKeyboardButton("🗑️ Удалить кнопку", callback_data="delete_button")],
        [InlineKeyboardButton("🎯 Управление SubGram", callback_data="subgram_management")],
    ]
    
    if permissions == "all":
        keyboard.extend([
            [InlineKeyboardButton("📢 Рассылка", callback_data="broadcast")],
            [InlineKeyboardButton("👥 Управление админами", callback_data="manage_admins")],
        ])
    
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_message(update, context, "⚙️ Админ панель", reply_markup)

async def admin_add_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not bot_manager.is_admin(user_id):
        await send_message(update, context, "❌ У вас нет прав для выполнения этого действия.")
        return
    
    context.user_data['awaiting_button_name'] = True
    context.user_data['admin_action'] = 'add_button'
    
    await send_message(update, context, "Введите название для новой кнопки:")

async def admin_list_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not bot_manager.is_admin(user_id):
        await send_message(update, context, "❌ У вас нет прав для выполнения этого действия.")
        return
    
    buttons = bot_manager.get_all_buttons()
    
    if not buttons:
        await send_message(update, context, "❌ Нет созданных кнопок.")
        return
    
    message_text = "📋 Список кнопок:\n\n"
    for button in buttons:
        parent_name = "Корень" if button.parent_id == 0 else f"ID:{button.parent_id}"
        message_text += f"📁 {button.name} (ID: {button.id})\n"
        message_text += f"Родитель: {parent_name}\n"
        message_text += f"Текст: {button.message_text[:50]}...\n"
        if button.price > 0:
            message_text += f"Цена: {button.price:.2f} руб.\n"
        message_text += "\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message(update, context, message_text, reply_markup)

async def admin_delete_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not bot_manager.is_admin(user_id):
        await send_message(update, context, "❌ У вас нет прав для выполнения этого действия.")
        return
    
    buttons = bot_manager.get_all_buttons()
    
    if not buttons:
        await send_message(update, context, "❌ Нет созданных кнопок для удаления.")
        return
    
    keyboard = []
    for button in buttons:
        keyboard.append([InlineKeyboardButton(f"🗑️ {button.name} (ID: {button.id})", callback_data=f"delete_btn_{button.id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message(update, context, "Выберите кнопку для удаления:", reply_markup)

async def handle_delete_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not bot_manager.is_admin(user_id):
        await send_message(update, context, "❌ У вас нет прав для выполнения этого действия.")
        return
    
    if query.data.startswith("delete_btn_"):
        button_id = int(query.data.split("_")[2])
        button = bot_manager.get_button(button_id)
        
        if button:
            button_name = button.name
            if bot_manager.delete_button(button_id):
                await send_message(update, context, f"✅ Кнопка '{button_name}' успешно удалена!")
            else:
                await send_message(update, context, f"❌ Ошибка при удалении кнопки '{button_name}'")
        else:
            await send_message(update, context, "❌ Кнопка не найдена!")
        
        await show_admin_panel(update, context)

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if bot_manager.get_admin_permissions(user_id) != "all":
        await send_message(update, context, "❌ У вас нет прав для рассылки.")
        return
    
    context.user_data['awaiting_broadcast'] = True
    context.user_data['admin_action'] = 'broadcast'
    
    await send_message(update, context, "Введите сообщение для рассылки всем пользователям:")

async def manage_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if bot_manager.get_admin_permissions(user_id) != "all":
        await send_message(update, context, "❌ У вас нет прав для управления админами.")
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить админа", callback_data="add_admin")],
        [InlineKeyboardButton("👥 Список админов", callback_data="list_admins")],
        [InlineKeyboardButton("🔧 Изменить права", callback_data="change_admin_perms")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message(update, context, "👥 Управление администраторами", reply_markup)

async def admin_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if bot_manager.get_admin_permissions(user_id) != "all":
        await send_message(update, context, "❌ У вас нет прав для добавления админов.")
        return
    
    context.user_data['awaiting_admin_id'] = True
    context.user_data['admin_action'] = 'add_admin'
    
    await send_message(update, context, 
        "Введите ID пользователя и уровень прав через пробел:\n\n"
        "Пример:\n"
        "123456789 limited - ограниченные права\n"
        "123456789 all - полные права\n\n"
        "Ограниченные права: добавление/удаление кнопок\n"
        "Полные права: все возможности + управление админами")

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if bot_manager.get_admin_permissions(user_id) != "all":
        await send_message(update, context, "❌ У вас нет прав для просмотра списка админов.")
        return
    
    admins = bot_manager.session.query(Admin).all()
    main_admins = ADMIN_IDS
    
    message_text = "👥 Список администраторов:\n\n"
    message_text += "🏆 Главные администраторы:\n"
    for admin_id in main_admins:
        message_text += f"• ID: {admin_id} (полные права)\n"
    
    message_text += "\n📋 Дополнительные администраторы:\n"
    for admin in admins:
        status = "полные" if admin.permissions == "all" else "ограниченные"
        message_text += f"• ID: {admin.user_id} ({status} права)\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="manage_admins")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message(update, context, message_text, reply_markup)

async def change_admin_permissions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if bot_manager.get_admin_permissions(user_id) != "all":
        await send_message(update, context, "❌ У вас нет прав для изменения прав админов.")
        return
    
    context.user_data['awaiting_admin_id_for_perms'] = True
    context.user_data['admin_action'] = 'change_admin_perms'
    
    await send_message(update, context, 
        "Введите ID администратора и уровень прав через пробел:\n\n"
        "Пример:\n"
        "123456789 limited - ограниченные права\n"
        "123456789 all - полные права\n\n"
        "Ограниченные права: добавление/удаление кнопок\n"
        "Полные права: все возможности + управление админами")

async def handle_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if bot_manager.get_admin_permissions(user_id) != "all":
        await send_message(update, context, "❌ У вас нет прав для удаления админов.")
        return
    
    if query.data.startswith("remove_admin_"):
        admin_id = int(query.data.split("_")[2])
        
        if bot_manager.remove_admin(admin_id):
            await send_message(update, context, f"✅ Администратор {admin_id} удален!")
        else:
            await send_message(update, context, f"❌ Не удалось удалить администратора {admin_id}")
        
        await manage_admins(update, context)

async def handle_parent_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not bot_manager.is_admin(user_id):
        await send_message(update, context, "❌ У вас нет прав для выполнения этого действия.")
        return
    
    if query.data.startswith("parent_"):
        parent_id = int(query.data.split("_")[1])
        context.user_data['parent_id'] = parent_id
        context.user_data['awaiting_parent_id'] = False
        context.user_data['awaiting_message_text'] = True
        
        await send_message(update, context, "Введите текст сообщения для этой кнопки:")

async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not bot_manager.is_admin(user_id):
        return
    
    text = update.message.text
    
    # Обработка добавления админа
    if context.user_data.get('awaiting_admin_id'):
        try:
            parts = text.split()
            if len(parts) != 2:
                await update.message.reply_text("❌ Неверный формат. Введите ID и уровень прав через пробел.")
                return
            
            admin_id = int(parts[0])
            permissions = parts[1].lower()
            
            if permissions not in ['all', 'limited']:
                await update.message.reply_text("❌ Неверный уровень прав. Используйте 'all' или 'limited'.")
                return
            
            if bot_manager.add_admin(admin_id, permissions):
                context.user_data.pop('awaiting_admin_id', None)
                context.user_data.pop('admin_action', None)
                await update.message.reply_text(f"✅ Администратор {admin_id} добавлен с правами: {permissions}")
            else:
                await update.message.reply_text(f"❌ Не удалось добавить администратора {admin_id}. Возможно, он уже есть в списке.")
            
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID. Введите числовой ID.")
        return
    
    # Обработка изменения прав администратора
    elif context.user_data.get('awaiting_admin_id_for_perms'):
        try:
            parts = text.split()
            if len(parts) != 2:
                await update.message.reply_text("❌ Неверный формат. Введите ID и уровень прав через пробел.")
                return
            
            admin_id = int(parts[0])
            permissions = parts[1].lower()
            
            if permissions not in ['all', 'limited']:
                await update.message.reply_text("❌ Неверный уровень прав. Используйте 'all' или 'limited'.")
                return
            
            if admin_id in ADMIN_IDS:
                await update.message.reply_text("❌ Нельзя изменять права главных администраторов.")
                return
            
            if bot_manager.update_admin_permissions(admin_id, permissions):
                context.user_data.pop('awaiting_admin_id_for_perms', None)
                context.user_data.pop('admin_action', None)
                await update.message.reply_text(f"✅ Права администратора {admin_id} обновлены: {permissions}")
            else:
                await update.message.reply_text(f"❌ Не удалось обновить права администратора {admin_id}")
            
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID. Введите числовой ID.")
        return
    
    # Обработка рассылки
    elif context.user_data.get('awaiting_broadcast'):
        broadcast_text = text
        context.user_data.pop('awaiting_broadcast', None)
        context.user_data.pop('admin_action', None)
        
        users = bot_manager.get_all_users()
        sent_count = 0
        failed_count = 0
        
        await update.message.reply_text(f"📢 Начинаю рассылку для {len(users)} пользователей...")
        
        for user_id in users:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=broadcast_text
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"Error sending broadcast to {user_id}: {e}")
                failed_count += 1
        
        await update.message.reply_text(
            f"✅ Рассылка завершена!\n"
            f"📤 Отправлено: {sent_count}\n"
            f"❌ Не отправлено: {failed_count}"
        )
        return
    
    # Обработка добавления кнопки
    elif context.user_data.get('awaiting_button_name'):
        context.user_data['button_name'] = text
        context.user_data['awaiting_button_name'] = False
        context.user_data['awaiting_parent_id'] = True
        
        buttons = bot_manager.get_all_buttons()
        keyboard = [[InlineKeyboardButton("🏠 Корневой уровень", callback_data="parent_0")]]
        
        for button in buttons:
            keyboard.append([InlineKeyboardButton(f"📁 {button.name} (ID: {button.id})", callback_data=f"parent_{button.id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Выберите родительскую кнопку (где будет расположена эта кнопка):", reply_markup=reply_markup)
    
    elif context.user_data.get('awaiting_message_text'):
        context.user_data['message_text'] = text
        context.user_data['awaiting_message_text'] = False
        context.user_data['awaiting_photo_url'] = True
        
        await update.message.reply_text(
            "Введите URL фото для кнопки (или 'нет' если фото не нужно):\n\n"
            "Пример: https://example.com/photo.jpg\n"
            "Или путь к файлу: /path/to/photo.jpg"
        )
    
    elif context.user_data.get('awaiting_photo_url'):
        if text.lower() == 'нет':
            context.user_data['photo_url'] = None
        else:
            context.user_data['photo_url'] = text
        
        context.user_data['awaiting_photo_url'] = False
        context.user_data['awaiting_price'] = True
        
        await update.message.reply_text("Введите цену задания (число, или 0 если это не задание):")
    
    elif context.user_data.get('awaiting_price'):
        try:
            price = float(text)
            context.user_data['price'] = price
            context.user_data['awaiting_price'] = False
            context.user_data['awaiting_buttons_json'] = True
            
            await update.message.reply_text(
                "Введите JSON массив кнопок (или 'нет' если кнопок не нужно):\n\n"
                "Пример:\n"
                '[{"name": "Моя кнопка", "callback_data": "my_button"}]\n'
                'Или: [{"name": "Сайт", "url": "https://example.com"}]'
            )
        except ValueError:
            await update.message.reply_text("❌ Неверный формат цены. Введите число:")
    
    elif context.user_data.get('awaiting_buttons_json'):
        if text.lower() == 'нет':
            buttons_json = "[]"
        else:
            try:
                buttons_data = json.loads(text)
                buttons_json = text
            except json.JSONDecodeError:
                await update.message.reply_text("Ошибка в формате JSON. Попробуйте еще раз:")
                return
        
        button_id = bot_manager.create_button(
            name=context.user_data['button_name'],
            parent_id=context.user_data['parent_id'],
            message_text=context.user_data['message_text'],
            buttons=json.loads(buttons_json),
            photo_url=context.user_data.get('photo_url'),
            price=context.user_data.get('price', 0.0)
        )
        
        for key in ['button_name', 'parent_id', 'message_text', 'photo_url', 'price', 'awaiting_buttons_json', 'admin_action']:
            context.user_data.pop(key, None)
        
        await update.message.reply_text(f"✅ Кнопка '{context.user_data.get('button_name', '')}' успешно создана! ID: {button_id}")

async def send_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=text, 
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(
                text=text, 
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        if update.callback_query:
            await update.callback_query.message.reply_text(
                text=text, 
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(
                text=text, 
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not bot_manager.is_admin(user_id) and not context.user_data.get('admin_action'):
        await show_main_menu(update, context)

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("approve_task", approve_task_command))
    
    # Обработчики callback'ов
    application.add_handler(CallbackQueryHandler(handle_button_click))
    
    # Обработчики сообщений (скриншоты)
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_screenshot))
    
    # Обработчики текстовых сообщений (для админ-панели)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_input))
    
    # Общий обработчик сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запуск бота
    print("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()