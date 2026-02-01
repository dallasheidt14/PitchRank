#!/usr/bin/env python3
"""
COMPY Review - Extract learnings from recent agent sessions

This script is called by COMPY to review session transcripts and
prepare a summary for knowledge extraction.

Run: python3 scripts/compy_review.py [--hours 24] [--output summary]
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Session logs location (Moltbot default)
SESSIONS_DIR = Path.home() / '.clawdbot' / 'agents' / 'main' / 'sessions'
# Alternative location
ALT_SESSIONS_DIR = Path.home() / '.openclaw' / 'agents' / 'main' / 'sessions'

def find_sessions_dir():
    """Find the sessions directory."""
    if SESSIONS_DIR.exists():
        return SESSIONS_DIR
    if ALT_SESSIONS_DIR.exists():
        return ALT_SESSIONS_DIR
    return None


def get_recent_sessions(hours: int = 24):
    """Get session files modified in the last N hours."""
    sessions_dir = find_sessions_dir()
    if not sessions_dir:
        print("❌ Sessions directory not found")
        return []
    
    cutoff = datetime.now() - timedelta(hours=hours)
    recent = []
    
    for session_file in sessions_dir.glob('*.jsonl'):
        mtime = datetime.fromtimestamp(session_file.stat().st_mtime)
        if mtime > cutoff:
            recent.append({
                'path': session_file,
                'modified': mtime,
                'size': session_file.stat().st_size
            })
    
    return sorted(recent, key=lambda x: x['modified'], reverse=True)


def parse_session(session_path: Path):
    """Parse a session JSONL file and extract key information.
    
    Moltbot JSONL format:
    - Top level: {"type": "message", "message": {...}}
    - message.role: "user" or "assistant"
    - message.content[]: array with types "text", "toolCall", "thinking"
    - message.errorMessage: error string if present
    """
    messages = []
    tools_used = set()
    errors = []
    user_messages = []
    
    try:
        with open(session_path, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    
                    # Skip non-message entries
                    if entry.get('type') != 'message':
                        continue
                    
                    msg = entry.get('message', {})
                    role = msg.get('role')
                    content = msg.get('content', [])
                    
                    # Extract user messages for context
                    if role == 'user' and isinstance(content, list):
                        for item in content:
                            if item.get('type') == 'text':
                                text = item.get('text', '')
                                # Strip Telegram prefix for cleaner text
                                if '[message_id:' in text:
                                    text = text.split(']', 2)[-1].strip() if text.count(']') >= 2 else text
                                user_messages.append(text[:300])
                    
                    # Extract assistant messages
                    if role == 'assistant' and isinstance(content, list):
                        for item in content:
                            if item.get('type') == 'text':
                                messages.append(item.get('text', '')[:500])
                            elif item.get('type') == 'toolCall':
                                tools_used.add(item.get('name', 'unknown'))
                    
                    # Check for errors
                    if msg.get('errorMessage'):
                        errors.append(msg.get('errorMessage'))
                        
                except json.JSONDecodeError:
                    continue
                    
    except Exception as e:
        return {'error': str(e)}
    
    return {
        'message_count': len(messages),
        'user_message_count': len(user_messages),
        'tools_used': list(tools_used),
        'errors': errors,
        'sample_messages': messages[:5],  # First 5 assistant messages
        'sample_user_messages': user_messages[:10]  # First 10 user messages for context
    }


def identify_agent(session_path: Path, parsed: dict):
    """Try to identify which agent this session belongs to."""
    # Check tools used
    tools = set(parsed.get('tools_used', []))
    
    # Check for agent patterns in messages (both assistant and user)
    messages = ' '.join(parsed.get('sample_messages', []))
    user_msgs = ' '.join(parsed.get('sample_user_messages', []))
    all_text = f"{messages} {user_msgs}".lower()
    
    if 'run_weekly_cleany' in all_text or 'cleany' in all_text:
        return 'Cleany'
    if 'scrappy_monitor' in all_text or 'scrappy' in all_text:
        return 'Scrappy'
    if 'watchy_health' in all_text or 'watchy' in all_text:
        return 'Watchy'
    if 'movy_report' in all_text or 'movy' in all_text:
        return 'Movy'
    if 'compy' in all_text:
        return 'Compy'
    if 'codey' in all_text:
        return 'Codey'
    
    # Check for main session indicators
    if parsed.get('user_message_count', 0) > 20 or 'telegram' in all_text:
        return 'Main'
    
    return 'Unknown'


def generate_summary(sessions: list):
    """Generate a summary of recent sessions for COMPY to analyze."""
    summary = {
        'review_time': datetime.now().isoformat(),
        'sessions_reviewed': len(sessions),
        'by_agent': {},
        'all_errors': [],
        'tools_used_frequency': {},
        'conversation_samples': [],  # Sample exchanges for learning
    }
    
    for session in sessions:
        parsed = parse_session(session['path'])
        if 'error' in parsed:
            continue
        
        agent = identify_agent(session['path'], parsed)
        
        if agent not in summary['by_agent']:
            summary['by_agent'][agent] = {
                'session_count': 0,
                'total_messages': 0,
                'user_messages': 0,
                'errors': [],
                'tools': set(),
                'sample_topics': []
            }
        
        summary['by_agent'][agent]['session_count'] += 1
        summary['by_agent'][agent]['total_messages'] += parsed.get('message_count', 0)
        summary['by_agent'][agent]['user_messages'] += parsed.get('user_message_count', 0)
        summary['by_agent'][agent]['errors'].extend(parsed.get('errors', []))
        summary['by_agent'][agent]['tools'].update(parsed.get('tools_used', []))
        
        # Collect sample user messages as topic indicators
        for msg in parsed.get('sample_user_messages', [])[:3]:
            if msg and len(msg) > 10:
                summary['by_agent'][agent]['sample_topics'].append(msg[:100])
        
        # Track all errors
        summary['all_errors'].extend(parsed.get('errors', []))
        
        # Track tool usage
        for tool in parsed.get('tools_used', []):
            summary['tools_used_frequency'][tool] = summary['tools_used_frequency'].get(tool, 0) + 1
    
    # Convert sets to lists for JSON
    for agent in summary['by_agent']:
        summary['by_agent'][agent]['tools'] = list(summary['by_agent'][agent]['tools'])
        # Keep only unique topics
        summary['by_agent'][agent]['sample_topics'] = list(set(summary['by_agent'][agent]['sample_topics']))[:5]
    
    return summary


def format_for_compy(summary: dict):
    """Format the summary as a prompt for COMPY to analyze."""
    lines = [
        "# COMPY Nightly Review Input",
        f"Review time: {summary['review_time']}",
        f"Sessions reviewed: {summary['sessions_reviewed']}",
        "",
        "## Sessions by Agent",
    ]
    
    for agent, data in summary['by_agent'].items():
        lines.append(f"\n### {agent}")
        lines.append(f"- Sessions: {data['session_count']}")
        lines.append(f"- Assistant messages: {data['total_messages']}")
        lines.append(f"- User messages: {data.get('user_messages', 0)}")
        lines.append(f"- Tools used: {', '.join(data['tools']) if data['tools'] else 'None'}")
        
        # Show sample topics (what was discussed)
        topics = data.get('sample_topics', [])
        if topics:
            lines.append("- Topics discussed:")
            for topic in topics[:5]:
                lines.append(f"  - \"{topic}\"")
        
        if data['errors']:
            lines.append(f"- Errors: {len(data['errors'])}")
            for err in data['errors'][:3]:  # First 3 errors
                lines.append(f"  - {err[:100]}")
    
    if summary['all_errors']:
        lines.append("\n## All Errors (for pattern analysis)")
        for err in summary['all_errors'][:10]:
            lines.append(f"- {err[:150]}")
    
    lines.append("\n## Tool Usage Frequency")
    sorted_tools = sorted(summary['tools_used_frequency'].items(), key=lambda x: x[1], reverse=True)
    for tool, count in sorted_tools[:10]:
        lines.append(f"- {tool}: {count}")
    
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='COMPY Review')
    parser.add_argument('--hours', type=int, default=24, help='Hours to look back')
    parser.add_argument('--output', choices=['json', 'summary', 'compy'], default='compy',
                       help='Output format')
    args = parser.parse_args()
    
    sessions = get_recent_sessions(args.hours)
    
    if not sessions:
        print("No recent sessions found.")
        return
    
    summary = generate_summary(sessions)
    
    if args.output == 'json':
        print(json.dumps(summary, indent=2, default=str))
    elif args.output == 'summary':
        print(f"Sessions reviewed: {summary['sessions_reviewed']}")
        print(f"Agents active: {', '.join(summary['by_agent'].keys())}")
        print(f"Total errors: {len(summary['all_errors'])}")
    else:  # compy format
        print(format_for_compy(summary))


if __name__ == '__main__':
    main()
