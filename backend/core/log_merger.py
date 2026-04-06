"""
Utility for merging and sorting multiple log files by timestamp
"""
import re
from datetime import datetime
from typing import List, Tuple
from pathlib import Path


def parse_mock_log_timestamp(line: str) -> Tuple[datetime, str]:
    """
    Parse timestamp from Mock log line.
    
    Mock logs have various formats:
    - root.log: "INFO buildroot.py:667:  Mock Version: ..."
    - root.log: "DEBUG file_util.py:18:  ensuring that dir exists: ..."
    - build.log: "Mock Version: unreleased_version"
    
    Some lines have timestamps like:
    - "2024-01-15 10:23:45,123 INFO ..."
    
    Returns:
        tuple: (datetime object or None, original line)
    """
    # Try ISO format with milliseconds: 2024-01-15 10:23:45,123
    match = re.match(r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:,\d+)?)\s+(.*)$', line)
    if match:
        timestamp_str = match.group(1).replace(',', '.')
        try:
            dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f')
            return (dt, line)
        except ValueError:
            try:
                dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                return (dt, line)
            except ValueError:
                pass
    
    # No timestamp found - use None (will be sorted to beginning or by file order)
    return (None, line)


def merge_log_files(log_files: List[Tuple[str, str]], sort_by_time: bool = True) -> str:
    """
    Merge multiple log files with file name prefixes and optional time sorting.
    
    Args:
        log_files: List of tuples (filename, content)
        sort_by_time: If True, sort lines by timestamp (when available)
    
    Returns:
        Merged log content with each line prefixed by filename
        
    Example output:
        build.log - Mock Version: unreleased_version
        root.log - INFO buildroot.py:667:  Mock Version: unreleased_version
        root.log - DEBUG file_util.py:18:  ensuring that dir exists: /var/lib/mock/...
    """
    if not log_files:
        return ""
    
    # If only one log file, just prefix the lines
    if len(log_files) == 1:
        filename, content = log_files[0]
        if not content:
            return ""
        lines = content.splitlines()
        return '\n'.join(f"{filename} - {line}" for line in lines) + '\n'
    
    # Multiple log files - parse timestamps and merge
    all_lines = []
    
    for filename, content in log_files:
        if not content:
            continue
        
        for line in content.splitlines():
            timestamp, original_line = parse_mock_log_timestamp(line)
            all_lines.append({
                'timestamp': timestamp,
                'filename': filename,
                'line': original_line
            })
    
    if not all_lines:
        return ""
    
    # Sort by timestamp if requested
    if sort_by_time:
        # Lines with timestamps come first (sorted), then lines without timestamps (in original order)
        lines_with_time = [l for l in all_lines if l['timestamp'] is not None]
        lines_without_time = [l for l in all_lines if l['timestamp'] is None]
        
        lines_with_time.sort(key=lambda x: x['timestamp'])
        sorted_lines = lines_with_time + lines_without_time
    else:
        sorted_lines = all_lines
    
    # Format output with filename prefix
    result = '\n'.join(f"{line['filename']} - {line['line']}" for line in sorted_lines)
    return result + '\n' if result else ""


def merge_log_file_paths(log_file_paths: List[Path], sort_by_time: bool = True) -> str:
    """
    Convenience function to merge log files from Path objects.
    
    Args:
        log_file_paths: List of Path objects pointing to log files
        sort_by_time: If True, sort lines by timestamp (when available)
    
    Returns:
        Merged log content
    """
    log_files = []
    
    for path in log_file_paths:
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                    log_files.append((path.name, content))
            except Exception:
                # Skip files that can't be read
                pass
    
    return merge_log_files(log_files, sort_by_time=sort_by_time)
