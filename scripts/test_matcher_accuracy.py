#!/usr/bin/env python3
"""
Test harness to evaluate game_matcher's fuzzy matching accuracy using approved matches.

This script:
1. Loads all approved entries from team_match_review_queue
2. Runs the current fuzzy matcher against each entry
3. Compares results to the approved matches
4. Calculates accuracy metrics

Usage:
    python3 scripts/test_matcher_accuracy.py [--limit N] [--verbose]
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Optional
import argparse
from datetime import datetime
import json

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from supabase import create_client
from config.settings import SUPABASE_URL, SUPABASE_KEY
from src.models.game_matcher import GameHistoryMatcher

class MatcherAccuracyTester:
    """Test the fuzzy matcher accuracy against known-good approved matches"""
    
    def __init__(self, supabase_client, verbose=False):
        self.db = supabase_client
        self.matcher = GameHistoryMatcher(supabase_client)
        self.verbose = verbose
        
        # Metrics
        self.total_tested = 0
        self.correct_matches = 0
        self.wrong_matches = 0
        self.no_matches = 0
        self.skipped = 0
        
        # Detailed results for analysis
        self.results = []
        
    def load_approved_matches(self, limit: Optional[int] = None) -> List[Dict]:
        """Load approved entries from team_match_review_queue that have a suggested match"""
        print("Loading approved matches from review queue...")
        
        query = self.db.table('team_match_review_queue').select('*').eq(
            'status', 'approved'
        ).not_.is_('suggested_master_team_id', 'null')
        
        if limit:
            query = query.limit(limit)
        
        result = query.execute()
        
        print(f"Loaded {len(result.data)} approved matches to test")
        return result.data
    
    def test_single_match(self, approved_entry: Dict) -> Dict:
        """Test a single approved match against the fuzzy matcher"""
        provider_team_name = approved_entry.get('provider_team_name')
        expected_team_id = approved_entry.get('suggested_master_team_id')
        match_details = approved_entry.get('match_details', {})
        
        # Extract match parameters
        age_group = match_details.get('age_group')
        gender = match_details.get('gender')
        club_name = match_details.get('club_name')
        
        # Skip if missing required fields
        if not all([provider_team_name, age_group, gender]):
            return {
                'status': 'skipped',
                'reason': 'missing_required_fields',
                'entry': approved_entry
            }
        
        # Run the fuzzy matcher (simulating what would happen during game matching)
        # This is the core logic from _match_team -> _fuzzy_match_team
        fuzzy_result = self.matcher._fuzzy_match_team(
            team_name=provider_team_name,
            age_group=age_group.lower() if age_group else age_group,  # Normalize
            gender=gender,
            club_name=club_name
        )
        
        # Evaluate result
        if fuzzy_result:
            matched_team_id = fuzzy_result['team_id']
            confidence = fuzzy_result['confidence']
            
            if matched_team_id == expected_team_id:
                status = 'correct'
            else:
                status = 'wrong'
        else:
            matched_team_id = None
            confidence = 0.0
            status = 'no_match'
        
        return {
            'status': status,
            'provider_team_name': provider_team_name,
            'expected_team_id': expected_team_id,
            'matched_team_id': matched_team_id,
            'confidence': confidence,
            'age_group': age_group,
            'gender': gender,
            'club_name': club_name,
            'provider_id': approved_entry.get('provider_id'),
            'provider_team_id': approved_entry.get('provider_team_id')
        }
    
    def run_accuracy_test(self, limit: Optional[int] = None):
        """Run the full accuracy test"""
        print("\n" + "="*60)
        print("GAME MATCHER ACCURACY TEST")
        print("="*60 + "\n")
        
        # Load approved matches
        approved_matches = self.load_approved_matches(limit)
        
        if not approved_matches:
            print("No approved matches found to test!")
            return
        
        print(f"\nTesting {len(approved_matches)} approved matches...\n")
        
        # Test each match
        for i, entry in enumerate(approved_matches, 1):
            if i % 100 == 0:
                print(f"Processed {i}/{len(approved_matches)} entries...")
            
            result = self.test_single_match(entry)
            self.results.append(result)
            
            # Update metrics
            if result['status'] == 'correct':
                self.correct_matches += 1
            elif result['status'] == 'wrong':
                self.wrong_matches += 1
            elif result['status'] == 'no_match':
                self.no_matches += 1
            elif result['status'] == 'skipped':
                self.skipped += 1
            
            self.total_tested = i
            
            # Verbose output for wrong matches
            if self.verbose and result['status'] == 'wrong':
                print(f"\n[WRONG MATCH] {result['provider_team_name']}")
                print(f"  Expected: {result['expected_team_id']}")
                print(f"  Got: {result['matched_team_id']} (confidence: {result['confidence']:.3f})")
        
        # Print summary
        self.print_summary()
    
    def print_summary(self):
        """Print detailed accuracy summary"""
        print("\n" + "="*60)
        print("ACCURACY TEST RESULTS")
        print("="*60 + "\n")
        
        total_valid = self.total_tested - self.skipped
        
        print(f"Total Entries Tested: {self.total_tested}")
        print(f"Skipped (missing data): {self.skipped}")
        print(f"Valid Tests: {total_valid}\n")
        
        if total_valid > 0:
            accuracy = (self.correct_matches / total_valid) * 100
            
            print("MATCH RESULTS:")
            print(f"  ✓ Correct Matches:  {self.correct_matches:5d} ({self.correct_matches/total_valid*100:5.2f}%)")
            print(f"  ✗ Wrong Matches:    {self.wrong_matches:5d} ({self.wrong_matches/total_valid*100:5.2f}%)")
            print(f"  ∅ No Match Found:   {self.no_matches:5d} ({self.no_matches/total_valid*100:5.2f}%)")
            
            print(f"\n{'='*60}")
            print(f"BASELINE ACCURACY: {accuracy:.2f}%")
            print(f"{'='*60}\n")
            
            # Additional insights
            print("BREAKDOWN BY CONFIDENCE:")
            confidence_buckets = {
                '0.90+': [],
                '0.85-0.89': [],
                '0.80-0.84': [],
                '0.75-0.79': [],
                'below 0.75': []
            }
            
            for result in self.results:
                if result['status'] in ['correct', 'wrong'] and result.get('confidence'):
                    conf = result['confidence']
                    if conf >= 0.90:
                        bucket = '0.90+'
                    elif conf >= 0.85:
                        bucket = '0.85-0.89'
                    elif conf >= 0.80:
                        bucket = '0.80-0.84'
                    elif conf >= 0.75:
                        bucket = '0.75-0.79'
                    else:
                        bucket = 'below 0.75'
                    
                    confidence_buckets[bucket].append(result)
            
            for bucket, results in confidence_buckets.items():
                if results:
                    correct_in_bucket = sum(1 for r in results if r['status'] == 'correct')
                    total_in_bucket = len(results)
                    accuracy_in_bucket = (correct_in_bucket / total_in_bucket * 100) if total_in_bucket > 0 else 0
                    print(f"  {bucket:12s}: {correct_in_bucket:4d}/{total_in_bucket:4d} correct ({accuracy_in_bucket:5.2f}%)")
            
            # Show some examples of wrong matches
            wrong_results = [r for r in self.results if r['status'] == 'wrong']
            if wrong_results and not self.verbose:
                print(f"\nSAMPLE WRONG MATCHES (first 5):")
                for result in wrong_results[:5]:
                    print(f"\n  Team: {result['provider_team_name']}")
                    print(f"  Expected: {result['expected_team_id']}")
                    print(f"  Got:      {result['matched_team_id']} (conf: {result['confidence']:.3f})")
                    if result.get('club_name'):
                        print(f"  Club:     {result['club_name']}")
    
    def save_results(self, output_file: str = None):
        """Save detailed results to JSON file"""
        if not output_file:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = f"matcher_accuracy_results_{timestamp}.json"
        
        output_path = project_root / 'logs' / output_file
        output_path.parent.mkdir(exist_ok=True)
        
        summary = {
            'timestamp': datetime.now().isoformat(),
            'total_tested': self.total_tested,
            'skipped': self.skipped,
            'correct_matches': self.correct_matches,
            'wrong_matches': self.wrong_matches,
            'no_matches': self.no_matches,
            'accuracy_pct': (self.correct_matches / (self.total_tested - self.skipped) * 100) 
                           if (self.total_tested - self.skipped) > 0 else 0,
            'detailed_results': self.results
        }
        
        with open(output_path, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"\nDetailed results saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Test game matcher accuracy')
    parser.add_argument('--limit', type=int, help='Limit number of entries to test')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output (show all wrong matches)')
    parser.add_argument('--save', action='store_true', help='Save detailed results to JSON')
    
    args = parser.parse_args()
    
    # Initialize Supabase client
    db = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Run test
    tester = MatcherAccuracyTester(db, verbose=args.verbose)
    tester.run_accuracy_test(limit=args.limit)
    
    # Save results if requested
    if args.save:
        tester.save_results()


if __name__ == '__main__':
    main()
