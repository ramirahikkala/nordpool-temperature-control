"""Local file-based logging for heating decisions with rotation.

Stores decisions as JSONL (one JSON per line) with automatic rotation:
- Keeps today's and yesterday's logs
- Rotates at midnight (00:00)
- File: data/heating_decisions.jsonl
"""

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Data directory
DATA_DIR = Path(__file__).parent / "data"
DECISIONS_LOG_FILE = DATA_DIR / "heating_decisions.jsonl"

def ensure_data_dir():
    """Create data directory if it doesn't exist."""
    DATA_DIR.mkdir(exist_ok=True)

def rotate_old_logs():
    """Remove decisions older than 2 days (keep today + yesterday)."""
    if not DECISIONS_LOG_FILE.exists():
        return
    
    try:
        tz = ZoneInfo("Europe/Helsinki")
        now = datetime.now(tz)
        two_days_ago = now.replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_timestamp = two_days_ago.isoformat()
        
        # Read all entries
        entries = []
        with open(DECISIONS_LOG_FILE, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        # Keep if timestamp is >= 2 days ago
                        if entry.get('timestamp', '') >= cutoff_timestamp:
                            entries.append(entry)
                    except json.JSONDecodeError:
                        pass
        
        # Write back only recent entries
        with open(DECISIONS_LOG_FILE, 'w') as f:
            for entry in entries:
                f.write(json.dumps(entry) + '\n')
    except Exception as e:
        print(f"Warning: Could not rotate logs: {e}")

def log_heating_decision(should_run, reason, current_price):
    """Log a heating decision to local file.
    
    Args:
        should_run: True if heating should run, False if blocked
        reason: Reason for the decision
        current_price: Current electricity price in c/kWh
    """
    ensure_data_dir()
    
    decision = "HEAT" if should_run else "BLOCK"
    tz = ZoneInfo("Europe/Helsinki")
    now = datetime.now(tz)
    
    entry = {
        "timestamp": now.isoformat(),
        "decision": decision,
        "price": round(current_price, 2),
        "reason": reason[:100]  # Truncate reason
    }
    
    try:
        # Append to log file
        with open(DECISIONS_LOG_FILE, 'a') as f:
            f.write(json.dumps(entry) + '\n')
        
        # Rotate old logs
        rotate_old_logs()
    except Exception as e:
        print(f"Error writing decision log: {e}")

def get_decisions(limit=None):
    """Get all logged decisions (most recent first).
    
    Args:
        limit: Maximum number of entries to return (None = all)
    
    Returns:
        List of decision entries (dicts with timestamp, decision, price, reason)
    """
    if not DECISIONS_LOG_FILE.exists():
        return []
    
    entries = []
    try:
        with open(DECISIONS_LOG_FILE, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        entries.append(entry)
                    except json.JSONDecodeError:
                        pass
    except Exception as e:
        print(f"Error reading decision log: {e}")
    
    # Return most recent first
    entries.reverse()
    
    if limit:
        return entries[:limit]
    return entries

def get_decisions_by_date(date_str=None):
    """Get decisions for a specific date.
    
    Args:
        date_str: Date in format YYYY-MM-DD (None = today)
    
    Returns:
        List of decisions for that date
    """
    if not DECISIONS_LOG_FILE.exists():
        return []
    
    if date_str is None:
        tz = ZoneInfo("Europe/Helsinki")
        date_str = datetime.now(tz).strftime("%Y-%m-%d")
    
    entries = []
    try:
        with open(DECISIONS_LOG_FILE, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        # Check if timestamp is from the requested date
                        ts = entry.get('timestamp', '')
                        if ts.startswith(date_str):
                            entries.append(entry)
                    except json.JSONDecodeError:
                        pass
    except Exception as e:
        print(f"Error reading decision log: {e}")
    
    return entries

def clear_all_logs():
    """Clear all logged decisions (for testing/reset)."""
    try:
        if DECISIONS_LOG_FILE.exists():
            DECISIONS_LOG_FILE.unlink()
    except Exception as e:
        print(f"Error clearing logs: {e}")
