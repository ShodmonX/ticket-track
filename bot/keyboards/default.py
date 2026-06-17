from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from shared.translations import get_text


def get_main_menu(lang: str = "uz") -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=get_text("btn_search", lang))
    builder.button(text=get_text("btn_my_monitorings", lang))
    builder.button(text=get_text("btn_settings", lang))
    builder.button(text=get_text("btn_help", lang))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)
