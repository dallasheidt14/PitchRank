"""
Scrapy Item definitions for Modular11 scraper.

This item schema matches the source format expected by import_games_enhanced.py
and EnhancedDataValidator.validate_game.
"""
import scrapy


class Modular11GameItem(scrapy.Item):
    """
    Game item representing one team's perspective of a match.
    
    Each game produces TWO items (home perspective + away perspective),
    following the same pattern as GotSport imports.
    """
    # Provider identification
    provider = scrapy.Field()              # always "modular11"
    
    # Team information (perspective team)
    team_id = scrapy.Field()               # provider team/academy id
    team_id_source = scrapy.Field()        # same as team_id
    team_name = scrapy.Field()             # team display name
    club_name = scrapy.Field()             # club name (same as team on modular11)
    
    # Opponent information
    opponent_id = scrapy.Field()           # opponent's academy id
    opponent_id_source = scrapy.Field()    # same as opponent_id
    opponent_name = scrapy.Field()         # opponent display name
    opponent_club_name = scrapy.Field()    # opponent club name
    
    # Match classification
    age_group = scrapy.Field()             # "U13", "U14", "U15", "U16", "U17"
    gender = scrapy.Field()                # "M" (all MLS NEXT matches are male)
    state = scrapy.Field()                 # 2-letter state code if available, else ""
    competition = scrapy.Field()           # "League" or "MLS NEXT Flex"
    division_name = scrapy.Field()         # division/region text (e.g., "Southwest")
    event_name = scrapy.Field()            # same as competition
    venue = scrapy.Field()                 # venue/field name
    
    # Match details
    game_date = scrapy.Field()             # "YYYY-MM-DD"
    home_away = scrapy.Field()             # "H" or "A"
    goals_for = scrapy.Field()             # numeric string (team's score)
    goals_against = scrapy.Field()         # numeric string (opponent's score)
    result = scrapy.Field()                # "W", "L", "D", or "U" (unknown)
    
    # MLS NEXT Division
    mls_division = scrapy.Field()          # "HD" (Homegrown) or "AD" (Academy)
    
    # Metadata
    match_id = scrapy.Field()              # Modular11 match ID
    source_url = scrapy.Field()            # API endpoint URL
    scraped_at = scrapy.Field()            # ISO timestamp


