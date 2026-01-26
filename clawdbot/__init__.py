"""
PitchRank Clawdbot Integration

This module provides automation agents for PitchRank data operations.

Agents:
    - Scout: Coordinator agent (morning briefings, status reports)
    - Hunter: Scraping agent (game discovery, imports)
    - Doc: Data quality agent (validation, fixes)
    - Ranker: Rankings agent (calculations, analysis)

Usage:
    from clawdbot.safety import SafeOperationWrapper
    from clawdbot.check_data_quality import DataQualityChecker

Safety Modes:
    - observer: Read-only, no modifications
    - safe_writer: Can import new data, flag issues
    - supervised: Can modify data with approval

See MAC_MINI_SETUP.md for installation instructions.
"""

__version__ = "1.0.0"
__author__ = "PitchRank Team"

from .safety import SafeOperationWrapper, OperationTier, OperationStatus
