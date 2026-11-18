"""
candidate_schema.py
====================
Unified candidate data model used across all scanning engines.

The fields are intentionally a superset of the existing JSON payloads so that
legacy scanners can continue writing their original structures while the
post-processing enrichment script maps them onto this common model.

Each engine fills the fields it owns; missing pieces default to None / 0.

Scoring:
  total_score = tier_score + volume_score + momentum_score + sector_score + cross_list_bonus
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Candidate:
    # --- Core identity ---
    symbol: str = ""
    name: Optional[str] = None
    industry: Optional[str] = None
    source: str = ""                    # originating list: "eod", "nr90", "ipo", "ems"
    sources: List[str] = field(default_factory=list)  # all lists where this symbol appeared

    # --- Price & volume snapshot ---
    ltp: Optional[float] = None
    vol: Optional[float] = None
    turnover_cr: Optional[float] = None
    daily_range_pct: Optional[float] = None
    change_pct: Optional[float] = None
    dist_from_high_pct: Optional[float] = None
    dist_52w_pct: Optional[float] = None
    close_loc: Optional[float] = None

    # --- Tier classification ---
    tier: Optional[str] = None
    tier_label: Optional[str] = None
    tier_order: Optional[int] = None

    # --- Scoring components (defaults to 0, filled by enrichment) ---
    tier_score: float = 0.0
    volume_score: float = 0.0
    momentum_score: float = 0.0
    sector_score: float = 0.0
    cross_list_bonus: float = 0.0
    total_score: float = 0.0

    # --- Extra info from specific engines ---
    flags: List[str] = field(default_factory=list)
    coil_tag: Optional[str] = None
    vol_tag: Optional[str] = None
    sector_tag: Optional[str] = None
    rs_rating: Optional[int] = None
    triggers: List[str] = field(default_factory=list)
    trigger_badges: List[str] = field(default_factory=list)
    nr_tags: List[str] = field(default_factory=list)

    # --- VCP / ATR (EOD engine) ---
    vcp_ratio_5d: Optional[float] = None
    vcp_ratio_3d: Optional[float] = None
    atr14: Optional[float] = None
    ema20: Optional[float] = None
    ema50: Optional[float] = None

    # --- Convenience & Classification ---
    score: Optional[float] = None           # original EOD score field
    priority_score: Optional[float] = None   # original NR90/IPO score field
    is_blue_sky: bool = False               # within <=3.5% of 52W High / ATH
    is_coiled: bool = False                 # tight range <= 2.2% or NR4/NR7/Inside Day/VDU
    is_sniper: bool = False                 # satisfies 3-Check Rule (Momentum + Blue Sky + Contraction)
    grade: str = "B"                        # "A+" for Sniper setups, "A" for Tier 1, "B" for standard

    def to_dict(self) -> dict:
        """Serialises to a dict suitable for JSON output."""
        return {k: v for k, v in asdict(self).items() if v is not None and v != [] and v != 0.0}
