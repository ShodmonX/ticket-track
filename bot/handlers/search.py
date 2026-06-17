from datetime import datetime
import os
import json
import logging
import asyncio

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InaccessibleMessage
from sqlalchemy import select, func

from shared.database import async_session
from shared.models import User, Subscription, SubscriptionState
from shared.translations import get_text, TRANSLATIONS, format_car_class, format_price_k
from bot.keyboards.inline import (
    get_transport_keyboard,
    get_cities_keyboard,
    get_date_keyboard,
    get_confirm_keyboard,
    get_search_results_keyboard,
)
from bot.keyboards.default import get_main_menu
from tracker.railway import fast_ticket_track
from tracker.avtoticket import fetch_avtoticket_trips
from bot.core.config import settings

router = Router()
logger = logging.getLogger("__main__")

# Load station/city data
DATA_DIR = "/app/shared/data"
if not os.path.exists(DATA_DIR):
    DATA_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "shared", "data"
    )

with open(os.path.join(DATA_DIR, "train_data.json"), "r", encoding="utf-8") as f:
    TRAIN_STATIONS = json.load(f)

with open(os.path.join(DATA_DIR, "bus_data.json"), "r", encoding="utf-8") as f:
    BUS_DATA = json.load(f)

# Flatten geography to map city_id -> city_name
BUS_CITIES = {}
for reg_id, reg in BUS_DATA["geography"].items():
    for city_id, city_name in reg["cities"].items():
        BUS_CITIES[city_id] = city_name

# Valid origin city IDs for bus
VALID_BUS_ORIGINS = set(BUS_DATA["routes"].keys())

# Popular lists for quick selection
# All train stations list sorted by name
ALL_TRAIN_STATIONS = sorted(
    [(code, name) for code, name in TRAIN_STATIONS.items()],
    key=lambda x: x[1]
)


class SearchStates(StatesGroup):
    transport_type = State()

    # Bus nested flow
    bus_origin_region = State()
    bus_origin_city = State()
    bus_dest_region = State()
    bus_dest_city = State()

    # Train direct flow
    train_origin = State()
    train_dest = State()

    # Shared steps
    date = State()
    confirm = State()


async def get_user_lang(tg_id: int) -> str:
    async with async_session() as session:
        stmt = select(User.language_code).where(User.telegram_id == tg_id)
        res = await session.execute(stmt)
        user_lang = res.scalar_one_or_none()
        return user_lang or "uz"


# Step 0: Start search flow
@router.message(
    F.text.in_(
        [
            TRANSLATIONS["uz"]["btn_search"],
            TRANSLATIONS["ru"]["btn_search"],
            TRANSLATIONS["en"]["btn_search"],
        ]
    )
)
async def cmd_start_search(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user is None:
        return
    lang = await get_user_lang(message.from_user.id)
    await state.update_data(lang=lang)
    await state.set_state(SearchStates.transport_type)
    await message.answer(
        get_text("select_transport", lang),
        reply_markup=get_transport_keyboard(lang),
    )


# Step 1: Transport Type callback selection
@router.callback_query(
    SearchStates.transport_type, F.data.startswith("transport:")
)
async def select_transport_callback(callback: CallbackQuery, state: FSMContext):
    if callback.data is None:
        return
    transport_type = callback.data.split(":")[1]
    await state.update_data(transport_type=transport_type)
    data = await state.get_data()
    lang = data.get("lang", "uz")

    if callback.message is None or isinstance(
        callback.message, InaccessibleMessage
    ):
        return

    if transport_type == "bus":
        # 1. Bus Flow: Origin Region selection
        # Filter regions that contain at least one city in routes keys (valid origins)
        valid_regions = []
        for reg_id, reg in BUS_DATA["geography"].items():
            has_origin = any(
                city_id in VALID_BUS_ORIGINS for city_id in reg["cities"].keys()
            )
            if has_origin:
                valid_regions.append((reg_id, reg["name"]))

        await state.set_state(SearchStates.bus_origin_region)
        await callback.message.edit_text(
            get_text("select_origin_region", lang),
            reply_markup=get_cities_keyboard(
                valid_regions, "bus_origin_region", lang
            ),
        )
    else:
        # 2. Train Flow: Direct Origin station selection
        await state.set_state(SearchStates.train_origin)
        await callback.message.edit_text(
            get_text("select_origin_train", lang),
            reply_markup=get_cities_keyboard(
                ALL_TRAIN_STATIONS, "train_origin", lang
            ),
        )
    await callback.answer()


# =====================================================================
# BUS FLOW HANDLERS (Region -> City Hierarchy)
# =====================================================================

@router.callback_query(
    SearchStates.bus_origin_region, F.data.startswith("bus_origin_region:")
)
async def select_bus_origin_region_callback(
    callback: CallbackQuery, state: FSMContext
):
    if callback.data is None:
        return
    reg_id = callback.data.split(":")[1]
    data = await state.get_data()
    lang = data.get("lang", "uz")

    # Filter cities in this region that are valid bus origins
    reg = BUS_DATA["geography"].get(reg_id, {"cities": {}, "name": ""})
    cities = []
    for city_id, city_name in reg["cities"].items():
        if city_id in VALID_BUS_ORIGINS:
            cities.append((city_id, city_name))

    await state.set_state(SearchStates.bus_origin_city)
    if callback.message is None or isinstance(
        callback.message, InaccessibleMessage
    ):
        return
    await callback.message.edit_text(
        get_text("select_origin_city", lang),
        reply_markup=get_cities_keyboard(cities, "bus_origin_city", lang),
    )
    await callback.answer()


@router.callback_query(
    SearchStates.bus_origin_city, F.data.startswith("bus_origin_city:")
)
async def select_bus_origin_city_callback(
    callback: CallbackQuery, state: FSMContext
):
    if callback.data is None:
        return
    city_id = callback.data.split(":")[1]
    data = await state.get_data()
    lang = data.get("lang", "uz")

    origin_name = BUS_CITIES.get(city_id, "")
    await state.update_data(bus_dep_id=city_id, origin_name=origin_name)

    # Get valid destination regions from this origin city
    valid_routes = BUS_DATA["routes"].get(city_id, {})
    dest_regions = []
    for r_id in valid_routes.keys():
        if r_id in BUS_DATA["geography"]:
            dest_regions.append((r_id, BUS_DATA["geography"][r_id]["name"]))

    await state.set_state(SearchStates.bus_dest_region)
    if callback.message is None or isinstance(
        callback.message, InaccessibleMessage
    ):
        return
    await callback.message.edit_text(
        get_text("select_dest_region", lang),
        reply_markup=get_cities_keyboard(
            dest_regions, "bus_dest_region", lang
        ),
    )
    await callback.answer()


@router.callback_query(
    SearchStates.bus_dest_region, F.data.startswith("bus_dest_region:")
)
async def select_bus_dest_region_callback(
    callback: CallbackQuery, state: FSMContext
):
    if callback.data is None:
        return
    reg_id = callback.data.split(":")[1]
    data = await state.get_data()
    lang = data.get("lang", "uz")
    origin_city_id = data.get("bus_dep_id", "")

    # Get destination cities in this region
    valid_routes = BUS_DATA["routes"].get(origin_city_id, {})
    city_ids = valid_routes.get(reg_id, [])
    cities = []
    for c_id in city_ids:
        if c_id in BUS_CITIES:
            cities.append((c_id, BUS_CITIES[c_id]))

    await state.set_state(SearchStates.bus_dest_city)
    if callback.message is None or isinstance(
        callback.message, InaccessibleMessage
    ):
        return
    await callback.message.edit_text(
        get_text("select_dest_city", lang),
        reply_markup=get_cities_keyboard(cities, "bus_dest_city", lang),
    )
    await callback.answer()


@router.callback_query(
    SearchStates.bus_dest_city, F.data.startswith("bus_dest_city:")
)
async def select_bus_dest_city_callback(
    callback: CallbackQuery, state: FSMContext
):
    if callback.data is None:
        return
    city_id = callback.data.split(":")[1]
    data = await state.get_data()
    lang = data.get("lang", "uz")

    dest_name = BUS_CITIES.get(city_id, "")
    await state.update_data(bus_arv_id=city_id, destination_name=dest_name)

    await state.set_state(SearchStates.date)
    if callback.message is None or isinstance(
        callback.message, InaccessibleMessage
    ):
        return
    await callback.message.edit_text(
        get_text("select_date", lang), reply_markup=get_date_keyboard(lang)
    )
    await callback.answer()


# =====================================================================
# TRAIN FLOW HANDLERS (Direct Stations & Text Search)
# =====================================================================

@router.callback_query(SearchStates.train_origin, F.data.startswith("train_origin:"))
async def select_train_origin_callback(callback: CallbackQuery, state: FSMContext):
    if callback.data is None:
        return
    station_code = callback.data.split(":")[1]
    data = await state.get_data()
    lang = data.get("lang", "uz")

    origin_name = TRAIN_STATIONS.get(station_code, "")
    await state.update_data(train_dep_code=station_code, origin_name=origin_name)

    # Filter destinations (excluding origin, sorted alphabetically)
    destinations = sorted(
        [(c, n) for c, n in ALL_TRAIN_STATIONS if n != origin_name],
        key=lambda x: x[1]
    )

    await state.set_state(SearchStates.train_dest)
    if callback.message is None or isinstance(
        callback.message, InaccessibleMessage
    ):
        return
    await callback.message.edit_text(
        get_text("select_dest_train", lang),
        reply_markup=get_cities_keyboard(destinations, "train_dest", lang),
    )
    await callback.answer()


@router.callback_query(SearchStates.train_dest, F.data.startswith("train_dest:"))
async def select_train_dest_callback(callback: CallbackQuery, state: FSMContext):
    if callback.data is None:
        return
    station_code = callback.data.split(":")[1]
    data = await state.get_data()
    lang = data.get("lang", "uz")

    dest_name = TRAIN_STATIONS.get(station_code, "")
    await state.update_data(train_arv_code=station_code, destination_name=dest_name)

    await state.set_state(SearchStates.date)
    if callback.message is None or isinstance(
        callback.message, InaccessibleMessage
    ):
        return
    await callback.message.edit_text(
        get_text("select_date", lang), reply_markup=get_date_keyboard(lang)
    )
    await callback.answer()


@router.message(
    SearchStates.bus_origin_region,
    SearchStates.bus_origin_city,
    SearchStates.bus_dest_region,
    SearchStates.bus_dest_city,
    SearchStates.train_origin,
    SearchStates.train_dest,
)
async def invalid_region_city_text_input(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await message.answer(get_text("invalid_text_input", lang))


# =====================================================================
# SHARED FLOW HANDLERS (Date & Confirmation)
# =====================================================================

@router.callback_query(SearchStates.date, F.data.startswith("date:"))
async def select_date_callback(callback: CallbackQuery, state: FSMContext):
    if callback.data is None:
        return
    date_val = callback.data.split(":")[1]
    data = await state.get_data()
    lang = data.get("lang", "uz")

    if date_val == "other":
        if callback.message is None or isinstance(
            callback.message, InaccessibleMessage
        ):
            return
        await callback.message.edit_text(get_text("select_date", lang))
        await callback.answer()
        return

    await state.update_data(date=date_val)
    await show_confirmation_step(callback, state)
    await callback.answer()


@router.message(SearchStates.date)
async def search_date_text(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    text = message.text

    if not text:
        await message.answer(get_text("invalid_date", lang))
        return

    parsed_date = None
    current_year = datetime.now().year

    for fmt in ("%d-%m-%Y", "%d.%m.%Y"):
        try:
            parsed_date = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue

    if not parsed_date:
        for fmt in ("%d-%m", "%d.%m"):
            try:
                parsed_date = datetime.strptime(
                    f"{text}-{current_year}", f"{fmt}-%Y"
                )
                break
            except ValueError:
                continue

    if not parsed_date or parsed_date.date() < datetime.now().date():
        await message.answer(get_text("invalid_date", lang))
        return

    date_str = parsed_date.strftime("%Y-%m-%d")
    await state.update_data(date=date_str)

    t_type = data.get("transport_type")
    if t_type == "train":
        transport_name = f"{get_text('lbl_train', lang)} 🚆"
    else:
        transport_name = f"{get_text('lbl_bus', lang)} 🚌"

    confirm_text = get_text(
        "confirm_subscription",
        lang=lang,
        origin=data.get("origin_name", ""),
        destination=data.get("destination_name", ""),
        date=date_str,
        transport=transport_name,
    )
    await message.answer(
        confirm_text, reply_markup=get_confirm_keyboard(lang), parse_mode="Markdown"
    )
    await state.set_state(SearchStates.confirm)


async def show_confirmation_step(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    date_str = data.get("date", "")
    t_type = data.get("transport_type")
    if t_type == "train":
        transport_name = f"{get_text('lbl_train', lang)} 🚆"
    else:
        transport_name = f"{get_text('lbl_bus', lang)} 🚌"

    confirm_text = get_text(
        "confirm_subscription",
        lang=lang,
        origin=data.get("origin_name", ""),
        destination=data.get("destination_name", ""),
        date=date_str,
        transport=transport_name,
    )

    await state.set_state(SearchStates.confirm)
    if callback.message is None or isinstance(
        callback.message, InaccessibleMessage
    ):
        return
    await callback.message.edit_text(
        confirm_text, reply_markup=get_confirm_keyboard(lang), parse_mode="Markdown"
    )


@router.callback_query(SearchStates.confirm, F.data.startswith("confirm:"))
async def process_confirm_selection(callback: CallbackQuery, state: FSMContext):
    if callback.data is None:
        return
    action = callback.data.split(":")[1]
    data = await state.get_data()
    lang = data.get("lang", "uz")

    if action == "cancel":
        await state.clear()
        if callback.message is None or isinstance(
            callback.message, InaccessibleMessage
        ):
            return
        await callback.message.edit_text(
            get_text("menu", lang), reply_markup=None
        )
        await callback.message.answer(
            get_text("menu", lang), reply_markup=get_main_menu(lang)
        )
        await callback.answer()
        return

    if action == "monitor":
        tg_id = callback.from_user.id
        origin_name = data.get("origin_name", "")
        destination_name = data.get("destination_name", "")
        train_dep_code = data.get("train_dep_code")
        train_arv_code = data.get("train_arv_code")
        bus_dep_id = data.get("bus_dep_id")
        bus_arv_id = data.get("bus_arv_id")
        date_str = data.get("date", "")
        transport_type = data.get("transport_type", "train")

        async with async_session() as session:
            # Ensure the user exists in the database to prevent ForeignKeyViolationError
            user_stmt = select(User).where(User.telegram_id == tg_id)
            user_res = await session.execute(user_stmt)
            db_user = user_res.scalar_one_or_none()
            if not db_user:
                db_user = User(
                    telegram_id=tg_id,
                    chat_id=callback.message.chat.id if callback.message else tg_id,
                    username=callback.from_user.username,
                    first_name=callback.from_user.first_name,
                    language_code=lang,
                )
                session.add(db_user)
                await session.flush()

            # Check subscription limit
            sub_type = db_user.subscription_type or "free"
            active_count_stmt = select(func.count(Subscription.id)).where(
                Subscription.user_id == tg_id,
                Subscription.is_active == True
            )
            active_count = (await session.execute(active_count_stmt)).scalar() or 0

            if sub_type == "free" and active_count >= 1:
                if callback.message is not None and not isinstance(callback.message, InaccessibleMessage):
                    await callback.message.edit_text(
                        get_text("limit_reached_free", lang, admin_username=settings.ADMIN_USERNAME),
                        reply_markup=None,
                        parse_mode="Markdown",
                    )
                await callback.answer()
                await state.clear()
                return

            if sub_type == "standard" and active_count >= 5:
                if callback.message is not None and not isinstance(callback.message, InaccessibleMessage):
                    await callback.message.edit_text(
                        get_text("limit_reached_standard", lang, admin_username=settings.ADMIN_USERNAME),
                        reply_markup=None,
                        parse_mode="Markdown",
                    )
                await callback.answer()
                await state.clear()
                return

            sub = Subscription(
                user_id=tg_id,
                origin_name=origin_name,
                destination_name=destination_name,
                train_dep_code=train_dep_code,
                train_arv_code=train_arv_code,
                bus_dep_id=bus_dep_id,
                bus_arv_id=bus_arv_id,
                date=date_str,
                transport_type=transport_type,
            )
            session.add(sub)
            await session.flush()

            state_record = SubscriptionState(subscription_id=sub.id)
            session.add(state_record)
            await session.commit()

        await state.clear()
        if callback.message is None or isinstance(
            callback.message, InaccessibleMessage
        ):
            return
        await callback.message.edit_text(
            get_text("monitoring_added", lang),
            reply_markup=None,
        )
        await callback.message.answer(
            get_text("menu", lang),
            reply_markup=get_main_menu(lang),
        )
        await callback.answer()
        return

    if action == "search":
        if callback.message is None or isinstance(
            callback.message, InaccessibleMessage
        ):
            return
        await callback.message.edit_text(
            "🔍 Qidirilmoqda..."
            if lang == "uz"
            else "🔍 Поиск..."
            if lang == "ru"
            else "🔍 Searching..."
        )
        await callback.answer()

        date_str = data.get("date", "")
        transport_type = data.get("transport_type", "train")
        train_dep = data.get("train_dep_code")
        train_arv = data.get("train_arv_code")
        bus_dep = data.get("bus_dep_id")
        bus_arv = data.get("bus_arv_id")

        results = []

        if transport_type == "train" and train_dep and train_arv:
            try:
                train_res = await fast_ticket_track(date_str, train_dep, train_arv)
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
                logger.error(f"Error checking trains in search handler: {e}")

        elif transport_type == "bus" and bus_dep and bus_arv:
            try:
                bus_res = await fetch_avtoticket_trips(date_str, int(bus_dep), int(bus_arv), 1)
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
                logger.error(f"Error checking buses in search handler: {e}")

        origin_name = data.get("origin_name", "")
        destination_name = data.get("destination_name", "")

        if transport_type == "train":
            buy_url = "https://eticket.railway.uz/uz/home"
        else:
            bus_dep = data.get("bus_dep_id")
            bus_arv = data.get("bus_arv_id")
            buy_url = f"https://avtoticket.uz/trips/{bus_dep}/{bus_arv}/{date_str}"

        if not results:
            transport_name = (
                "Poyezd 🚆" if transport_type == "train" else "Avtobus 🚌"
            )
            if lang == "ru":
                transport_name = "Поезд 🚆" if transport_type == "train" else "Автобус 🚌"
            elif lang == "en":
                transport_name = "Train 🚆" if transport_type == "train" else "Bus 🚌"

            await callback.message.edit_text(
                get_text(
                    "no_tickets_found",
                    lang,
                    origin=origin_name,
                    destination=destination_name,
                    date=date_str,
                    transport=transport_name,
                ),
                reply_markup=get_search_results_keyboard(lang, buy_url=buy_url),
                parse_mode="Markdown",
            )
        else:
            PAGE_SIZE = 10
            total_pages = (len(results) + PAGE_SIZE - 1) // PAGE_SIZE
            await state.update_data(search_results=results, current_page=1)

            formatted = format_search_results_page(results, 1, PAGE_SIZE)
            results_text = get_text(
                "search_results",
                lang,
                results=formatted,
                date=date_str,
                origin=origin_name,
                destination=destination_name,
            )
            if results:
                results_text += get_text("price_legend", lang)

            await callback.message.edit_text(
                results_text,
                reply_markup=get_search_results_keyboard(lang, 1, total_pages, buy_url=buy_url),
                parse_mode="Markdown",
            )


def format_search_results_page(results: list[str], page: int, page_size: int = 10) -> str:
    start = (page - 1) * page_size
    end = start + page_size
    page_results = results[start:end]
    return "\n\n".join(page_results)


@router.callback_query(F.data.startswith("search:page:"))
async def process_search_page_callback(callback: CallbackQuery, state: FSMContext):
    if callback.data is None:
        return
    action = callback.data.split(":")[2]
    data = await state.get_data()
    results = data.get("search_results")
    current_page = data.get("current_page", 1)
    lang = data.get("lang", "uz")

    if not results:
        await callback.answer(
            "Seans muddati tugadi." if lang == "uz" else "Сессия истекла." if lang == "ru" else "Session expired.",
            show_alert=True
        )
        return

    PAGE_SIZE = 10
    total_pages = (len(results) + PAGE_SIZE - 1) // PAGE_SIZE

    if action == "noop":
        await callback.answer()
        return

    if action == "prev":
        if current_page > 1:
            current_page -= 1
        else:
            await callback.answer()
            return
    elif action == "next":
        if current_page < total_pages:
            current_page += 1
        else:
            await callback.answer()
            return

    await state.update_data(current_page=current_page)
    formatted = format_search_results_page(results, current_page, PAGE_SIZE)

    if callback.message is None or isinstance(
        callback.message, InaccessibleMessage
    ):
        return

    transport_type = data.get("transport_type", "train")
    date_str = data.get("date", "")
    if transport_type == "train":
        buy_url = "https://eticket.railway.uz/uz/home"
    else:
        bus_dep = data.get("bus_dep_id")
        bus_arv = data.get("bus_arv_id")
        buy_url = f"https://avtoticket.uz/trips/{bus_dep}/{bus_arv}/{date_str}"

    results_text = get_text(
        "search_results",
        lang,
        results=formatted,
        date=date_str,
        origin=data.get("origin_name", ""),
        destination=data.get("destination_name", ""),
    )
    if results:
        results_text += get_text("price_legend", lang)

    await callback.message.edit_text(
        results_text,
        reply_markup=get_search_results_keyboard(lang, current_page, total_pages, buy_url=buy_url),
        parse_mode="Markdown",
    )
    await callback.answer()


# Global Cancel Handler
@router.callback_query(F.data == "search:cancel")
async def cancel_search_callback(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.clear()
    if callback.message is None or isinstance(
        callback.message, InaccessibleMessage
    ):
        return
    await callback.message.edit_text(
        get_text("menu", lang), reply_markup=None
    )
    await callback.message.answer(
        get_text("menu", lang), reply_markup=get_main_menu(lang)
    )
    await callback.answer()
