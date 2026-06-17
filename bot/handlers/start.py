from sqlalchemy import select
import logging
import asyncio

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InaccessibleMessage

from bot.core.config import settings
from shared.database import async_session
from shared.models import User
from shared.translations import get_text, TRANSLATIONS
from bot.keyboards.inline import get_language_keyboard
from bot.keyboards.default import get_main_menu

router = Router()
logger = logging.getLogger("__main__")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        await message.answer("Internal Error")
        logger.warning("Start buyrug'ida from user obyekti none ko'rinishda keldi")
        return
    telegram_lang = message.from_user.language_code
    if telegram_lang and telegram_lang.startswith("ru"):
        lang = "ru"
    elif telegram_lang and telegram_lang.startswith("uz"):
        lang = "uz"
    else:
        lang = "en"

    tg_id = message.from_user.id
    chat_id = message.chat.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    show_lang_selector = False

    async with async_session() as session:
        stmt = select(User).where(User.telegram_id == tg_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()

        if not user:
            user = User(
                telegram_id=tg_id,
                chat_id=chat_id,
                username=username,
                first_name=first_name,
                language_code=lang,
            )
            session.add(user)
            show_lang_selector = True
            
            # Notify admin about new user
            if tg_id != settings.ADMIN_ID:
                try:
                    from bot.main import bot
                    notify_msg = get_text(
                        "admin_new_user_start",
                        lang="uz",
                        name=first_name,
                        tg_id=tg_id,
                        username=username or "None"
                    )
                    asyncio.create_task(bot.send_message(settings.ADMIN_ID, notify_msg, parse_mode="Markdown"))
                except Exception as e:
                    logger.error(f"Failed to notify admin on startup: {e}")
        else:
            user.chat_id = chat_id
            user.username = username
            user.first_name = first_name
            lang = user.language_code

        await session.commit()

    if show_lang_selector:
        welcome_text = get_text("welcome", lang=lang, name=first_name)
        await message.answer(welcome_text, reply_markup=get_language_keyboard())
    else:
        welcome_text = get_text("welcome_back", lang=lang, name=first_name)
        await message.answer(welcome_text, reply_markup=get_main_menu(lang))


@router.callback_query(F.data.startswith("lang:"))
async def process_language_selection(callback: CallbackQuery):
    if callback.data is None:
        await callback.answer("Internal Error")
        logger.warning("Til tanlash funksiyasiga callback data none holatida keldi.")
        return
    lang_code = callback.data.split(":")[1]
    tg_id = callback.from_user.id

    async with async_session() as session:
        stmt = select(User).where(User.telegram_id == tg_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()

        if user:
            user.language_code = lang_code
            await session.commit()

    success_text = get_text("lang_selected", lang=lang_code)
    if callback.message is None:
        await callback.answer("Internal Error")
        logger.warning(
            "Til tanlash qismida callback message none bo'lganligi sababli matn tahrirlanmadi."
        )
        return
    if isinstance(callback.message, InaccessibleMessage):
        await callback.answer("Internal Error")
        logger.warning(
            "Til tanlash qismida callback message InaccessibleMessage klasiga tegishli."
        )
        return
    await callback.message.edit_text(success_text)

    await callback.message.answer(
        get_text("menu", lang=lang_code),
        reply_markup=get_main_menu(lang=lang_code),
    )
    await callback.answer()


@router.message(
    F.text.in_(
        [
            TRANSLATIONS["uz"]["btn_settings"],
            TRANSLATIONS["ru"]["btn_settings"],
            TRANSLATIONS["en"]["btn_settings"],
        ]
    )
)
async def cmd_settings(message: Message):
    if message.from_user is None:
        return
    tg_id = message.from_user.id
    async with async_session() as session:
        stmt = select(User).where(User.telegram_id == tg_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        lang = user.language_code if user else "uz"

    await message.answer(
        get_text("select_lang", lang=lang), reply_markup=get_language_keyboard()
    )


@router.message(
    F.text.in_(
        [
            TRANSLATIONS["uz"]["btn_help"],
            TRANSLATIONS["ru"]["btn_help"],
            TRANSLATIONS["en"]["btn_help"],
        ]
    )
)
async def cmd_help(message: Message):
    if message.from_user is None:
        return
    tg_id = message.from_user.id
    async with async_session() as session:
        stmt = select(User).where(User.telegram_id == tg_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        lang = user.language_code if user else "uz"

    await message.answer(get_text("help_text", lang=lang), parse_mode="Markdown")
