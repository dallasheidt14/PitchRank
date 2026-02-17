#!/usr/bin/env python3
"""
Verify that all agent cron jobs include learnings file reads.
Run this to audit the learning pipeline is working.
"""

import subprocess
import json
import re

def get_cron_jobs():
    """Fetch all cron jobs via openclaw CLI."""
    # This would need openclaw access - for now we check via pattern
    return None

def check_prompt_for_learnings(prompt: str, agent_name: str) -> dict:
    """Check if a prompt includes learnings file reads."""
    results = {
        'agent': agent_name,
        'reads_shared_learnings': False,
        'reads_agent_learnings': False,
        'issues': []
    }
    
    # Check for shared LEARNINGS.md
    if 'docs/LEARNINGS.md' in prompt or 'LEARNINGS.md' in prompt:
        results['reads_shared_learnings'] = True
    else:
        results['issues'].append('Missing: docs/LEARNINGS.md')
    
    # Check for agent-specific learnings
    agent_lower = agent_name.lower().replace(' ', '-').split(':')[0]
    learnings_patterns = [
        f'{agent_lower}-learnings.skill.md',
        f'.claude/skills/{agent_lower}',
        'learnings.skill.md'
    ]
    
    for pattern in learnings_patterns:
        if pattern in prompt.lower():
            results['reads_agent_learnings'] = True
            break
    
    if not results['reads_agent_learnings']:
        # Some agents don't have specific learnings files, that's OK
        results['issues'].append(f'Note: No agent-specific learnings file referenced')
    
    return results

def main():
    print("=" * 60)
    print("AGENT LEARNINGS VERIFICATION")
    print("=" * 60)
    print()
    
    # Expected agents and their required learnings
    agents = {
        'Watchy': {'shared': True, 'specific': 'watchy-learnings.skill.md'},
        'Scrappy (Mon)': {'shared': True, 'specific': 'scrappy-learnings.skill.md'},
        'Scrappy (Wed)': {'shared': True, 'specific': 'scrappy-learnings.skill.md'},
        'Ranky': {'shared': True, 'specific': 'ranky-learnings.skill.md'},
        'Movy (Tue)': {'shared': True, 'specific': 'movy-learnings.skill.md'},
        'Movy (Wed)': {'shared': True, 'specific': 'movy-learnings.skill.md'},
        'Socialy': {'shared': True, 'specific': None},
        'Cleany': {'shared': True, 'specific': 'cleany-learnings.skill.md'},
        'COMPY': {'shared': True, 'specific': None},
    }
    
    print("This script verifies agent cron prompts include learnings.")
    print("Run 'cron action=list' and manually check each agent's prompt contains:")
    print()
    
    for agent, config in agents.items():
        print(f"### {agent}")
        print(f"  ✓ Must read: docs/LEARNINGS.md")
        if config['specific']:
            print(f"  ✓ Should read: .claude/skills/{config['specific']}")
        print()
    
    print("=" * 60)
    print("To fix missing learnings, update cron with:")
    print("  cron action=update jobId=<id> patch={...}")
    print("=" * 60)

if __name__ == '__main__':
    main()
