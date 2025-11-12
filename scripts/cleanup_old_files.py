#!/usr/bin/env python3
"""
Clean up old log files and scraped game files
"""
import os
from pathlib import Path
from datetime import datetime, timedelta

def cleanup_old_files():
    """Remove old log and scraped game files"""
    project_root = Path(__file__).parent.parent
    
    # Clean up old log files (older than 7 days)
    logs_dir = project_root / "logs"
    if logs_dir.exists():
        cutoff_date = datetime.now() - timedelta(days=7)
        log_files = list(logs_dir.glob("*.log"))
        removed_logs = 0
        for log_file in log_files:
            if datetime.fromtimestamp(log_file.stat().st_mtime) < cutoff_date:
                print(f"Removing old log: {log_file.name}")
                log_file.unlink()
                removed_logs += 1
        print(f"Removed {removed_logs} old log file(s)")
    
    # Clean up old scraped game files (older than 1 day, keep test files)
    raw_dir = project_root / "data" / "raw"
    if raw_dir.exists():
        cutoff_date = datetime.now() - timedelta(days=1)
        scraped_files = list(raw_dir.glob("scraped_games_*.jsonl"))
        removed_scraped = 0
        total_size_freed = 0
        
        for scraped_file in scraped_files:
            # Skip test files
            if "test" in scraped_file.name.lower() or "quick" in scraped_file.name.lower():
                continue
            
            file_time = datetime.fromtimestamp(scraped_file.stat().st_mtime)
            if file_time < cutoff_date:
                file_size = scraped_file.stat().st_size
                print(f"Removing old scraped file: {scraped_file.name} ({file_size / 1024 / 1024:.2f} MB)")
                scraped_file.unlink()
                removed_scraped += 1
                total_size_freed += file_size
        
        print(f"Removed {removed_scraped} old scraped file(s)")
        print(f"Freed {total_size_freed / 1024 / 1024:.2f} MB")
    
    print("\n✅ Cleanup complete!")

if __name__ == "__main__":
    cleanup_old_files()

