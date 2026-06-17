import httpx
from urllib.parse import unquote
import json
import asyncio
import logging
from bot.core.config import settings

logger = logging.getLogger("tracker")

async def send_admin_alert(message: str):
    """Sends a critical warning message to the admin via Telegram API."""
    try:
        url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": settings.ADMIN_ID,
            "text": f"⚠️ *CRITICAL ALERT: Tracker Error*\n\n{message}",
            "parse_mode": "Markdown"
        }
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(url, json=payload)
            if res.status_code != 200:
                logger.error(f"Telegram Admin alert failed: {res.status_code} {res.text}")
    except Exception as e:
        logger.error(f"Failed to send admin alert: {e}")

async def fast_ticket_track(date, dep_code, arv_code):
    """
    Fetches train tickets using pure HTTP requests.
    Retries with exponential backoff on failure and alerts the admin if blocked.
    """
    url = "https://eticket.railway.uz/uz/home"
    search_url = f"https://eticket.railway.uz/uz/trains-list?date={date}&stationFrom={dep_code}&stationTo={arv_code}"
    api_url = "https://eticket.railway.uz/api/v3/handbook/trains/list"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "uz-UZ,uz;q=0.9,ru;q=0.8,en-US;q=0.7,en;q=0.6"
    }
    
    max_retries = 3
    backoff = 2
    
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Attempt {attempt}/{max_retries} to fetch trains for {dep_code}->{arv_code} on {date}")
            
            async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=15) as client:
                # 1. Establish session
                await client.get(url)
                
                # 2. Get CSRF Token
                r_csrf = await client.get("https://eticket.railway.uz/api/v1/csrf-token")
                if r_csrf.status_code != 200:
                    raise httpx.HTTPStatusError(
                        message=f"CSRF token returned status {r_csrf.status_code}",
                        request=r_csrf.request,
                        response=r_csrf
                    )
                
                xsrf_token = client.cookies.get("XSRF-TOKEN")
                if not xsrf_token:
                    raise ValueError("XSRF-TOKEN cookie not found in response")
                
                decoded_xsrf = unquote(xsrf_token)
                
                # 3. Fetch API data
                payload = {
                    "directions": {
                        "forward": {
                            "date": date,
                            "depStationCode": dep_code,
                            "arvStationCode": arv_code
                        }
                    }
                }
                
                api_headers = {
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                    "X-XSRF-TOKEN": decoded_xsrf,
                    "Origin": "https://eticket.railway.uz",
                    "Referer": search_url,
                    "Accept-Language": "uz-UZ,uz;q=0.9,ru;q=0.8,en-US;q=0.7,en;q=0.6"
                }
                
                r = await client.post(api_url, json=payload, headers=api_headers)
                
                if r.status_code == 429:
                    logger.warning(f"Rate limited (429) on attempt {attempt}")
                    if attempt == max_retries:
                        await send_admin_alert(f"Rate limited (429 Too Many Requests) by eticket.railway.uz on route `{dep_code} ➔ {arv_code}` for `{date}`.")
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                elif r.status_code == 403:
                    logger.warning(f"Access forbidden (403) on attempt {attempt}")
                    if attempt == max_retries:
                        await send_admin_alert(f"Access Forbidden (403) by eticket.railway.uz. IP may be blocked or Cloudflare challenge active on route `{dep_code} ➔ {arv_code}` for `{date}`.")
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                
                r.raise_for_status()
                
                logger.info("Successfully fetched train data.")
                return r.json()
                
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.error(f"Error on attempt {attempt} for {dep_code}->{arv_code}: {e}")
            if attempt == max_retries:
                await send_admin_alert(f"Failed to fetch train data after {max_retries} attempts on route `{dep_code} ➔ {arv_code}` for `{date}`.\nError: `{e}`")
            await asyncio.sleep(backoff)
            backoff *= 2
            
    return None