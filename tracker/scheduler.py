import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.core.config import settings
from shared.database import async_session
from shared.models import Subscription, SubscriptionState, User
from shared.translations import get_text, format_car_class
from tracker.railway import fast_ticket_track
from tracker.avtoticket import fetch_avtoticket_trips

logger = logging.getLogger("tracker")
bot = Bot(token=settings.BOT_TOKEN)

CHECK_INTERVAL = 600  # 10 minutes in seconds


def parse_train_data(train_res) -> dict:
    """Parses train response JSON into a standard dict: {train_key: {seats: {class: {seats, price}}}}"""
    trains_dict = {}
    if not train_res or not train_res.get("data") or not train_res["data"].get("directions"):
        return trains_dict

    fwd = train_res["data"]["directions"].get("forward", {})
    trains = fwd.get("trains", [])
    for t in trains:
        num = t.get("number", "")
        dep = t.get("departureDate", "").split()[-1]
        arr = t.get("arrivalDate", "").split()[-1]
        brand = t.get("brand")
        key = f"{num}_{dep}"
        
        seats = {}
        for car in t.get("cars", []):
            c_type = car.get("type", "")
            for tariff in car.get("tariffs", []):
                st = tariff.get("classServiceType", "")
                free = tariff.get("freeSeats", 0) or car.get("freeSeats", 0)
                price = int(tariff.get("tariff", 0))
                
                class_key = f"{c_type}_{st}"
                if free > 0:
                    seats[class_key] = {"seats": free, "price": price, "type": c_type, "service_type": st}
                
        trains_dict[key] = {
            "number": num,
            "dep_time": dep,
            "arr_time": arr,
            "brand": brand,
            "origin_route": t.get("originRoute"),
            "seats": seats
        }
    return trains_dict


def parse_bus_data(bus_res) -> dict:
    """Parses bus response JSON into a standard dict: {trip_key: {seats, price, carrier}}"""
    buses_dict = {}
    if not bus_res or not bus_res.get("success") or not bus_res.get("data"):
        return buses_dict

    for day in bus_res["data"]:
        for trip in day.get("trips", []):
            dep = trip.get("departure_at", "").split()[-1][:5]
            arr = trip.get("arrive_at", "").split()[-1][:5]
            seats = trip.get("seats", 0)
            sold = trip.get("sold_seats", 0)
            free = seats - sold
            price = int(trip.get("price", 0))
            carrier = trip.get("transporter_name", "").strip().strip('"')
            key = f"{dep}_{carrier}"
            
            if free > 0:
                buses_dict[key] = {
                    "dep_time": dep,
                    "arr_time": arr,
                    "seats": free,
                    "price": price,
                    "carrier": carrier
                }
    return buses_dict


def compare_states(prev: dict, curr: dict, user_lang: str = "uz") -> tuple[list[str], list[str], list[str]]:
    """Compares previous and current states, returning (appeared, decreasing, disappeared) alerts."""
    appeared = []
    decreasing = []
    disappeared = []

    prev_trains = prev.get("trains", {})
    curr_trains = curr.get("trains", {})
    prev_buses = prev.get("buses", {})
    curr_buses = curr.get("buses", {})

    def get_train_display_name(t) -> str:
        num = t.get("number", "")
        brand = t.get("brand")
        origin_route = t.get("origin_route")
        if brand and brand not in ["Пассажирский", "Скорый", "Tezyurar", "Tezkor", "Passenger", "Fast"]:
            train_name = brand
        elif origin_route and origin_route.get("depStationName") and origin_route.get("arvStationName"):
            dep_station = origin_route.get("depStationName").strip().title()
            arv_station = origin_route.get("arvStationName").strip().title()
            if "Markaziy" in arv_station: arv_station = arv_station.replace("Markaziy", "").strip()
            if "Yuzhny" in arv_station: arv_station = arv_station.replace("Yuzhny", "").strip()
            if "Южный" in arv_station: arv_station = arv_station.replace("Южный", "").strip()
            if "Центральный" in arv_station: arv_station = arv_station.replace("Центральный", "").strip()
            if "Markaziy" in dep_station: dep_station = dep_station.replace("Markaziy", "").strip()
            if "Yuzhny" in dep_station: dep_station = dep_station.replace("Yuzhny", "").strip()
            if "Южный" in dep_station: dep_station = dep_station.replace("Южный", "").strip()
            if "Центральный" in dep_station: dep_station = dep_station.replace("Центральный", "").strip()
            train_name = f"{dep_station} — {arv_station}"
        else:
            train_name = brand or get_text("lbl_train", user_lang)
        return f"{num} «{train_name}»"

    # Compare Trains
    for key, curr_t in curr_trains.items():
        num = curr_t["number"]
        dep = curr_t["dep_time"]
        arr = curr_t.get("arr_time", "")
        train_title = get_train_display_name(curr_t)
        header = f"🚆 {train_title} | 🕒 `{dep}` ➔ `{arr}`"

        t_appeared_lines = []
        t_decreasing_lines = []

        curr_seats = curr_t.get("seats", {})
        prev_seats = prev_trains.get(key, {}).get("seats", {}) if key in prev_trains else {}

        for c_key, curr_s in curr_seats.items():
            # Safe dict fallback for legacy records
            c_type = curr_s.get("type", c_key.split("_")[0] if "_" in c_key else c_key)
            st = curr_s.get("service_type", c_key.split("_")[1] if "_" in c_key else "")
            c_display = format_car_class(c_type, st, user_lang)
            
            free = curr_s.get("seats", 0)
            price_val = curr_s.get("price")
            from shared.translations import format_price_k
            price_str = format_price_k(price_val)

            if c_key not in prev_seats:
                t_appeared_lines.append(f"  🔹 {c_display}: `{free}` {get_text('lbl_seat_count', user_lang)} — {price_str}")
            else:
                prev_s = prev_seats[c_key]
                # Safe .get() fallback for legacy data structures
                prev_free = prev_s.get("seats", 0) if isinstance(prev_s, dict) else 0
                if free > prev_free:
                    t_appeared_lines.append(f"  🔹 {c_display}: `{free}` {get_text('lbl_seat_count', user_lang)} — {price_str}")
                elif free < prev_free:
                    t_decreasing_lines.append(f"  🔹 {c_display}: `{prev_free}` ➔ `{free}` {get_text('lbl_seat_count', user_lang)}")

        if t_appeared_lines:
            appeared.append(f"{header}\n" + "\n".join(t_appeared_lines))
        if t_decreasing_lines:
            decreasing.append(f"{header}\n" + "\n".join(t_decreasing_lines))

    # Check for train seats that disappeared
    for key, prev_t in prev_trains.items():
        num = prev_t["number"]
        dep = prev_t["dep_time"]
        arr = prev_t.get("arr_time", "")
        train_title = get_train_display_name(prev_t)
        header = f"🚆 {train_title} | 🕒 `{dep}` ➔ `{arr}`"

        t_disappeared_lines = []

        if key not in curr_trains:
            for c_key, prev_s in prev_t.get("seats", {}).items():
                c_type = prev_s.get("type", c_key.split("_")[0] if "_" in c_key else c_key) if isinstance(prev_s, dict) else c_key.split("_")[0]
                st = prev_s.get("service_type", c_key.split("_")[1] if "_" in c_key else "") if isinstance(prev_s, dict) else ""
                c_display = format_car_class(c_type, st, user_lang)
                t_disappeared_lines.append(f"  🔹 {c_display}: {get_text('lbl_seats', user_lang).lower()} tugadi" if user_lang == "uz" else f"  🔹 {c_display}: мест нет" if user_lang == "ru" else f"  🔹 {c_display}: sold out")
        else:
            curr_t = curr_trains[key]
            curr_seats = curr_t.get("seats", {})
            for c_key, prev_s in prev_t.get("seats", {}).items():
                if c_key not in curr_seats:
                    c_type = prev_s.get("type", c_key.split("_")[0] if "_" in c_key else c_key) if isinstance(prev_s, dict) else c_key.split("_")[0]
                    st = prev_s.get("service_type", c_key.split("_")[1] if "_" in c_key else "") if isinstance(prev_s, dict) else ""
                    c_display = format_car_class(c_type, st, user_lang)
                    t_disappeared_lines.append(f"  🔹 {c_display}: {get_text('lbl_seats', user_lang).lower()} tugadi" if user_lang == "uz" else f"  🔹 {c_display}: мест нет" if user_lang == "ru" else f"  🔹 {c_display}: sold out")

        if t_disappeared_lines:
            disappeared.append(f"{header}\n" + "\n".join(t_disappeared_lines))

    # Compare Buses
    for key, curr_b in curr_buses.items():
        dep = curr_b["dep_time"]
        arr = curr_b.get("arr_time", "")
        carrier = curr_b["carrier"]
        header = f"🚌 «{carrier}» | 🕒 `{dep}` ➔ `{arr}`"
        
        free = curr_b["seats"]
        price_val = curr_b["price"]
        from shared.translations import format_price_k
        price_str = format_price_k(price_val)

        if key not in prev_buses:
            appeared.append(
                f"{header}\n  🔹 {get_text('lbl_seats', user_lang)}: `{free}` o'rin — {price_str}" if user_lang == "uz"
                else f"{header}\n  🔹 {get_text('lbl_seats', user_lang)}: `{free}` мест — {price_str}"
            )
        else:
            prev_b = prev_buses[key]
            prev_free = prev_b["seats"]
            if free > prev_free:
                appeared.append(
                    f"{header}\n  🔹 {get_text('lbl_seats', user_lang)}: `{free}` o'rin — {price_str}" if user_lang == "uz"
                    else f"{header}\n  🔹 {get_text('lbl_seats', user_lang)}: `{free}` мест — {price_str}"
                )
            elif free < prev_free:
                decreasing.append(
                    f"{header}\n  🔹 {get_text('lbl_seats', user_lang)}: `{prev_free}` ➔ `{free}` o'rin" if user_lang == "uz"
                    else f"{header}\n  🔹 {get_text('lbl_seats', user_lang)}: `{prev_free}` ➔ `{free}` мест"
                )

    # Check for bus trips that disappeared
    for key, prev_b in prev_buses.items():
        dep = prev_b["dep_time"]
        arr = prev_b.get("arr_time", "")
        carrier = prev_b["carrier"]
        header = f"🚌 «{carrier}» | 🕒 `{dep}` ➔ `{arr}`"
        if key not in curr_buses:
            disappeared.append(
                f"{header}\n  🔹 {get_text('lbl_seats', user_lang)}: tugadi" if user_lang == "uz"
                else f"{header}\n  🔹 {get_text('lbl_seats', user_lang)}: мест нет"
            )

    return appeared, decreasing, disappeared


def get_disable_keyboard(sub_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=get_text("btn_disable_monitoring", lang),
        callback_data=f"track:delete:{sub_id}"
    )
    return builder.as_markup()


async def check_all_active_subscriptions():
    """Fetches and runs checks for all active subscriptions, grouped by query to avoid duplicate API requests."""
    logger.info("Starting checks for all active subscriptions...")
    
    import datetime
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    uz_now = utc_now + datetime.timedelta(hours=5)
    uz_today_str = uz_now.strftime("%Y-%m-%d")

    async with async_session() as session:
        # 1. Find and deactivate expired subscriptions
        stmt_expired = (
            select(Subscription)
            .where(Subscription.is_active == True)
            .where(Subscription.date < uz_today_str)
        )
        res_expired = await session.execute(stmt_expired)
        expired_subs = res_expired.scalars().all()
        if expired_subs:
            for sub in expired_subs:
                logger.info(f"Auto-deactivating expired subscription {sub.id}: {sub.origin_name} -> {sub.destination_name} on {sub.date}")
                sub.is_active = False
            await session.commit()

        # 2. Fetch active subscriptions with joined User and SubscriptionState
        stmt = (
            select(Subscription)
            .where(Subscription.is_active == True)
            .options(
                joinedload(Subscription.user),
                joinedload(Subscription.state)
            )
        )
        res = await session.execute(stmt)
        subs = list(res.scalars().all())

    if not subs:
        logger.info("No active subscriptions to check.")
        return

    # 3. Extract unique train and bus queries to prevent duplicate fetching
    train_queries = set()
    bus_queries = set()
    for sub in subs:
        if (sub.transport_type == "train" or sub.transport_type == "both") and sub.train_dep_code and sub.train_arv_code:
            train_queries.add((sub.date, sub.train_dep_code, sub.train_arv_code))
        if (sub.transport_type == "bus" or sub.transport_type == "both") and sub.bus_dep_id and sub.bus_arv_id:
            bus_queries.add((sub.date, sub.bus_dep_id, sub.bus_arv_id))

    # 4. Fetch unique train queries
    train_results = {}
    for date, dep, arv in train_queries:
        logger.info(f"Fetching trains once for: {dep} -> {arv} on {date}")
        try:
            res = await fast_ticket_track(date, dep, arv)
            if res is not None:
                train_results[(date, dep, arv)] = parse_train_data(res)
            else:
                train_results[(date, dep, arv)] = None
        except Exception as e:
            logger.error(f"Error fetching trains for {dep}->{arv} on {date}: {e}")
            train_results[(date, dep, arv)] = None

    # 5. Fetch unique bus queries
    bus_results = {}
    for date, dep, arv in bus_queries:
        logger.info(f"Fetching buses once for: {dep} -> {arv} on {date}")
        try:
            res = await fetch_avtoticket_trips(date, int(dep), int(arv), 1)
            if res is not None:
                bus_results[(date, dep, arv)] = parse_bus_data(res)
            else:
                bus_results[(date, dep, arv)] = None
        except Exception as e:
            logger.error(f"Error fetching buses for {dep}->{arv} on {date}: {e}")
            bus_results[(date, dep, arv)] = None

    # 6. Distribute results and check updates for each subscription
    for sub in subs:
        state_record = sub.state
        if not state_record:
            continue

        user_lang = sub.user.language_code if sub.user else "uz"
        prev_state = state_record.last_state or {"trains": {}, "buses": {}}
        curr_state = {"trains": {}, "buses": {}}

        # Train check state assembly
        if (sub.transport_type == "train" or sub.transport_type == "both") and sub.train_dep_code and sub.train_arv_code:
            train_res = train_results.get((sub.date, sub.train_dep_code, sub.train_arv_code))
            if train_res is not None:
                curr_state["trains"] = train_res
            else:
                curr_state["trains"] = prev_state.get("trains", {})

        # Bus check state assembly
        if (sub.transport_type == "bus" or sub.transport_type == "both") and sub.bus_dep_id and sub.bus_arv_id:
            bus_res = bus_results.get((sub.date, sub.bus_dep_id, sub.bus_arv_id))
            if bus_res is not None:
                curr_state["buses"] = bus_res
            else:
                curr_state["buses"] = prev_state.get("buses", {})

        # State comparison
        appeared, decreasing, disappeared = compare_states(prev_state, curr_state, user_lang)
        has_previous_data = state_record.last_state is not None

        # Send alerts if changed
        if has_previous_data:
            if appeared:
                details = "\n\n".join(appeared)
                text = get_text(
                    "alert_appeared",
                    lang=user_lang,
                    origin=sub.origin_name,
                    destination=sub.destination_name,
                    date=sub.date,
                    details=details
                )
                try:
                    await bot.send_message(sub.user_id, text, reply_markup=get_disable_keyboard(sub.id, user_lang), parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Failed to send alert to user {sub.user_id}: {e}")

            if decreasing:
                details = "\n\n".join(decreasing)
                text = get_text(
                    "alert_decreasing",
                    lang=user_lang,
                    origin=sub.origin_name,
                    destination=sub.destination_name,
                    date=sub.date,
                    details=details
                )
                try:
                    await bot.send_message(sub.user_id, text, reply_markup=get_disable_keyboard(sub.id, user_lang), parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Failed to send alert to user {sub.user_id}: {e}")

            if disappeared:
                text = get_text(
                    "alert_disappeared",
                    lang=user_lang,
                    origin=sub.origin_name,
                    destination=sub.destination_name,
                    date=sub.date
                )
                try:
                    await bot.send_message(sub.user_id, text, reply_markup=get_disable_keyboard(sub.id, user_lang), parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Failed to send alert to user {sub.user_id}: {e}")

        # Save the current state in database
        try:
            async with async_session() as session:
                stmt_state = select(SubscriptionState).where(SubscriptionState.subscription_id == sub.id)
                res_state = await session.execute(stmt_state)
                state_db = res_state.scalar_one_or_none()
                if state_db:
                    state_db.last_state = curr_state
                    await session.commit()
        except Exception as e:
            logger.error(f"Error saving state for sub {sub.id}: {e}")
                
    logger.info("Finished checks for all subscriptions.")


async def start_scheduler():
    """Infinite loop checking subscriptions every 10 minutes."""
    logger.info(f"Scheduler started. Checking every {CHECK_INTERVAL // 60} minutes.")
    while True:
        try:
            await check_all_active_subscriptions()
        except Exception as e:
            logger.error(f"Error in scheduler main loop: {e}")
        await asyncio.sleep(CHECK_INTERVAL)
