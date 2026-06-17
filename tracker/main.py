import asyncio
import logging

from tracker.scheduler import start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("tracker")


async def main():
    logger.info("Starting Ticket Tracking Background Worker Process...")
    await start_scheduler()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Ticket Tracking Background Worker stopped.")
    except Exception as e:
        logger.exception(e)
