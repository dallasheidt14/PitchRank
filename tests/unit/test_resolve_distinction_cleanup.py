import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from src.utils.team_name_utils import resolve_distinction


def test_drops_club_acronym_short():
    # "vsa" = initials of Virginia Soccer Assocation -> not a squad tag
    got = resolve_distinction("VSA 2014 Premier Red", "Virginia Soccer Assocation", "VA")
    assert got == "red|premier"  # vsa dropped; red (color) before premier (program)


def test_drops_club_acronym_long():
    # "cosc" = initials of California Odyssey Soccer Club; ECNL is league, 2013 is age
    got = resolve_distinction("COSC ECNL 2013", "California Odyssey Soccer Club", "CA")
    assert got is None


def test_drops_stray_single_char():
    # "c" left over from "F.C" is not a squad tag
    got = resolve_distinction("MIDWEST GLADIATORS F.C", "MIDWEST GLADIATORS F.C", "TX")
    assert got is None


def test_drops_leftover_league_token():
    got = resolve_distinction("Hoover-Vestavia 2009 MLS NEXT", "Hoover-Vestavia Soccer", "AL")
    assert got is None  # mls + next both dropped as league tokens


def test_preserves_real_squad_tag():
    # color + direction is a legitimate squad distinguisher
    got = resolve_distinction("CCV Stars 2011 East Navy", "Ccv Stars", "AZ")
    assert got == "navy|east"  # 2-word club -> no acronym; nothing stripped


def test_preserves_modular11_ad_hd():
    # HD must survive (Modular11 / MLS NEXT format is sacred)
    got = resolve_distinction("Carolina Core FC U13 HD", "Carolina Core FC Youth", "NC")
    assert got is not None and "hd" in got.split("|")
