#!/usr/bin/env python3
"""
Test the log_merger utility
"""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / 'backend'))

from backend.core.log_merger import merge_log_files


def test_basic_merge():
    """Test basic log merging with filename prefixes"""
    log_files = [
        ('build.log', 'Mock Version: unreleased_version\nBuilding package...\n'),
        ('root.log', 'INFO buildroot.py:667:  Mock Version: unreleased_version\nDEBUG file_util.py:18:  ensuring that dir exists\n'),
    ]
    
    result = merge_log_files(log_files, sort_by_time=False)
    print("=== Test: Basic Merge (no sorting) ===")
    print(result)
    print()
    
    # Each line should be prefixed
    lines = result.strip().split('\n')
    assert len(lines) == 4
    assert lines[0].startswith('build.log - ')
    assert lines[1].startswith('build.log - ')
    assert lines[2].startswith('root.log - ')
    assert lines[3].startswith('root.log - ')
    print("✓ All lines correctly prefixed")
    print()


def test_time_sorting():
    """Test log merging with timestamp-based sorting"""
    log_files = [
        ('build.log', '2024-01-15 10:23:47,000 Building started\n2024-01-15 10:23:49,500 Build complete\n'),
        ('root.log', '2024-01-15 10:23:45,123 INFO Setting up environment\n2024-01-15 10:23:48,000 DEBUG Installing deps\n'),
    ]
    
    result = merge_log_files(log_files, sort_by_time=True)
    print("=== Test: Time-sorted Merge ===")
    print(result)
    print()
    
    # Lines should be sorted by timestamp
    lines = result.strip().split('\n')
    assert len(lines) == 4
    
    # Order should be: 10:23:45 (root), 10:23:47 (build), 10:23:48 (root), 10:23:49 (build)
    assert 'root.log' in lines[0] and '10:23:45' in lines[0]
    assert 'build.log' in lines[1] and '10:23:47' in lines[1]
    assert 'root.log' in lines[2] and '10:23:48' in lines[2]
    assert 'build.log' in lines[3] and '10:23:49' in lines[3]
    print("✓ Lines correctly sorted by timestamp")
    print()


def test_mixed_timestamps():
    """Test log merging with some lines having timestamps and some not"""
    log_files = [
        ('build.log', 'Mock Version: unreleased_version\n2024-01-15 10:23:47 Building\nDone\n'),
        ('root.log', '2024-01-15 10:23:45 INFO Setup\nPlain log line\n'),
    ]
    
    result = merge_log_files(log_files, sort_by_time=True)
    print("=== Test: Mixed timestamps ===")
    print(result)
    print()
    
    lines = result.strip().split('\n')
    assert len(lines) == 5
    
    # Timestamped lines should come first (sorted), then non-timestamped in original order
    # First timestamped: 10:23:45 (root)
    # Second timestamped: 10:23:47 (build)
    # Then non-timestamped in order: Mock Version, Done, Plain log line
    assert '10:23:45' in lines[0]
    assert '10:23:47' in lines[1]
    print("✓ Timestamped lines sorted first, non-timestamped after")
    print()


def test_single_file():
    """Test with a single log file"""
    log_files = [
        ('build.log', 'Line 1\nLine 2\nLine 3\n'),
    ]
    
    result = merge_log_files(log_files)
    print("=== Test: Single file ===")
    print(result)
    print()
    
    lines = result.strip().split('\n')
    assert len(lines) == 3
    assert all(line.startswith('build.log - ') for line in lines)
    print("✓ Single file correctly prefixed")
    print()


def test_empty_content():
    """Test with empty log content"""
    log_files = [
        ('build.log', ''),
        ('root.log', 'Some content\n'),
    ]
    
    result = merge_log_files(log_files)
    print("=== Test: Empty content ===")
    print(result)
    print()
    
    lines = result.strip().split('\n')
    assert len(lines) == 1
    assert lines[0].startswith('root.log - ')
    print("✓ Empty files handled correctly")
    print()


if __name__ == '__main__':
    print("Testing log_merger utility\n")
    print("=" * 60)
    print()
    
    test_basic_merge()
    test_time_sorting()
    test_mixed_timestamps()
    test_single_file()
    test_empty_content()
    
    print("=" * 60)
    print("\n✅ All tests passed!")
