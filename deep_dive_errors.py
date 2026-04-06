#!/usr/bin/env python3
"""
Deep dive analysis - look at actual error messages in %build failures
"""
import sqlite3
import re

conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()

# Get packages with %build failures
cursor.execute("""
    SELECT name, build_log
    FROM packages 
    WHERE project_id = 10 
    AND build_status = 'failed'
    AND build_log LIKE '%Bad exit status from%(%build)%'
    LIMIT 20
""")

packages = cursor.fetchall()

print(f"Analyzing {len(packages)} packages with %build failures...")
print("=" * 80)

for name, log in packages:
    print(f"\n{'='*80}")
    print(f"Package: {name}")
    print('='*80)
    
    # Extract the actual error before "Bad exit status"
    # Look for the error context
    lines = log.split('\n')
    
    # Find "Bad exit status" line
    for i, line in enumerate(lines):
        if 'Bad exit status from' in line and '%build' in line:
            # Print 30 lines before the error
            start = max(0, i - 30)
            context_lines = lines[start:i+1]
            
            # Filter out just compilation/build output, focus on errors
            error_context = []
            for ctx_line in context_lines:
                if any(keyword in ctx_line for keyword in ['error:', 'Error:', 'ERROR:', 'failed', 'Fehler:', 'cannot find', 'No such file', 'ModuleNotFoundError', 'ImportError', 'SyntaxError']):
                    error_context.append(ctx_line.strip())
            
            if error_context:
                print("\nError context:")
                for err_line in error_context[-10:]:  # Last 10 error-related lines
                    print(f"  {err_line}")
            break
    
    print()

conn.close()
