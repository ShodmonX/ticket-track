from sqlalchemy import select, delete
import logging
import asyncio

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InaccessibleMessage, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shared.database import async_session
from shared.models import User, Subscription
from shared.translations import get_text, TRANSLATIONS, format_car_class, format_price_k
from bot.keyboards.default import get_main_menu
from tracker.railway import fast_ticket_track
from tracker.avtoticket import fetch_avtoticket_trips

router = Router()
logger = logging.getLogger("__main__")


async def get_user_lang(tg_id: int) -> str:
    async with async_session() as session:
        stmt = select(User.language_code).where(User.telegram_id == tg_id)
        res = await session.execute(stmt)
        user_lang = res.scalar_one_or_none()
        return user_lang or "uz"


def get_uz_today_str() -> str:
    import datetime
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    uz_now = utc_now + datetime.timedelta(hours=5)
    return uz_now.strftime("%Y-%m-%d")


async def auto_deactivate_expired(user_id: int):
    uz_today_str = get_uz_today_str()
    async with async_session() as session:
        stmt = (
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .where(Subscription.is_active == True)
            .where(Subscription.date < uz_today_str)
        )
        res = await session.execute(stmt)
        expired_subs = res.scalars().all()
        if expired_subs:
            for es in expired_subs:
                es.is_active = False
            await session.commit()


def get_subscriptions_keyboard(
    subs: list[Subscription], lang: str
) -> InlineKeyboardMarkup:
    uz_today_str = get_uz_today_str()

    builder = InlineKeyboardBuilder()
    for idx, sub in enumerate(subs, 1):
        if sub.date < uz_today_str:
            status_icon = "⌛"
        else:
            status_icon = "🟢" if sub.is_active else "⏸️"
        transport_icon = (
            "🚆"
            if sub.transport_type == "train"
            else "🚌"
            if sub.transport_type == "bus"
            else "🔄"
        )
        text = f"{idx}. {sub.origin_name} ➔ {sub.destination_name} ({sub.date}) {transport_icon} {status_icon}"
        builder.button(text=text, callback_data=f"track:detail:{sub.id}")
    builder.adjust(1)

    back_builder = InlineKeyboardBuilder()
    back_builder.button(
        text=get_text("btn_back", lang), callback_data="track:back_to_menu"
    )
    builder.attach(back_builder)
    return builder.as_markup()


def get_subscription_detail_keyboard(
    sub_id: int, is_active: bool, is_expired: bool, lang: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not is_expired:
        builder.button(
            text=get_text("btn_check_now", lang),
            callback_data=f"track:check:{sub_id}",
        )
        if is_active:
            builder.button(
                text=get_text("btn_pause", lang),
                callback_data=f"track:pause:{sub_id}",
            )
        else:
            builder.button(
                text=get_text("btn_resume", lang),
                callback_data=f"track:resume:{sub_id}",
            )

    builder.button(
        text=get_text("btn_delete", lang),
        callback_data=f"track:delete:{sub_id}",
    )
    builder.button(
        text=get_text("btn_back", lang), callback_data="track:list"
    )
    if not is_expired:
        builder.adjust(2, 2)
    else:
        builder.adjust(2)
    return builder.as_markup()


@router.message(
    F.text.in_(
        [
            TRANSLATIONS["uz"]["btn_my_monitorings"],
            TRANSLATIONS["ru"]["btn_my_monitorings"],
            TRANSLATIONS["en"]["btn_my_monitorings"],
        ]
    )
)
async def cmd_my_monitorings(message: Message):
    if message.from_user is None:
        return
    tg_id = message.from_user.id
    lang = await get_user_lang(tg_id)

    await auto_deactivate_expired(tg_id)

    async with async_session() as session:
        stmt = (
            select(Subscription)
            .where(Subscription.user_id == tg_id)
            .order_by(Subscription.created_at.desc())
        )
        res = await session.execute(stmt)
        subs = list(res.scalars().all())

    if not subs:
        await message.answer(get_text("no_monitorings", lang))
    else:
        await message.answer(
            get_text("my_monitorings_title", lang),
            reply_markup=get_subscriptions_keyboard(subs, lang),
            parse_mode="Markdown",
        )


@router.callback_query(F.data == "track:list")
async def track_list_callback(callback: CallbackQuery):
    tg_id = callback.from_user.id
    lang = await get_user_lang(tg_id)

    await auto_deactivate_expired(tg_id)

    async with async_session() as session:
        stmt = (
            select(Subscription)
            .where(Subscription.user_id == tg_id)
            .order_by(Subscription.created_at.desc())
        )
        res = await session.execute(stmt)
        subs = list(res.scalars().all())

    if callback.message is None or isinstance(
        callback.message, InaccessibleMessage
    ):
        return

    if not subs:
        await callback.message.edit_text(
            get_text("no_monitorings", lang),
            reply_markup=get_subscriptions_keyboard([], lang),
        )
    else:
        await callback.message.edit_text(
            get_text("my_monitorings_title", lang),
            reply_markup=get_subscriptions_keyboard(subs, lang),
            parse_mode="Markdown",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("track:detail:"))
async def track_detail_callback(callback: CallbackQuery):
    if callback.data is None:
        return
    sub_id = int(callback.data.split(":")[2])
    tg_id = callback.from_user.id
    lang = await get_user_lang(tg_id)

    async with async_session() as session:
        stmt = select(Subscription).where(Subscription.id == sub_id)
        res = await session.execute(stmt)
        sub = res.scalar_one_or_none()

    if not sub:
        await callback.answer("Error: Subscription not found")
        return

    uz_today_str = get_uz_today_str()
    is_expired = sub.date < uz_today_str

    if is_expired:
        status_str = get_text("status_expired", lang)
    else:
        status_str = (
            get_text("status_active", lang)
            if sub.is_active
            else get_text("status_paused", lang)
        )
    transport_name = sub.transport_type.capitalize()

    detail_text = get_text(
        "monitoring_detail",
        lang=lang,
        origin=sub.origin_name,
        destination=sub.destination_name,
        date=sub.date,
        transport=transport_name,
        status=status_str,
    )

    if callback.message is None or isinstance(
        callback.message, InaccessibleMessage
    ):
        return

    await callback.message.edit_text(
        detail_text,
        reply_markup=get_subscription_detail_keyboard(
            sub.id, sub.is_active, is_expired, lang
        ),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("track:pause:"))
async def track_pause_callback(callback: CallbackQuery):
    if callback.data is None:
        return
    sub_id = int(callback.data.split(":")[2])
    tg_id = callback.from_user.id
    lang = await get_user_lang(tg_id)

    async with async_session() as session:
        stmt = select(Subscription).where(Subscription.id == sub_id)
        res = await session.execute(stmt)
        sub = res.scalar_one_or_none()

        if sub:
            uz_today_str = get_uz_today_str()
            is_expired = sub.date < uz_today_str
            if is_expired:
                sub.is_active = False
                await session.commit()
                await callback.answer(get_text("action_expired", lang), show_alert=True)
                return

            sub.is_active = False
            await session.commit()
            status_str = get_text("status_paused", lang)
            transport_name = sub.transport_type.capitalize()
            detail_text = get_text(
                "monitoring_detail",
                lang=lang,
                origin=sub.origin_name,
                destination=sub.destination_name,
                date=sub.date,
                transport=transport_name,
                status=status_str,
            )
            if callback.message is not None and not isinstance(
                callback.message, InaccessibleMessage
            ):
                await callback.message.edit_text(
                    detail_text,
                    reply_markup=get_subscription_detail_keyboard(
                        sub.id, False, is_expired, lang
                    ),
                    parse_mode="Markdown",
                )

    await callback.answer(get_text("action_paused", lang))


@router.callback_query(F.data.startswith("track:resume:"))
async def track_resume_callback(callback: CallbackQuery):
    if callback.data is None:
        return
    sub_id = int(callback.data.split(":")[2])
    tg_id = callback.from_user.id
    lang = await get_user_lang(tg_id)

    async with async_session() as session:
        stmt = select(Subscription).where(Subscription.id == sub_id)
        res = await session.execute(stmt)
        sub = res.scalar_one_or_none()

        if sub:
            uz_today_str = get_uz_today_str()
            is_expired = sub.date < uz_today_str
            if is_expired:
                sub.is_active = False
                await session.commit()
                await callback.answer(get_text("action_expired", lang), show_alert=True)
                return

            sub.is_active = True
            await session.commit()
            status_str = get_text("status_active", lang)
            transport_name = sub.transport_type.capitalize()
            detail_text = get_text(
                "monitoring_detail",
                lang=lang,
                origin=sub.origin_name,
                destination=sub.destination_name,
                date=sub.date,
                transport=transport_name,
                status=status_str,
            )
            if callback.message is not None and not isinstance(
                callback.message, InaccessibleMessage
            ):
                await callback.message.edit_text(
                    detail_text,
                    reply_markup=get_subscription_detail_keyboard(
                        sub.id, True, is_expired, lang
                    ),
                    parse_mode="Markdown",
                )

    await callback.answer(get_text("action_resumed", lang))


@router.callback_query(F.data.startswith("track:delete:"))
async def track_delete_callback(callback: CallbackQuery):
    if callback.data is None:
        return
    sub_id = int(callback.data.split(":")[2])
    tg_id = callback.from_user.id
    lang = await get_user_lang(tg_id)

    async with async_session() as session:
        stmt = delete(Subscription).where(Subscription.id == sub_id)
        await session.execute(stmt)
        await session.commit()

        # Re-fetch subscriptions list
        stmt_list = (
            select(Subscription)
            .where(Subscription.user_id == tg_id)
            .order_by(Subscription.created_at.desc())
        )
        res_list = await session.execute(stmt_list)
        subs = list(res_list.scalars().all())

    await callback.answer(get_text("action_deleted", lang))

    if callback.message is None or isinstance(
        callback.message, InaccessibleMessage
    ):
        return

    if not subs:
        await callback.message.edit_text(
            get_text("no_monitorings", lang),
            reply_markup=get_subscriptions_keyboard([], lang),
        )
    else:
        await callback.message.edit_text(
            get_text("my_monitorings_title", lang),
            reply_markup=get_subscriptions_keyboard(subs, lang),
            parse_mode="Markdown",
        )


@router.callback_query(F.data.startswith("track:check:"))
async def track_check_callback(callback: CallbackQuery):
    if callback.data is None:
        return
    sub_id = int(callback.data.split(":")[2])
    tg_id = callback.from_user.id
    lang = await get_user_lang(tg_id)

    async with async_session() as session:
        stmt = select(Subscription).where(Subscription.id == sub_id)
        res = await session.execute(stmt)
        sub = res.scalar_one_or_none()

    if not sub:
        await callback.answer("Error: Subscription not found")
        return

    uz_today_str = get_uz_today_str()
    if sub.date < uz_today_str:
        await callback.answer(get_text("action_expired", lang), show_alert=True)
        return

    if callback.message is None or isinstance(
        callback.message, InaccessibleMessage
    ):
        return

    # Loading indicator
    loading_msg = await callback.message.answer(
        "🔍 Qidirilmoqda..."
        if lang == "uz"
        else "🔍 Поиск..."
        if lang == "ru"
        else "🔍 Searching..."
    )
    await callback.answer()

    # Query API in a thread executor
    results = []

    if (
        (sub.transport_type == "train" or sub.transport_type == "both")
        and sub.train_dep_code
        and sub.train_arv_code
    ):
        try:
            train_res = await fast_ticket_track(sub.date, sub.train_dep_code, sub.train_arv_code)
            if (
                train_res
                and train_res.get("data")
                and train_res["data"].get("directions")
            ):
                fwd = train_res["data"]["directions"].get("forward", {})
                trains = fwd.get("trains", [])
                for t in trains:
                    train_num = t.get("number", "")
                    dep_time = t.get("departureDate", "").split()[-1]
                    arr_time = t.get("arrivalDate", "").split()[-1]
                    
                    brand = t.get("brand")
                    origin_route = t.get("originRoute", {})
                    if brand and brand not in ["Пассажирский", "Скорый", "Tezyurar", "Tezkor", "Passenger", "Fast"]:
                        train_name = brand
                    elif origin_route and origin_route.get("depStationName") and origin_route.get("arvStationName"):
                        dep_station = origin_route.get("depStationName").strip().title()
                        arv_station = origin_route.get("arvStationName").strip().title()
                        if "Markaziy" in arv_station: arv_station = arv_station.replace("Markaziy", "").strip()
                        if "Yuzhny" in arv_station: arv_station = arv_station.replace("Yuzhny", "").strip()
                        if "Южный" in arv_station: arv_station = arv_station.replace("Южный", "").strip()
                        if "Центральный" in arv_station: arv_station = arv_station.replace("Центральный", "").strip()
                        train_name = f"{dep_station} — {arv_station}"
                    else:
                        train_name = brand or get_text("lbl_train", lang)

                    seats_by_class = {}
                    for car in t.get("cars", []):
                        c_type = car.get("type", "")
                        for tariff in car.get("tariffs", []):
                            st = tariff.get("classServiceType", "")
                            free = tariff.get("freeSeats", 0) or car.get("freeSeats", 0)
                            if free <= 0:
                                continue
                            price_val = int(tariff.get("tariff", 0))
                            c_display = format_car_class(c_type, st, lang)
                            if c_display not in seats_by_class:
                                seats_by_class[c_display] = {"seats": 0, "prices": []}
                            seats_by_class[c_display]["seats"] += free
                            if price_val:
                                seats_by_class[c_display]["prices"].append(price_val)

                    seats_lines = []
                    for c_display, info in seats_by_class.items():
                        seats_num = info["seats"]
                        prices = sorted(list(set(info["prices"])))
                        if len(prices) == 1:
                            price_str = format_price_k(prices[0])
                        elif len(prices) > 1:
                            price_str = f"{format_price_k(prices[0])} — {format_price_k(prices[-1])}"
                        else:
                            price_str = "—"
                        seats_lines.append(f"  🔹 {c_display}: `{seats_num}` {get_text('lbl_seat_count', lang)} — {price_str}")

                    if seats_lines:
                        seats_block = "\n".join(seats_lines)
                        results.append(
                            f"🚆 {train_num} «{train_name}» | 🕒 `{dep_time}` ➔ `{arr_time}`\n"
                            f"{seats_block}"
                        )
        except Exception as e:
            logger.error(f"Error checking trains in manual tracking check: {e}")

    if (
        (sub.transport_type == "bus" or sub.transport_type == "both")
        and sub.bus_dep_id
        and sub.bus_arv_id
    ):
        try:
            bus_res = await fetch_avtoticket_trips(sub.date, int(sub.bus_dep_id), int(sub.bus_arv_id), 1)
            if bus_res and bus_res.get("success") and bus_res.get("data"):
                for day in bus_res["data"]:
                    for trip in day.get("trips", []):
                        dep = trip.get("departure_at", "").split()[-1][:5]
                        arr = trip.get("arrive_at", "").split()[-1][:5]
                        seats = trip.get("seats", 0)
                        sold = trip.get("sold_seats", 0)
                        free = seats - sold
                        price_val = int(trip.get('price', 0))
                        price_str = format_price_k(price_val)
                        carrier = trip.get("transporter_name", "").strip().strip('"')

                        if free > 0:
                            results.append(
                                f"🚌 «{carrier}» | 🕒 `{dep}` ➔ `{arr}`\n"
                                f"  🔹 {get_text('lbl_seats', lang)}: `{free}/{seats}` {get_text('lbl_seat_unit', lang)} — {price_str}"
                            )
        except Exception as e:
            logger.error(f"Error checking buses in manual tracking check: {e}")

    if not results:
        transport_type = sub.transport_type
        transport_name = (
            "Poyezd 🚆" if transport_type == "train" else "Avtobus 🚌"
        )
        if lang == "ru":
            transport_name = "Поезд 🚆" if transport_type == "train" else "Автобус 🚌"
        elif lang == "en":
            transport_name = "Train 🚆" if transport_type == "train" else "Bus 🚌"

        try:
            await loading_msg.delete()
        except Exception as e:
            logger.error(f"Error deleting loading message: {e}")

        await callback.message.answer(
            get_text(
                "no_tickets_found",
                lang,
                origin=sub.origin_name,
                destination=sub.destination_name,
                date=sub.date,
                transport=transport_name,
            ),
            reply_markup=get_main_menu(lang),
            parse_mode="Markdown",
        )
    else:
        formatted = "\n\n".join(results)
        try:
            await loading_msg.delete()
        except Exception as e:
            logger.error(f"Error deleting loading message: {e}")

        results_text = get_text("search_results", lang, results=formatted)
        if results:
            results_text += get_text("price_legend", lang)

        await callback.message.answer(
            results_text,
            reply_markup=get_main_menu(lang),
            parse_mode="Markdown",
        )


@router.callback_query(F.data == "track:back_to_menu")
async def track_back_to_menu_callback(callback: CallbackQuery):
    tg_id = callback.from_user.id
    lang = await get_user_lang(tg_id)
    if callback.message is None or isinstance(
        callback.message, InaccessibleMessage
    ):
        return
    await callback.message.edit_text(
        get_text("menu", lang), reply_markup=get_main_menu(lang)
    )
    await callback.answer()
