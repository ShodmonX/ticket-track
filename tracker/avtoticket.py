import httpx
import json
from datetime import datetime


async def fetch_avtoticket_trips(date: str, from_id: int, to_id: int, days: int = 3):
    url = "https://wapi.avtoticket.uz/api/api-trips"

    payload = {"date": date, "from": from_id, "to": to_id, "days": days}

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://avtoticket.uz",
        "Referer": "https://avtoticket.uz/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "uz-UZ,uz;q=0.9,ru;q=0.8,en;q=0.6",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()

    except httpx.HTTPStatusError as e:
        if e.response:
            print(f"❌ HTTP xato: {e.response.status_code} {e.response.reason_phrase}")
            print("Server javobi:", e.response.text[:500])
        return None

    except httpx.RequestError as e:
        print(f"❌ So'rov xatosi: {e}")
        return None


def fmt_time(dt_str: str) -> str:
    """'2026-06-22 08:45:00'  →  '08:45'"""
    try:
        return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").strftime("%H:%M")
    except Exception:
        return dt_str


def fmt_price(price) -> str:
    """115000  →  '115 000 so'm'"""
    try:
        return f"{int(price):,} so'm".replace(",", " ")
    except Exception:
        return str(price)


def print_trips(data):
    if not data or not data.get("success"):
        print("❌ API muvaffaqiyatsiz javob qaytardi.")
        return

    days = data.get("data", [])
    total = 0

    for day in days:
        trips = day.get("trips", [])
        if not trips:
            continue

        date_label = day.get("name", "—")
        print(f"\n📅 {date_label}  ({len(trips)} ta reys)")
        print("─" * 60)

        for trip in trips:
            dep      = fmt_time(trip.get("departure_at", ""))
            arr      = fmt_time(trip.get("arrive_at", ""))
            seats    = trip.get("seats", 0)
            sold     = trip.get("sold_seats", 0)
            free     = seats - sold
            price    = fmt_price(trip.get("price"))
            carrier  = trip.get("transporter_name", "—").strip().strip('"')
            bus      = trip.get("bus_model_name", "—")
            platform = trip.get("platform", "—")
            route    = trip.get("route_name_uz") or trip.get("route_name", "—")

            seat_icon = "🔴" if free <= 5 else "🟡" if free <= 15 else "🟢"

            print(
                f"  🕐 {dep} → {arr}  |  "
                f"{seat_icon} {free}/{seats} o'rin  |  "
                f"💰 {price}  |  "
                f"🚏 {platform}-peron"
            )
            print(f"     🚌 {bus}  |  🏢 {carrier}")
            print(f"     📍 {route}")
            print()

            total += 1

    print("─" * 60)
    print(f"✅ Jami: {total} ta reys topildi.")


if __name__ == "__main__":
    print("🔍 Reyslар qidirilmoqda...\n")

    result = fetch_avtoticket_trips(
        date="2026-06-22",
        from_id=1726,
        to_id=1710224,
        days=1
    )

    if result:
        print_trips(result)