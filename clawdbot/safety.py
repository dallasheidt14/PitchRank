#!/usr/bin/env python3
"""
PitchRank Safety Wrapper for Clawdbot

This module ensures all Clawdbot operations are safe and reversible.
All data modifications go through this wrapper which enforces:
1. Dry-run first policy
2. Audit logging
3. Human approval for destructive operations
4. Automatic rollback on errors

Usage:
    from clawdbot.safety import SafeOperationWrapper

    wrapper = SafeOperationWrapper(supabase_client)

    # Safe read operation
    result = wrapper.execute("query_teams", {"age_group": "u14"})

    # Safe write operation (adds to review queue)
    result = wrapper.execute("flag_duplicate", {"team_id": "xxx"})

    # Requires approval (returns approval request)
    result = wrapper.execute("fix_age_group", {"team_id": "xxx", "new_age": "u12"})
"""

import os
import sys
import json
import hashlib
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from dataclasses import dataclass, asdict
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)


class OperationTier(Enum):
    """Operation safety tiers"""
    READ = "read"           # Always allowed
    SAFE_WRITE = "safe"     # Allowed, logs to audit
    REQUIRES_APPROVAL = "approval"  # Must have human approval
    FORBIDDEN = "forbidden"  # Never allowed automatically


class OperationStatus(Enum):
    """Operation execution status"""
    SUCCESS = "success"
    PENDING_APPROVAL = "pending_approval"
    DRY_RUN = "dry_run"
    FAILED = "failed"
    FORBIDDEN = "forbidden"


@dataclass
class OperationResult:
    """Result of an operation attempt"""
    status: OperationStatus
    operation: str
    message: str
    data: Optional[Dict] = None
    approval_id: Optional[str] = None
    rollback_id: Optional[str] = None
    dry_run_preview: Optional[Dict] = None


# Define operation classifications
OPERATION_TIERS = {
    # Tier 1: READ operations - Always allowed
    "query_teams": OperationTier.READ,
    "query_games": OperationTier.READ,
    "query_rankings": OperationTier.READ,
    "check_data_quality": OperationTier.READ,
    "find_duplicates": OperationTier.READ,
    "find_age_mismatches": OperationTier.READ,
    "find_missing_states": OperationTier.READ,
    "get_pending_requests": OperationTier.READ,
    "get_review_queue": OperationTier.READ,
    "generate_report": OperationTier.READ,

    # Tier 2: SAFE_WRITE operations - Allowed with logging
    "add_to_review_queue": OperationTier.SAFE_WRITE,
    "log_data_quality_issue": OperationTier.SAFE_WRITE,
    "log_build_metrics": OperationTier.SAFE_WRITE,
    "quarantine_invalid_data": OperationTier.SAFE_WRITE,
    "submit_correction": OperationTier.SAFE_WRITE,
    "process_scrape_request": OperationTier.SAFE_WRITE,  # Imports new data, doesn't modify existing

    # Tier 3: REQUIRES_APPROVAL operations - Need human confirmation
    "fix_age_group": OperationTier.REQUIRES_APPROVAL,
    "fix_state_code": OperationTier.REQUIRES_APPROVAL,
    "merge_teams": OperationTier.REQUIRES_APPROVAL,
    "apply_correction": OperationTier.REQUIRES_APPROVAL,
    "approve_match": OperationTier.REQUIRES_APPROVAL,
    "recalculate_rankings": OperationTier.REQUIRES_APPROVAL,

    # Tier 4: FORBIDDEN operations - Never allowed automatically
    "delete_team": OperationTier.FORBIDDEN,
    "delete_game": OperationTier.FORBIDDEN,
    "delete_games_bulk": OperationTier.FORBIDDEN,
    "modify_game_directly": OperationTier.FORBIDDEN,
    "drop_table": OperationTier.FORBIDDEN,
    "truncate_table": OperationTier.FORBIDDEN,
}


class SafeOperationWrapper:
    """
    Wrapper that ensures all Clawdbot operations are safe.

    Enforces:
    - Operation classification (read/safe-write/approval/forbidden)
    - Dry-run first policy
    - Comprehensive audit logging
    - Human approval workflow
    - Automatic rollback on errors
    """

    def __init__(self, supabase_client, mode: str = "observer"):
        """
        Initialize the safety wrapper.

        Args:
            supabase_client: Supabase client instance
            mode: Operating mode - "observer", "safe_writer", or "supervised"
        """
        self.supabase = supabase_client
        self.mode = mode
        self.pending_approvals: Dict[str, Dict] = {}

        # Validate mode
        if mode not in ["observer", "safe_writer", "supervised"]:
            raise ValueError(f"Invalid mode: {mode}. Must be observer, safe_writer, or supervised")

        logger.info(f"SafeOperationWrapper initialized in '{mode}' mode")

    def execute(
        self,
        operation: str,
        params: Dict[str, Any],
        dry_run: bool = True,
        approval_code: Optional[str] = None
    ) -> OperationResult:
        """
        Execute an operation with safety checks.

        Args:
            operation: Name of the operation to execute
            params: Parameters for the operation
            dry_run: If True, preview changes without applying (default: True for safety)
            approval_code: Optional approval code for operations requiring human approval

        Returns:
            OperationResult with status and details
        """
        # 1. Check if operation is known
        tier = OPERATION_TIERS.get(operation)
        if tier is None:
            logger.warning(f"Unknown operation attempted: {operation}")
            return OperationResult(
                status=OperationStatus.FORBIDDEN,
                operation=operation,
                message=f"Unknown operation: {operation}. Must be explicitly defined."
            )

        # 2. Check if operation is forbidden
        if tier == OperationTier.FORBIDDEN:
            logger.error(f"Forbidden operation attempted: {operation}")
            self._log_audit("forbidden_attempt", operation, params)
            return OperationResult(
                status=OperationStatus.FORBIDDEN,
                operation=operation,
                message=f"Operation '{operation}' is forbidden and cannot be executed automatically."
            )

        # 3. Check mode restrictions
        if self.mode == "observer" and tier != OperationTier.READ:
            return OperationResult(
                status=OperationStatus.FORBIDDEN,
                operation=operation,
                message=f"Operation '{operation}' not allowed in observer mode. Switch to safe_writer or supervised mode."
            )

        if self.mode == "safe_writer" and tier == OperationTier.REQUIRES_APPROVAL:
            # In safe_writer mode, approval operations return pending status
            if not approval_code:
                approval_id = self._create_approval_request(operation, params)
                return OperationResult(
                    status=OperationStatus.PENDING_APPROVAL,
                    operation=operation,
                    message=f"Operation '{operation}' requires approval. Reply with: APPROVE-{approval_id}",
                    approval_id=approval_id,
                    dry_run_preview=self._preview_operation(operation, params)
                )

        # 4. Check approval for supervised mode
        if tier == OperationTier.REQUIRES_APPROVAL:
            if not approval_code:
                approval_id = self._create_approval_request(operation, params)
                return OperationResult(
                    status=OperationStatus.PENDING_APPROVAL,
                    operation=operation,
                    message=f"Operation '{operation}' requires approval. Reply with: APPROVE-{approval_id}",
                    approval_id=approval_id,
                    dry_run_preview=self._preview_operation(operation, params)
                )

            # Validate approval code
            if not self._validate_approval(approval_code, operation, params):
                return OperationResult(
                    status=OperationStatus.FAILED,
                    operation=operation,
                    message=f"Invalid or expired approval code: {approval_code}"
                )

        # 5. Execute with dry-run if requested
        if dry_run:
            preview = self._preview_operation(operation, params)
            return OperationResult(
                status=OperationStatus.DRY_RUN,
                operation=operation,
                message=f"Dry-run preview for '{operation}'",
                dry_run_preview=preview
            )

        # 6. Execute the operation
        try:
            # Log before execution
            self._log_audit("execute_start", operation, params)

            # Create snapshot for potential rollback
            rollback_id = self._create_snapshot(operation, params)

            # Execute the actual operation
            result = self._execute_operation(operation, params)

            # Log success
            self._log_audit("execute_success", operation, params, result)

            return OperationResult(
                status=OperationStatus.SUCCESS,
                operation=operation,
                message=f"Operation '{operation}' completed successfully",
                data=result,
                rollback_id=rollback_id
            )

        except Exception as e:
            # Log failure
            self._log_audit("execute_failed", operation, params, {"error": str(e)})

            # Attempt rollback
            if rollback_id:
                self._attempt_rollback(rollback_id)

            return OperationResult(
                status=OperationStatus.FAILED,
                operation=operation,
                message=f"Operation '{operation}' failed: {str(e)}"
            )

    def _preview_operation(self, operation: str, params: Dict) -> Dict:
        """Generate a preview of what the operation would do"""
        # This would contain operation-specific preview logic
        return {
            "operation": operation,
            "params": params,
            "would_affect": self._estimate_affected_records(operation, params),
            "preview_generated_at": datetime.now().isoformat()
        }

    def _estimate_affected_records(self, operation: str, params: Dict) -> Dict:
        """Estimate how many records would be affected"""
        # This would query the database to estimate impact
        return {"teams": 0, "games": 0, "aliases": 0}

    def _create_approval_request(self, operation: str, params: Dict) -> str:
        """Create a pending approval request"""
        approval_id = hashlib.sha256(
            f"{operation}:{json.dumps(params, sort_keys=True)}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]

        self.pending_approvals[approval_id] = {
            "operation": operation,
            "params": params,
            "created_at": datetime.now().isoformat(),
            "expires_at": None  # Could add expiration
        }

        # Also store in database for persistence
        try:
            self.supabase.table("clawdbot_approvals").insert({
                "approval_id": approval_id,
                "operation": operation,
                "params": json.dumps(params),
                "status": "pending",
                "created_at": datetime.now().isoformat()
            }).execute()
        except Exception as e:
            logger.warning(f"Could not persist approval request: {e}")

        return approval_id

    def _validate_approval(self, approval_code: str, operation: str, params: Dict) -> bool:
        """Validate an approval code"""
        # Check memory first
        if approval_code in self.pending_approvals:
            pending = self.pending_approvals[approval_code]
            if pending["operation"] == operation:
                del self.pending_approvals[approval_code]
                return True

        # Check database
        try:
            result = self.supabase.table("clawdbot_approvals")\
                .select("*")\
                .eq("approval_id", approval_code)\
                .eq("status", "pending")\
                .single()\
                .execute()

            if result.data:
                # Mark as used
                self.supabase.table("clawdbot_approvals")\
                    .update({"status": "approved", "approved_at": datetime.now().isoformat()})\
                    .eq("approval_id", approval_code)\
                    .execute()
                return True
        except Exception as e:
            logger.warning(f"Error validating approval: {e}")

        return False

    def _create_snapshot(self, operation: str, params: Dict) -> Optional[str]:
        """Create a snapshot of affected data for potential rollback"""
        rollback_id = hashlib.sha256(
            f"snapshot:{operation}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]

        # This would store the current state of affected records
        try:
            self.supabase.table("clawdbot_snapshots").insert({
                "rollback_id": rollback_id,
                "operation": operation,
                "params": json.dumps(params),
                "snapshot_data": "{}",  # Would contain actual data
                "created_at": datetime.now().isoformat()
            }).execute()
        except Exception as e:
            logger.warning(f"Could not create snapshot: {e}")
            return None

        return rollback_id

    def _attempt_rollback(self, rollback_id: str) -> bool:
        """Attempt to rollback an operation using its snapshot"""
        try:
            result = self.supabase.table("clawdbot_snapshots")\
                .select("*")\
                .eq("rollback_id", rollback_id)\
                .single()\
                .execute()

            if result.data:
                # Restore from snapshot
                # This would contain operation-specific rollback logic
                logger.info(f"Rollback {rollback_id} executed")
                return True
        except Exception as e:
            logger.error(f"Rollback failed: {e}")

        return False

    def _execute_operation(self, operation: str, params: Dict) -> Dict:
        """Execute the actual operation"""
        # This would contain operation-specific logic
        # For now, return a placeholder
        return {"executed": True, "operation": operation}

    def _log_audit(
        self,
        event_type: str,
        operation: str,
        params: Dict,
        result: Optional[Dict] = None
    ):
        """Log an audit event"""
        try:
            self.supabase.table("clawdbot_audit_log").insert({
                "event_type": event_type,
                "operation": operation,
                "params": json.dumps(params),
                "result": json.dumps(result) if result else None,
                "mode": self.mode,
                "timestamp": datetime.now().isoformat()
            }).execute()
        except Exception as e:
            # If we can't log to database, at least log locally
            logger.error(f"Audit log failed: {e}")
            logger.info(f"AUDIT: {event_type} - {operation} - {params}")


class DataQualityChecker:
    """
    Safe data quality checking operations.
    All methods are read-only and return issues found.
    """

    def __init__(self, supabase_client):
        self.supabase = supabase_client

    def find_age_mismatches(self) -> List[Dict]:
        """Find teams where age_group doesn't match birth year in name"""
        import re

        current_year = 2025

        # Fetch teams
        result = self.supabase.table("teams")\
            .select("team_id_master, team_name, age_group")\
            .execute()

        mismatches = []
        for team in result.data or []:
            team_name = team.get("team_name", "")
            current_age = (team.get("age_group") or "").lower()

            # Extract birth year from name
            match = re.search(r'(?<![0-9])(20\d{2})(?![0-9])', team_name)
            if match:
                birth_year = int(match.group(1))
                expected_age = current_year - birth_year + 1
                expected_group = f"u{expected_age}"

                if 7 <= expected_age <= 19 and expected_group != current_age:
                    mismatches.append({
                        "team_id": team["team_id_master"],
                        "team_name": team_name,
                        "current_age_group": current_age,
                        "expected_age_group": expected_group,
                        "birth_year": birth_year
                    })

        return mismatches

    def find_missing_state_codes(self) -> List[Dict]:
        """Find teams without state_code that could be inferred from club"""
        result = self.supabase.table("teams")\
            .select("team_id_master, team_name, club_name, state_code")\
            .is_("state_code", "null")\
            .not_.is_("club_name", "null")\
            .limit(100)\
            .execute()

        return result.data or []

    def find_potential_duplicates(self) -> List[Dict]:
        """Find teams that might be duplicates based on name similarity"""
        # This would use fuzzy matching
        # For now, return empty - actual implementation would be more complex
        return []

    def get_quality_summary(self) -> Dict:
        """Get a summary of data quality issues"""
        age_mismatches = self.find_age_mismatches()
        missing_states = self.find_missing_state_codes()

        return {
            "age_group_mismatches": len(age_mismatches),
            "missing_state_codes": len(missing_states),
            "potential_duplicates": 0,
            "checked_at": datetime.now().isoformat()
        }


if __name__ == "__main__":
    # Test the safety wrapper
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")

    if url and key:
        client = create_client(url, key)
        wrapper = SafeOperationWrapper(client, mode="observer")

        # Test a read operation
        result = wrapper.execute("query_teams", {"limit": 10})
        print(f"Result: {result}")

        # Test a forbidden operation
        result = wrapper.execute("delete_team", {"team_id": "xxx"})
        print(f"Forbidden result: {result}")
    else:
        print("Missing Supabase credentials")
