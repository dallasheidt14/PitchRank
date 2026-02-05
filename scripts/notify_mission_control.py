#!/usr/bin/env python3
"""
notify_mission_control.py - Helper to notify Mission Control from agent sessions

This script provides a simple interface for OpenClaw agents to automatically
track their tasks in Mission Control's Task Board.

Usage from agent sessions:
    # At task start
    python3 scripts/notify_mission_control.py spawn "session-key-here" "codey" "Implementing feature X"
    
    # On progress update
    python3 scripts/notify_mission_control.py progress "session-key-here" "codey" "Progress update" --result "50% complete"
    
    # On completion
    python3 scripts/notify_mission_control.py complete "session-key-here" "codey" "Done" --result "Feature X implemented successfully"
    
    # On error
    python3 scripts/notify_mission_control.py error "session-key-here" "codey" "Failed" --error "Build failed: missing dependency"

Can also be used as a module:
    from scripts.notify_mission_control import notify_mission_control
    notify_mission_control('spawn', 'session-key', 'codey', 'Task description')
"""

import os
import sys
import argparse
import requests
from typing import Optional

# Default webhook URL - use environment variable or localhost for dev
WEBHOOK_URL = os.environ.get(
    'MISSION_CONTROL_WEBHOOK_URL',
    'http://localhost:3000/api/agent-webhook'
)

# Optional webhook secret for authentication
WEBHOOK_SECRET = os.environ.get('AGENT_WEBHOOK_SECRET', None)


def notify_mission_control(
    action: str,
    session_key: str,
    agent_name: str,
    task: str,
    result: Optional[str] = None,
    error: Optional[str] = None,
    webhook_url: Optional[str] = None,
    timeout: int = 10
) -> dict:
    """
    Notify Mission Control about agent task lifecycle events.
    
    Args:
        action: One of 'spawn', 'progress', 'complete', 'error'
        session_key: Unique session identifier (e.g., OpenClaw session key)
        agent_name: Name of the agent (e.g., 'codey', 'movy', 'watchy')
        task: Task description
        result: Optional result message (for progress/complete)
        error: Optional error message (for error action)
        webhook_url: Override default webhook URL
        timeout: Request timeout in seconds
        
    Returns:
        dict: Response from webhook with 'success', 'taskId', 'message' on success
              or 'error' on failure
    """
    url = webhook_url or WEBHOOK_URL
    
    payload = {
        'action': action,
        'sessionKey': session_key,
        'agentName': agent_name,
        'task': task,
    }
    
    if result:
        payload['result'] = result
    if error:
        payload['error'] = error
    
    headers = {'Content-Type': 'application/json'}
    
    # Add auth header if secret is configured
    if WEBHOOK_SECRET:
        headers['Authorization'] = f'Bearer {WEBHOOK_SECRET}'
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        return {'error': f'Could not connect to {url}. Is the frontend server running?'}
    except requests.exceptions.Timeout:
        return {'error': f'Request timed out after {timeout}s'}
    except requests.exceptions.HTTPError as e:
        try:
            return response.json()
        except:
            return {'error': str(e)}
    except Exception as e:
        return {'error': str(e)}


def main():
    parser = argparse.ArgumentParser(
        description='Notify Mission Control about agent task events',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start a new task
  %(prog)s spawn "session-123" "codey" "Implementing new feature"
  
  # Report progress
  %(prog)s progress "session-123" "codey" "Progress" --result "50%% complete"
  
  # Complete a task
  %(prog)s complete "session-123" "codey" "Task done" --result "Feature implemented"
  
  # Report an error
  %(prog)s error "session-123" "codey" "Task failed" --error "Build failed"

Environment Variables:
  MISSION_CONTROL_WEBHOOK_URL  Override webhook URL (default: http://localhost:3000/api/agent-webhook)
  AGENT_WEBHOOK_SECRET         Optional auth secret
        """
    )
    
    parser.add_argument(
        'action',
        choices=['spawn', 'progress', 'complete', 'error'],
        help='Action type'
    )
    parser.add_argument(
        'session_key',
        help='Unique session identifier'
    )
    parser.add_argument(
        'agent_name',
        help='Agent name (e.g., codey, movy, watchy)'
    )
    parser.add_argument(
        'task',
        help='Task description'
    )
    parser.add_argument(
        '--result',
        help='Result message (for progress/complete actions)'
    )
    parser.add_argument(
        '--error',
        help='Error message (for error action)'
    )
    parser.add_argument(
        '--url',
        help='Override webhook URL'
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Suppress output on success'
    )
    
    args = parser.parse_args()
    
    response = notify_mission_control(
        action=args.action,
        session_key=args.session_key,
        agent_name=args.agent_name,
        task=args.task,
        result=args.result,
        error=args.error,
        webhook_url=args.url
    )
    
    if 'error' in response:
        print(f"❌ Error: {response['error']}", file=sys.stderr)
        sys.exit(1)
    elif not args.quiet:
        print(f"✅ {response.get('message', 'Success')}")
        if 'taskId' in response:
            print(f"   Task ID: {response['taskId']}")
    
    sys.exit(0)


if __name__ == '__main__':
    main()
