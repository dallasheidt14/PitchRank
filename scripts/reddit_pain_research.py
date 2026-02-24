#!/usr/bin/env python3
"""
Reddit Pain Point Research for Blog Content
Fetches top posts from youth soccer subreddits and extracts pain points.

Usage:
    python3 scripts/reddit_pain_research.py
    python3 scripts/reddit_pain_research.py --subreddit youthsoccer --limit 20
    python3 scripts/reddit_pain_research.py --thread-url "https://reddit.com/r/youthsoccer/comments/xyz/..."
"""

import argparse
import json
import urllib.request
import urllib.error
from datetime import datetime

SUBREDDITS = [
    "youthsoccer",
    "bootroom", 
    "SoccerCoachResources",
    "soccermoms",
]

USER_AGENT = "PitchRank Research Bot 1.0"

def fetch_reddit_json(url: str) -> dict:
    """Fetch JSON from Reddit URL."""
    if not url.endswith('.json'):
        url = url.rstrip('/') + '.json'
    
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print(f"Error fetching {url}: {e}")
        return {}

def get_top_posts(subreddit: str, limit: int = 10, timeframe: str = "year") -> list:
    """Get top posts from a subreddit."""
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t={timeframe}&limit={limit}"
    data = fetch_reddit_json(url)
    
    posts = []
    if data and 'data' in data and 'children' in data['data']:
        for child in data['data']['children']:
            post = child['data']
            posts.append({
                'title': post.get('title', ''),
                'selftext': post.get('selftext', '')[:2000],  # Truncate long posts
                'score': post.get('score', 0),
                'num_comments': post.get('num_comments', 0),
                'url': f"https://reddit.com{post.get('permalink', '')}",
                'created': datetime.fromtimestamp(post.get('created_utc', 0)).isoformat(),
            })
    return posts

def get_thread_with_comments(url: str) -> dict:
    """Get a thread and its comments."""
    data = fetch_reddit_json(url)
    
    if not data or len(data) < 2:
        return {}
    
    # First element is the post, second is comments
    post_data = data[0]['data']['children'][0]['data']
    
    result = {
        'title': post_data.get('title', ''),
        'selftext': post_data.get('selftext', ''),
        'score': post_data.get('score', 0),
        'num_comments': post_data.get('num_comments', 0),
        'comments': []
    }
    
    # Extract comments (flatten tree)
    def extract_comments(children, depth=0):
        comments = []
        for child in children:
            if child['kind'] != 't1':
                continue
            comment = child['data']
            comments.append({
                'body': comment.get('body', '')[:1000],
                'score': comment.get('score', 0),
                'depth': depth
            })
            # Get replies
            if comment.get('replies') and isinstance(comment['replies'], dict):
                replies = comment['replies'].get('data', {}).get('children', [])
                comments.extend(extract_comments(replies, depth + 1))
        return comments
    
    if data[1].get('data', {}).get('children'):
        result['comments'] = extract_comments(data[1]['data']['children'])
    
    return result

def analyze_for_pain_points(posts: list) -> dict:
    """Categorize posts by likely pain point themes."""
    themes = {
        'cost_money': [],
        'time_commitment': [],
        'club_politics': [],
        'development_vs_winning': [],
        'choosing_club': [],
        'college_recruiting': [],
        'travel_tournaments': [],
        'other': []
    }
    
    keywords = {
        'cost_money': ['cost', 'money', 'expensive', 'fee', 'pay', 'afford', '$', 'price', 'worth'],
        'time_commitment': ['time', 'travel', 'hours', 'drive', 'sacrifice', 'weekend', 'commitment'],
        'club_politics': ['politics', 'favoritism', 'coach', 'playing time', 'bench', 'unfair'],
        'development_vs_winning': ['development', 'winning', 'results', 'pressure', 'fun', 'burnout'],
        'choosing_club': ['choose', 'pick', 'tryout', 'which club', 'best club', 'compare'],
        'college_recruiting': ['college', 'recruit', 'scholarship', 'exposure', 'showcase'],
        'travel_tournaments': ['tournament', 'travel', 'hotel', 'stay-to-play', 'showcase']
    }
    
    for post in posts:
        text = (post['title'] + ' ' + post.get('selftext', '')).lower()
        categorized = False
        
        for theme, words in keywords.items():
            if any(word in text for word in words):
                themes[theme].append(post)
                categorized = True
                break
        
        if not categorized:
            themes['other'].append(post)
    
    return themes

def main():
    parser = argparse.ArgumentParser(description='Research youth soccer pain points from Reddit')
    parser.add_argument('--subreddit', default='youthsoccer', help='Subreddit to search')
    parser.add_argument('--limit', type=int, default=15, help='Number of posts to fetch')
    parser.add_argument('--timeframe', default='year', choices=['day', 'week', 'month', 'year', 'all'])
    parser.add_argument('--thread-url', help='Specific thread URL to analyze')
    parser.add_argument('--all-subs', action='store_true', help='Search all youth soccer subreddits')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    args = parser.parse_args()
    
    if args.thread_url:
        # Analyze specific thread
        print(f"\n{'='*60}")
        print(f"📖 ANALYZING THREAD")
        print(f"{'='*60}\n")
        
        thread = get_thread_with_comments(args.thread_url)
        if thread:
            print(f"Title: {thread['title']}")
            print(f"Score: {thread['score']} | Comments: {thread['num_comments']}")
            print(f"\nPost:\n{thread['selftext'][:1500]}...")
            print(f"\n--- TOP COMMENTS ({len(thread['comments'])} total) ---\n")
            
            # Show top 10 comments by score
            sorted_comments = sorted(thread['comments'], key=lambda x: x['score'], reverse=True)[:10]
            for i, comment in enumerate(sorted_comments, 1):
                print(f"{i}. [+{comment['score']}] {comment['body'][:300]}...")
                print()
        return
    
    # Fetch from subreddits
    subreddits = SUBREDDITS if args.all_subs else [args.subreddit]
    all_posts = []
    
    for sub in subreddits:
        print(f"\nFetching r/{sub}...")
        posts = get_top_posts(sub, args.limit, args.timeframe)
        all_posts.extend(posts)
        print(f"  Found {len(posts)} posts")
    
    if args.json:
        print(json.dumps(all_posts, indent=2))
        return
    
    # Analyze and display
    themes = analyze_for_pain_points(all_posts)
    
    print(f"\n{'='*60}")
    print(f"📊 PAIN POINT ANALYSIS ({len(all_posts)} posts)")
    print(f"{'='*60}\n")
    
    for theme, posts in themes.items():
        if posts:
            print(f"\n🔥 {theme.upper().replace('_', ' ')} ({len(posts)} posts)")
            print("-" * 40)
            for post in posts[:3]:  # Top 3 per category
                print(f"  [{post['score']}⬆] {post['title'][:70]}...")
                print(f"       {post['url']}")
    
    print(f"\n{'='*60}")
    print("💡 Use --thread-url to deep-dive into specific discussions")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
