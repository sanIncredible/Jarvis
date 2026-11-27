# -*- coding: utf-8 -*-
"""test_kedia_sa.py - Kedia-style sequential SA section of the 09:14 brief. Pure function on synthetic history:
no workbook, no network, no Telegram, no file writes."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pre_market_summary as pms

PASS = [0]


def check(name, cond, info=""):
    if not cond:
        print(f"FAIL: {name} {info}")
        sys.exit(1)
    PASS[0] += 1
    print(f"PASS: {name}")


def row(d, up4=4.0, dn4=2.0, sf=0.9, vr=0.45, low=30.0, nifty=0.1, bd_sf=0.8, a10=60.0):
    return {"date": d.strftime("%d-%b-%Y"), "up_4_pct": up4, "up_4_cnt": int(up4 * 25), "dn_4_pct": dn4,
            "bo_sf_ratio": sf, "vol_ratio": vr, "below_vol_pct": low, "nifty_chg": nifty,
            "net_breadth": up4 - dn4, "bd_sf_ratio": bd_sf, "pct_ab_10": a10}


days = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(300)]
# steady year: breadth 55-65% above 10-DEMA, 4% breakouts cycling 3.0..6.6
base = [row(d, up4=3.0 + (i % 10) * 0.4, a10=55.0 + (i % 5) * 2.5) for i, d in enumerate(days)]
T = lambda h: pms.kedia_sa_read(h, today=_parse(h[-1]["date"]) + timedelta(days=1))
_parse = pms._parse_sheet_date
txt = lambda r: " ".join(r["lines"])


def seq(a10s, **kw):
    """replace the tail of base with a 10-DEMA path (per-day overrides via kw lists)"""
    h = base[:len(base) - len(a10s)]
    for j, a in enumerate(a10s):
        i = len(h)
        args = {k: v[j] for k, v in kw.items()}
        h.append(row(days[i], a10=a, **{"up4": 4.0, **args}))
    return h


check("too little history -> unavailable", pms.kedia_sa_read(base[:10])["available"] is False)

# 26-Nov-like: pullback 77 -> 28, first bounce day to 32 on weak thrust, volume drying
r = T(seq([77, 70, 60, 48, 40, 33, 29, 28, 32], up4=[5, 4, 3, 3, 3, 3, 3, 3, 5.0], vr=[.5, .5, .45, .45, .45, .45, .45, .41, .31]))
check("pullback -> bounce day 1", r["phase"] == "BOUNCE_D1", r["phase"])
check("pullback is not called oversold", "not an extreme" in txt(r) and not r["at_extreme"])
check("weak thrust wording", "thrust is weak" in txt(r))
check("day-1 scenarios: follow-through vs fade", "Follow-through" in txt(r) and "Fade" in txt(r))
check("selective stance anchored to a date", r["stance_code"] == "SELECTIVE" and ("No change in stance since" in txt(r) or "Stance changes today" in txt(r)))

# fix 2: weak, dry bounce in a weak market (<30% above 10-DEMA, vol < 0.5, no decent 4% day) -> WAIT
rw = T(seq([60, 45, 30, 22, 18, 20, 24], vr=[.4] * 7, up4=[3] * 7))
check("weak dry bounce -> WAIT", rw["stance_code"] == "WAIT", rw["stance_code"])
# ...but not when volume is healthy (17-Nov-2024 guard)
rw = T(seq([60, 45, 30, 22, 18, 20, 24], vr=[.4] * 6 + [.62], up4=[3] * 7))
check("healthy volume -> not WAIT", rw["stance_code"] != "WAIT", rw["stance_code"])
# fix 1: rising breadth + one decent 4% day turns positive even with volume ~0.35
rw = T(seq([20, 14, 22, 32, 40], up4=[2, 2, 5, 9.0, 6], vr=[.35] * 5))
check("rising breadth + decent day -> POSITIVE with low volume", rw["stance_code"] == "POSITIVE", rw["stance_code"])
check("step-aside trigger is the swing low", "back below 28%" in txt(r))

# 22-Oct-like: falling to 13% = approaching, NOT extreme -> expect further decline, bounce = trap
r = T(seq([57, 40, 30, 20, 13]))
check("13% is approaching, not extreme", r["phase"] == "DECLINE" and not r["at_extreme"] and "5-6% or lower" in txt(r))
check("non-extreme decline: weak bounce is a trap", "trap" in txt(r))

# at a genuine extreme -> sell-off then reversal is the ideal; gap-up is the spoiler
r = T(seq([57, 30, 15, 9, 6]))
check("6% is an extreme", r["at_extreme"] and "spoiler" in txt(r) and "Parabolic" in txt(r))

# 28/29-Oct-like: bounce from 7%, 10% then 17.5% thrust, volume falling -> not a thrust, lack of confidence, exhaustion
r = T(seq([20, 7, 18, 25, 30], up4=[2, 2, 9.9, 17.5, 7.7], vr=[.5, .5, .40, .38, .30], sf=[.5, .5, 1.6, 1.68, 1.43]))
check("bounce day 3", r["phase"] == "BOUNCE_D3", r["phase"])
check("17.5% is not a breadth thrust", "not a breadth thrust" in txt(r))
check("volume should have picked up", "should have picked up" in txt(r) and "lack confidence" in txt(r))
check("exhaustion / real test", "real test" in txt(r))

# real breadth thrust with volume -> entries on dips
r = T(seq([20, 7, 25, 40], up4=[2, 2, 28, 22], vr=[.5, .5, .6, .9], sf=[.5, .5, 1.8, 1.6]))
check("thrust + volume -> dips are entries", "breadth thrust" in txt(r) and "entries" in txt(r))

# breakdown day -> step aside; volume up on a down day = selling
r = T(seq([60, 58, 45], up4=[4, 4, 1.0], dn4=[2, 2, 15.0], vr=[.4, .4, 1.2], bd_sf=[.8, .8, 2.0], sf=[.9, .9, .4]))
check("breakdown day -> step aside", r["stance_code"] == "STEP_ASIDE")
check("volume up on down day read as selling", "selling pressure" in txt(r))

# two strong days -> positive
r = T(seq([50, 55, 62], up4=[4, 11, 12], vr=[.45, .8, .9], sf=[.9, 1.5, 1.6]))
check("two strong days -> positive", r["stance_code"] == "POSITIVE")

# calendar: post-holiday (Fri after 3-day gap) + Nov seasonality
hh = [row(datetime(2026, 11, 24) - timedelta(days=300 - i)) for i in range(301)]
rr = pms.kedia_sa_read(hh, today=datetime(2026, 11, 27))
check("post-holiday trap warning", "after a holiday" in txt(rr))
check("November seasonality line", "November to mid-December" in txt(rr))
check("html: no raw ampersand or stray angle bracket",
      "&" not in txt(rr) and all(l.count("<") == l.count(">") for l in rr["lines"]))

# fallback when sheet lacks DEMA columns
nod = [{k: v for k, v in x.items() if k != "pct_ab_10"} for x in base]
check("works without 10-DEMA columns", pms.kedia_sa_read(nod, today=days[-1] + timedelta(days=1))["available"])
print(f"test_kedia_sa: ALL OK ({PASS[0]} PASS)")
