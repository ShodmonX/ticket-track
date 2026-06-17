import asyncio
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select, func

from bot.core.config import settings
from shared.database import async_session
from shared.models import User, Subscription
from shared.translations import get_text

router = Router()

class AdminStates(StatesGroup):
    wait_for_user_id = State()
    wait_for_broadcast_msg = State()
    wait_for_direct_user_id = State()
    wait_for_direct_msg = State()

def is_admin(tg_id: int) -> bool:
    return tg_id == settings.ADMIN_ID

def get_admin_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🟢 Tarifni o'zgartirish", callback_data="admin:change_tarif")
    builder.button(text="✉️ Ommaviy xabar yuborish", callback_data="admin:broadcast")
    builder.button(text="💬 Shaxsiy xabar yuborish", callback_data="admin:direct_msg")
    builder.button(text="📊 Tizim statistikasi", callback_data="admin:stats")
    builder.adjust(1)
    return builder.as_markup()

def get_tarif_selection_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Bepul (Free) ⚪", callback_data="admin:set_tarif:free")
    builder.button(text="Standart (Standard) 🟢", callback_data="admin:set_tarif:standard")
    builder.button(text="⬅️ Orqaga", callback_data="admin:menu")
    builder.adjust(2, 1)
    return builder.as_markup()

async def get_user_lang(tg_id: int) -> str:
    async with async_session() as session:
        stmt = select(User.language_code).where(User.telegram_id == tg_id)
        res = await session.execute(stmt)
        user_lang = res.scalar_one_or_none()
        return user_lang or "uz"

@router.message(F.text == "/admin")
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    await message.answer(
        get_text("admin_menu", lang),
        reply_markup=get_admin_menu_keyboard(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "admin:menu")
async def callback_admin_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    lang = await get_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        get_text("admin_menu", lang),
        reply_markup=get_admin_menu_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin:change_tarif")
async def callback_change_tarif(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    lang = await get_user_lang(callback.from_user.id)
    await state.set_state(AdminStates.wait_for_user_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Orqaga", callback_data="admin:menu")
    
    await callback.message.edit_text(
        get_text("admin_enter_id", lang),
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.message(AdminStates.wait_for_user_id)
async def process_user_id_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    lang = await get_user_lang(message.from_user.id)
    text = message.text or ""
    
    if not text.isdigit():
        await message.answer(get_text("admin_enter_id", lang))
        return
        
    target_tg_id = int(text)
    
    async with async_session() as session:
        stmt = select(User).where(User.telegram_id == target_tg_id)
        res = await session.execute(stmt)
        target_user = res.scalar_one_or_none()
        
    if not target_user:
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Orqaga", callback_data="admin:menu")
        await message.answer(
            get_text("admin_user_not_found", lang),
            reply_markup=builder.as_markup()
        )
        return
        
    await state.update_data(target_tg_id=target_tg_id)
    
    await message.answer(
        get_text(
            "admin_user_detail",
            lang,
            name=target_user.first_name,
            tg_id=target_user.telegram_id,
            tarif=target_user.subscription_type.capitalize()
        ),
        reply_markup=get_tarif_selection_keyboard()
    )

@router.callback_query(F.data.startswith("admin:set_tarif:"))
async def callback_set_tarif(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    lang = await get_user_lang(callback.from_user.id)
    new_tarif = callback.data.split(":")[2]
    
    state_data = await state.get_data()
    target_tg_id = state_data.get("target_tg_id")
    
    if not target_tg_id:
        await callback.message.edit_text("Seans muddati tugadi.", reply_markup=get_admin_menu_keyboard())
        await callback.answer()
        await state.clear()
        return
        
    async with async_session() as session:
        stmt = select(User).where(User.telegram_id == target_tg_id)
        res = await session.execute(stmt)
        target_user = res.scalar_one_or_none()
        if target_user:
            target_user.subscription_type = new_tarif
            await session.commit()
            
    await state.clear()
    
    await callback.message.edit_text(
        get_text("admin_tarif_updated", lang, tg_id=target_tg_id, tarif=new_tarif.capitalize()),
        reply_markup=get_admin_menu_keyboard()
    )
    await callback.answer()
    
    # Notify user
    if target_user:
        target_lang = target_user.language_code or "uz"
        try:
            from bot.main import bot
            await bot.send_message(
                target_tg_id,
                get_text("user_tarif_updated_notify", target_lang, tarif=new_tarif.capitalize()),
                parse_mode="Markdown"
            )
        except Exception:
            pass

@router.callback_query(F.data == "admin:broadcast")
async def callback_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    lang = await get_user_lang(callback.from_user.id)
    await state.set_state(AdminStates.wait_for_broadcast_msg)
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Orqaga", callback_data="admin:menu")
    await callback.message.edit_text(
        get_text("admin_ask_broadcast_msg", lang),
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.message(AdminStates.wait_for_broadcast_msg)
async def process_broadcast_msg(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    lang = await get_user_lang(message.from_user.id)
    await state.clear()
    await message.answer(get_text("admin_broadcast_started", lang))
    
    async with async_session() as session:
        stmt = select(User)
        res = await session.execute(stmt)
        users = res.scalars().all()
        
    success = 0
    blocked = 0
    errors = 0
    
    for u in users:
        try:
            await message.copy_to(chat_id=u.telegram_id)
            success += 1
            if not u.is_active:
                async with async_session() as s:
                    db_u = (await s.execute(select(User).where(User.telegram_id == u.telegram_id))).scalar_one_or_none()
                    if db_u:
                        db_u.is_active = True
                        await s.commit()
        except TelegramForbiddenError:
            blocked += 1
            if u.is_active:
                async with async_session() as s:
                    db_u = (await s.execute(select(User).where(User.telegram_id == u.telegram_id))).scalar_one_or_none()
                    if db_u:
                        db_u.is_active = False
                        await s.commit()
        except Exception:
            errors += 1
            
        await asyncio.sleep(0.05)
        
    report = get_text(
        "admin_broadcast_report",
        lang,
        success=success,
        blocked=blocked,
        errors=errors
    )
    
    await message.answer(report, reply_markup=get_admin_menu_keyboard(), parse_mode="Markdown")

@router.callback_query(F.data == "admin:direct_msg")
async def callback_direct_msg(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    lang = await get_user_lang(callback.from_user.id)
    await state.set_state(AdminStates.wait_for_direct_user_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Orqaga", callback_data="admin:menu")
    await callback.message.edit_text(
        get_text("admin_ask_direct_user", lang),
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.message(AdminStates.wait_for_direct_user_id)
async def process_direct_user_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    lang = await get_user_lang(message.from_user.id)
    text = message.text or ""
    
    if not text.isdigit():
        await message.answer(get_text("admin_ask_direct_user", lang))
        return
        
    target_tg_id = int(text)
    
    async with async_session() as session:
        stmt = select(User).where(User.telegram_id == target_tg_id)
        res = await session.execute(stmt)
        target_user = res.scalar_one_or_none()
        
    if not target_user:
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Orqaga", callback_data="admin:menu")
        await message.answer(
            get_text("admin_user_not_found", lang),
            reply_markup=builder.as_markup()
        )
        return
        
    await state.update_data(target_tg_id=target_tg_id)
    await state.set_state(AdminStates.wait_for_direct_msg)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Orqaga", callback_data="admin:menu")
    await message.answer(
        get_text("admin_ask_direct_msg", lang),
        reply_markup=builder.as_markup()
    )

@router.message(AdminStates.wait_for_direct_msg)
async def process_direct_msg_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    lang = await get_user_lang(message.from_user.id)
    
    state_data = await state.get_data()
    target_tg_id = state_data.get("target_tg_id")
    await state.clear()
    
    try:
        await message.copy_to(chat_id=target_tg_id)
        
        async with async_session() as session:
            stmt = select(User).where(User.telegram_id == target_tg_id)
            res = await session.execute(stmt)
            target_user = res.scalar_one_or_none()
            if target_user and not target_user.is_active:
                target_user.is_active = True
                await session.commit()
                
        await message.answer(
            get_text("admin_direct_sent", lang, tg_id=target_tg_id),
            reply_markup=get_admin_menu_keyboard()
        )
    except TelegramForbiddenError:
        async with async_session() as session:
            stmt = select(User).where(User.telegram_id == target_tg_id)
            res = await session.execute(stmt)
            target_user = res.scalar_one_or_none()
            if target_user and target_user.is_active:
                target_user.is_active = False
                await session.commit()
                
        await message.answer(
            get_text("admin_direct_failed", lang, error="User blocked the bot (Forbidden)"),
            reply_markup=get_admin_menu_keyboard()
        )
    except Exception as e:
        await message.answer(
            get_text("admin_direct_failed", lang, error=str(e)),
            reply_markup=get_admin_menu_keyboard()
        )

@router.callback_query(F.data == "admin:stats")
async def callback_admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    lang = await get_user_lang(callback.from_user.id)
    
    async with async_session() as session:
        total_users_stmt = select(func.count(User.telegram_id))
        total_users = (await session.execute(total_users_stmt)).scalar() or 0
        
        standard_users_stmt = select(func.count(User.telegram_id)).where(User.subscription_type == "standard")
        standard_users = (await session.execute(standard_users_stmt)).scalar() or 0
        
        active_subs_stmt = select(func.count(Subscription.id)).where(Subscription.is_active == True)
        active_subs = (await session.execute(active_subs_stmt)).scalar() or 0
        
        blocked_users_stmt = select(func.count(User.telegram_id)).where(User.is_active == False)
        blocked_users = (await session.execute(blocked_users_stmt)).scalar() or 0
        
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Orqaga", callback_data="admin:menu")
    
    stats_text = (
        f"📊 **Tizim statistikasi:**\n\n"
        f"👤 Jami foydalanuvchilar: `{total_users}` ta\n"
        f"⭐ Standart tarifidagilar: `{standard_users}` ta\n"
        f"📊 Faol kuzatuvlar: `{active_subs}` ta\n"
        f"❌ Botni bloklaganlar: `{blocked_users}` ta"
    )
    
    await callback.message.edit_text(
        stats_text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()
