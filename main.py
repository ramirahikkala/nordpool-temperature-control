"""
Temperature Control System - Main Entry Point.

This is the main entry point for the temperature control system.
It runs the control cycle on a schedule (every 15 minutes).

Usage:
    python main.py     # Runs scheduler with control cycle every 15 min
"""
import os
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import TIMEZONE
from control import run_control

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point - runs the scheduler."""
    # Get timezone
    tz = pytz.timezone(TIMEZONE)
    
    # Create scheduler
    scheduler = BlockingScheduler(timezone=tz)
    
    # Schedule to run at :00, :15, :30, :45 every hour
    scheduler.add_job(
        run_control,
        trigger=CronTrigger(minute='0,15,30,45', timezone=tz),
        id='temperature_control',
        name='Temperature Control',
        replace_existing=True
    )
    
    logger.info("Scheduler initialized. Will run at :00, :15, :30, :45 every hour.")
    logger.info(f"Timezone: {tz}")
    logger.info("Running initial control cycle now...")
    
    # Run once immediately at startup
    try:
        run_control()
    except Exception as e:
        logger.error(f"Error in initial control cycle: {e}", exc_info=True)
    
    # Start scheduler (blocks forever)
    logger.info("Starting scheduler... (this will block and keep the process running)")
    try:
        scheduler.start()
        logger.info("Scheduler stopped normally (should not reach here)")
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by signal.")
    except Exception as e:
        logger.error(f"Scheduler failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
