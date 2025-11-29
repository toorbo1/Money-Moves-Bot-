import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import json
import os
from typing import Dict, List
from datetime import datetime

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

# Конфигурация
BOT_TOKEN = "7803868173:AAF7MrQCePuVzxJyOdm9DzzFnL3817S2100"
ADMIN_IDS = [8358009538]  # Главные администраторы
REFERRAL_BONUS = 10.0  # Бонус приглашенному
REFERRER_BONUS_PERCENT = 0.1  # 10% от первого заработка приглашенного

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
            return False  # Нельзя удалить главного администратора
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
            # Создаем запись баланса, если её нет
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
            # Начисляем деньги за задание
            button = self.get_button(button_id)
            if button and button.price > 0:
                self.update_user_balance(user_id, button.price)
            self.session.commit()
            return True
        return False

    def add_referral(self, referrer_id: int, referred_id: int):
        # Проверяем, нет ли уже такой записи
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
        """Получить всех пользователей, у которых есть баланс"""
        users = self.session.query(UserBalance).all()
        return [user.user_id for user in users]

# Инициализация менеджера
bot_manager = BotManager()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Обработка реферальной ссылки
    if context.args:
        try:
            referrer_id = int(context.args[0])
            if bot_manager.add_referral(referrer_id, user_id):
                # Начисляем бонус приглашенному
                bot_manager.update_user_balance(user_id, REFERRAL_BONUS)
                
                # Уведомляем пригласившего
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 По вашей ссылке зарегистрировался новый пользователь! Вы получите {REFERRER_BONUS_PERCENT*100}% от его первого заработка."
                    )
                except Exception as e:
                    logger.error(f"Error notifying referrer: {e}")
        except ValueError:
            pass
    
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

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = bot_manager.get_child_buttons(0)  # Кнопки верхнего уровня
    
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
    
    # Добавляем кнопку баланса и реферальной системы
    keyboard.append([InlineKeyboardButton("💰 Баланс", callback_data="balance")])
    keyboard.append([InlineKeyboardButton("👥 Реферальная система", callback_data="referral")])
    
    # Добавляем кнопку для админов
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
    
    # Генерируем реферальную ссылку
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
    
    elif data.startswith("start_task_"):
        button_id = int(data.split("_")[2])
        button = bot_manager.get_button(button_id)
        
        if button and button.price > 0:
            # Проверяем, не выполнял ли пользователь уже это задание
            if bot_manager.has_completed_task(user_id, button_id):
                await send_message(update, context, "❌ Вы уже выполняли это задание!")
                return
            
            # Добавляем задание в список выполненных (но еще не подтвержденных)
            bot_manager.add_completed_task(user_id, button_id)
            
            # Устанавливаем состояние ожидания скриншота
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
            # Если у кнопки есть фото и цена, показываем страницу задания
            if button.photo_url and button.price > 0:
                await show_task_page(update, context, button)
                return
            
            # Парсим кнопки из JSON
            child_buttons_data = json.loads(button.buttons) if button.buttons else []
            child_buttons = bot_manager.get_child_buttons(button_id)
            
            keyboard = []
            
            # Добавляем дочерние кнопки из базы данных
            for child_button in child_buttons:
                keyboard.append([InlineKeyboardButton(child_button.name, callback_data=f"button_{child_button.id}")])
            
            # Добавляем кнопки из JSON
            for btn_data in child_buttons_data:
                if "url" in btn_data:
                    keyboard.append([InlineKeyboardButton(btn_data["name"], url=btn_data["url"])])
                else:
                    keyboard.append([InlineKeyboardButton(btn_data["name"], callback_data=btn_data["callback_data"])])
            
            # Добавляем кнопку назад
            if button.parent_id != 0:
                keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f"button_{button.parent_id}")])
            keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await send_message(update, context, button.message_text, reply_markup)
    
    # Админские callback'ы
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
    """Показывает страницу задания с фото, ценой и кнопкой для начала задания"""
    user_id = update.effective_user.id
    
    # Проверяем, выполнял ли пользователь уже это задание
    has_completed = bot_manager.has_completed_task(user_id, button.id)
    
    message_text = f"{button.message_text}\n\n💰 Стоимость: {button.price:.2f} руб."
    
    if has_completed:
        message_text += "\n\n✅ Вы уже выполнили это задание"
    
    # Парсим кнопки из JSON
    child_buttons_data = json.loads(button.buttons) if button.buttons else []
    
    keyboard = []
    
    # Добавляем кнопку для начала задания только если пользователь еще не выполнял его
    if not has_completed:
        keyboard.append([InlineKeyboardButton("🎯 Начать задание", callback_data=f"start_task_{button.id}")])
    
    # Добавляем кнопки из JSON (ссылки)
    for btn_data in child_buttons_data:
        if "url" in btn_data:
            keyboard.append([InlineKeyboardButton(btn_data["name"], url=btn_data["url"])])
    
    # Добавляем навигационные кнопки
    if button.parent_id != 0:
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f"button_{button.parent_id}")])
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отправляем фото с текстом и кнопками
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
        # Если не удалось отправить фото, отправляем просто текст
        await send_message(update, context, message_text, reply_markup)

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка скриншотов от пользователей"""
    user_id = update.effective_user.id
    
    if context.user_data.get('awaiting_screenshot') and (update.message.photo or update.message.document):
        button_id = context.user_data.get('task_button_id')
        button = bot_manager.get_button(button_id)
        
        if button:
            # Отмечаем, что скриншот отправлен
            bot_manager.set_task_screenshot_sent(user_id, button_id)
            
            # Очищаем состояние
            context.user_data.pop('awaiting_screenshot', None)
            context.user_data.pop('task_button_id', None)
            
            # Уведомляем пользователя
            await update.message.reply_text(
                "✅ Скриншот отправлен на проверку администратору!\n"
                "Мы проверим его в ближайшее время и начислим деньги на ваш баланс."
            )
            
            # Уведомляем администраторов
            admins = bot_manager.session.query(Admin).all()
            admin_ids = [admin.user_id for admin in admins] + ADMIN_IDS
            
            for admin_id in admin_ids:
                try:
                    # Пересылаем сообщение со скриншотом администратору
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
    """Команда для подтверждения задания администратором"""
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
        
        # Подтверждаем задание
        if bot_manager.approve_task(target_user_id, button_id):
            # Начисляем бонус рефереру если это первое задание
            referrer_id = bot_manager.get_referrer(target_user_id)
            if referrer_id and bot_manager.mark_first_task_completed(target_user_id):
                # Начисляем 10% от заработка приглашенного
                bonus_amount = button.price * REFERRER_BONUS_PERCENT
                bot_manager.update_user_balance(referrer_id, bonus_amount)
                
                # Уведомляем реферера
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
            
            # Уведомляем пользователя
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
    """Команда /help - открывает чат с администратором"""
    keyboard = [
        [InlineKeyboardButton("📞 Написать администратору", url="https://t.me/MoneyMovesAdmin1")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Привет!\nмне нужна помощь :",
        reply_markup=reply_markup
    )

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /balance - показывает баланс"""
    await show_balance(update, context)

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    permissions = bot_manager.get_admin_permissions(user_id)
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить кнопку", callback_data="add_button")],
        [InlineKeyboardButton("📋 Список кнопок", callback_data="list_buttons")],
        [InlineKeyboardButton("🗑️ Удалить кнопку", callback_data="delete_button")],
    ]
    
    # Только админы с полными правами могут управлять другими админами и делать рассылку
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
            
            # Нельзя изменять права главных администраторов
            if admin_id in ADMIN_IDS:
                await update.message.reply_text("❌ Нельзя изменять права главных администраторов.")
                return
            
            # Обновляем права
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
        
        # Получаем всех пользователей
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
        
        # Показываем список существующих кнопок для выбора родителя
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
                # Валидируем JSON
                buttons_data = json.loads(text)
                buttons_json = text
            except json.JSONDecodeError:
                await update.message.reply_text("Ошибка в формате JSON. Попробуйте еще раз:")
                return
        
        # Создаем кнопку в базе данных
        button_id = bot_manager.create_button(
            name=context.user_data['button_name'],
            parent_id=context.user_data['parent_id'],
            message_text=context.user_data['message_text'],
            buttons=json.loads(buttons_json),
            photo_url=context.user_data.get('photo_url'),
            price=context.user_data.get('price', 0.0)
        )
        
        # Очищаем временные данные
        for key in ['button_name', 'parent_id', 'message_text', 'photo_url', 'price', 'awaiting_buttons_json', 'admin_action']:
            context.user_data.pop(key, None)
        
        await update.message.reply_text(f"✅ Кнопка '{context.user_data.get('button_name', '')}' успешно создана! ID: {button_id}")

async def send_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    """Универсальная функция отправки сообщений"""
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
    """Обработка обычных сообщений"""
    user_id = update.effective_user.id
    
    # Если пользователь не админ и не в процессе диалога с админ-панелью
    if not bot_manager.is_admin(user_id) and not context.user_data.get('admin_action'):
        await show_main_menu(update, context)

def main():
    # Создаем приложение
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