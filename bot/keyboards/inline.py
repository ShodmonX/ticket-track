from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shared.translations import get_text

UZ_MONTHS = [
    "yanvar",
    "fevral",
    "mart",
    "aprel",
    "may",
    "iyun",
    "iyul",
    "avgust",
    "sentabr",
    "oktabr",
    "noyabr",
    "dekabr",
]
RU_MONTHS = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]
EN_MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

UZ_WEEKDAYS = [
    "Dushanba",
    "Seshanba",
    "Chorshanba",
    "Payshanba",
    "Juma",
    "Shanba",
    "Yakshanba",
]
RU_WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
EN_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def get_language_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🇺🇿 O'zbekcha", callback_data="lang:uz")
    builder.button(text="🇷🇺 Русский", callback_data="lang:ru")
    builder.button(text="🇬🇧 English", callback_data="lang:en")
    builder.adjust(1)
    return builder.as_markup()


def get_transport_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🚆 Poezd" if lang == "uz" else "🚆 Поезд" if lang == "ru" else "🚆 Train", callback_data="transport:train")
    builder.button(text="🚌 Avtobus" if lang == "uz" else "🚌 Автобус" if lang == "ru" else "🚌 Bus", callback_data="transport:bus")
    builder.button(text=get_text("cancel", lang), callback_data="search:cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_cities_keyboard(cities: list[tuple[str, str]], prefix: str, lang: str = "uz") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code_or_id, name in cities:
        builder.button(text=name, callback_data=f"{prefix}:{code_or_id}")
    builder.adjust(2)
    
    # Add a cancel button at the bottom
    cancel_builder = InlineKeyboardBuilder()
    cancel_builder.button(text=get_text("cancel", lang), callback_data="search:cancel")
    builder.attach(cancel_builder)
    return builder.as_markup()


def format_date_label(dt: datetime, lang: str) -> str:
    day = dt.day
    month_idx = dt.month - 1
    weekday_idx = dt.weekday()
    
    if lang == "ru":
        return f"{day} {RU_MONTHS[month_idx]} ({RU_WEEKDAYS[weekday_idx]})"
    elif lang == "en":
        return f"{day} {EN_MONTHS[month_idx]} ({EN_WEEKDAYS[weekday_idx]})"
    else:
        return f"{day}-{UZ_MONTHS[month_idx]} ({UZ_WEEKDAYS[weekday_idx]})"


def get_date_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    now = datetime.now()
    
    # Button for Today
    today_label = "Bugun" if lang == "uz" else "Сегодня" if lang == "ru" else "Today"
    builder.button(text=f"📅 {today_label} ({now.strftime('%d-%m')})", callback_data=f"date:{now.strftime('%Y-%m-%d')}")
    
    # Button for Tomorrow
    tomorrow = now + timedelta(days=1)
    tomorrow_label = "Ertaga" if lang == "uz" else "Завтра" if lang == "ru" else "Tomorrow"
    builder.button(text=f"📅 {tomorrow_label} ({tomorrow.strftime('%d-%m')})", callback_data=f"date:{tomorrow.strftime('%Y-%m-%d')}")
    
    # Next 7 days
    for i in range(2, 9):
        dt = now + timedelta(days=i)
        label = format_date_label(dt, lang)
        builder.button(text=label, callback_data=f"date:{dt.strftime('%Y-%m-%d')}")
        
    builder.adjust(1)
    
    # Custom date and cancel buttons
    extra_builder = InlineKeyboardBuilder()
    other_label = "Boshqa sana 📅" if lang == "uz" else "Другая дата 📅" if lang == "ru" else "Other date 📅"
    extra_builder.button(text=other_label, callback_data="date:other")
    extra_builder.button(text=get_text("cancel", lang), callback_data="search:cancel")
    extra_builder.adjust(1)
    
    builder.attach(extra_builder)
    return builder.as_markup()


def get_confirm_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=get_text("search_now", lang), callback_data="confirm:search")
    builder.button(text=get_text("start_monitoring", lang), callback_data="confirm:monitor")
    builder.button(text=get_text("cancel", lang), callback_data="confirm:cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_search_results_keyboard(lang: str = "uz", current_page: int = 1, total_pages: int = 1, buy_url: str = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    if buy_url:
        builder.button(text=get_text("btn_buy", lang), url=buy_url)
        builder.adjust(1)
        
    if total_pages > 1:
        page_builder = InlineKeyboardBuilder()
        page_builder.button(text="⬅️", callback_data="search:page:prev")
        page_builder.button(text=f"{current_page} / {total_pages}", callback_data="search:page:noop")
        page_builder.button(text="➡️", callback_data="search:page:next")
        page_builder.adjust(3)
        builder.attach(page_builder)
        
    action_builder = InlineKeyboardBuilder()
    action_builder.button(text=get_text("start_monitoring", lang), callback_data="confirm:monitor")
    action_builder.button(text=get_text("cancel", lang), callback_data="confirm:cancel")
    action_builder.adjust(1)
    
    builder.attach(action_builder)
    return builder.as_markup()
