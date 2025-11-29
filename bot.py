import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import json

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

class Admin(Base):
    __tablename__ = 'admins'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)

# Конфигурация
BOT_TOKEN = "7803868173:AAF7MrQCePuVzxJyOdm9DzzFnL3817S2100"
ADMIN_IDS = [8358009538]  # Замените на ваш ID


class BotManager:
    def __init__(self):
        self.engine = create_engine('sqlite:///bot_data.db')
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

    def is_admin(self, user_id: int) -> bool:
        admin = self.session.query(Admin).filter(Admin.user_id == user_id).first()
        return user_id in ADMIN_IDS or admin is not None

    def add_admin(self, user_id: int):
        if not self.is_admin(user_id):
            admin = Admin(user_id=user_id)
            self.session.add(admin)
            self.session.commit()

    def create_button(self, name: str, parent_id: int, message_text: str, buttons: list):
        button = Button(
            name=name,
            parent_id=parent_id,
            message_text=message_text,
            buttons=json.dumps(buttons, ensure_ascii=False)
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

# Инициализация менеджера
bot_manager = BotManager()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
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
        keyboard = [[InlineKeyboardButton("📞 Связь с администратором", callback_data="contact_admin")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_message(update, context, "Добро пожаловать! Меню находится в разработке.", reply_markup)
        return

    keyboard = []
    for button in buttons:
        keyboard.append([InlineKeyboardButton(button.name, callback_data=f"button_{button.id}")])
    
    # Добавляем кнопку для админов
    user_id = update.effective_user.id
    if bot_manager.is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ Админ панель", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_message(update, context, "🏠 Главное меню", reply_markup)

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
        await send_message(update, context, "📞 Свяжитесь с администратором: @username")
    
    elif data.startswith("button_"):
        button_id = int(data.split("_")[1])
        button = bot_manager.get_button(button_id)
        
        if button:
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

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Добавить кнопку", callback_data="add_button")],
        [InlineKeyboardButton("📋 Список кнопок", callback_data="list_buttons")],
        [InlineKeyboardButton("👥 Добавить админа", callback_data="add_admin")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_message(update, context, "⚙️ Админ панель", reply_markup)

async def admin_add_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['awaiting_button_name'] = True
    context.user_data['admin_action'] = 'add_button'
    
    await send_message(update, context, "Введите название для новой кнопки:")

async def admin_list_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    buttons = bot_manager.get_all_buttons()
    
    if not buttons:
        await send_message(update, context, "❌ Нет созданных кнопок.")
        return
    
    message_text = "📋 Список кнопок:\n\n"
    for button in buttons:
        parent_name = "Корень" if button.parent_id == 0 else f"ID:{button.parent_id}"
        message_text += f"📁 {button.name} (ID: {button.id})\n"
        message_text += f"Родитель: {parent_name}\n"
        message_text += f"Текст: {button.message_text[:50]}...\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message(update, context, message_text, reply_markup)

async def admin_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['awaiting_admin_id'] = True
    context.user_data['admin_action'] = 'add_admin'
    
    await send_message(update, context, "Введите ID пользователя, которого хотите сделать администратором:")

async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not bot_manager.is_admin(user_id):
        return
    
    text = update.message.text
    
    if context.user_data.get('awaiting_button_name'):
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
        context.user_data['awaiting_buttons_json'] = True
        
        await update.message.reply_text(
            "Введите JSON массив кнопок (или 'нет' если кнопок не нужно):\n\n"
            "Пример:\n"
            '[{"name": "Моя кнопка", "callback_data": "my_button"}]\n'
            'Или: [{"name": "Сайт", "url": "https://example.com"}]'
        )
    
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
            buttons=json.loads(buttons_json)
        )
        
        # Очищаем временные данные
        for key in ['button_name', 'parent_id', 'message_text', 'awaiting_buttons_json', 'admin_action']:
            context.user_data.pop(key, None)
        
        await update.message.reply_text(f"✅ Кнопка '{context.user_data.get('button_name', '')}' успешно создана! ID: {button_id}")
    
    elif context.user_data.get('awaiting_admin_id'):
        try:
            new_admin_id = int(text)
            bot_manager.add_admin(new_admin_id)
            context.user_data.pop('awaiting_admin_id', None)
            context.user_data.pop('admin_action', None)
            await update.message.reply_text(f"✅ Пользователь {new_admin_id} добавлен как администратор!")
        except ValueError:
            await update.message.reply_text("❌ Неверный ID. Введите числовой ID:")

async def handle_parent_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("parent_"):
        parent_id = int(query.data.split("_")[1])
        context.user_data['parent_id'] = parent_id
        context.user_data['awaiting_parent_id'] = False
        context.user_data['awaiting_message_text'] = True
        
        await send_message(update, context, "Введите текст сообщения для этой кнопки:")

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
    
    # Обработчики callback'ов
    application.add_handler(CallbackQueryHandler(handle_button_click, pattern="^(main_menu|admin_panel|button_|contact_admin)"))
    application.add_handler(CallbackQueryHandler(admin_add_button, pattern="^add_button$"))
    application.add_handler(CallbackQueryHandler(admin_list_buttons, pattern="^list_buttons$"))
    application.add_handler(CallbackQueryHandler(admin_add_admin, pattern="^add_admin$"))
    application.add_handler(CallbackQueryHandler(handle_parent_selection, pattern="^parent_"))
    
    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_input))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запуск бота
    print("Бот запущен...")
    application.run_polling()

# Функции для управления админами (можно запустить в консоли)
def add_admin_command():
    """Добавить администратора через консоль"""
    user_id = int(input("Введите ID пользователя: "))
    bot_manager.add_admin(user_id)
    print(f"✅ Пользователь {user_id} добавлен как администратор!")

def list_buttons_command():
    """Показать все кнопки"""
    buttons = bot_manager.get_all_buttons()
    if not buttons:
        print("❌ Нет созданных кнопок.")
        return
    
    for button in buttons:
        print(f"ID: {button.id}, Name: {button.name}, Parent: {button.parent_id}")

if __name__ == '__main__':
    # Если нужно добавить админа через консоль, раскомментируйте:
    # add_admin_command()
    
    # Если нужно посмотреть кнопки, раскомментируйте:
    # list_buttons_command()
    
    main()