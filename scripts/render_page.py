#!/usr/bin/env python3
"""
render_page.py - build a browsable HTML page for one airport.

    python3 render_page.py KATL --amenities --out /tmp/katl.html
    xdg-open /tmp/katl.html

A self-contained, theme-aware document: runway diagram, specs, frequencies,
procedures, weather, and a searchable food/shops/lounges browser. No server
and no assets - everything is inline except the Google Fonts stylesheet.
"""

import argparse
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apt  # noqa: E402


def esc(value):
    return html.escape(str(value if value is not None else ""))


# --------------------------------------------------------------------------
# Design tokens
#
# Palette is lifted from the aeronautical chart it is imitating: sectional
# magenta for the accent, controlled-airspace blue as the secondary, asphalt
# grey for runways, and the FAA's own flight-category colors for the weather
# chip. Neutrals carry a slight blue-green bias so they read as chosen.
# --------------------------------------------------------------------------

CSS = """
:root {
  --paper:#eef1f0; --panel:#f108; --card:#fbfcfc; --ink:#131a1e; --ink-2:#3b4750;
  --muted:#6a7780; --rule:#d3dad8; --rule-2:#e3e8e6;
  --magenta:#b0156a; --magenta-soft:#f6e3ee; --blue:#1b5e8c; --blue-soft:#e2ecf3;
  --rwy:#39424b; --cl:#ffffff;
  --vfr:#0f7a45; --mvfr:#1b5e8c; --ifr:#bc2026; --lifr:#8e2c86;
  --shadow:0 1px 2px rgba(19,26,30,.06), 0 8px 24px -12px rgba(19,26,30,.18);
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:"IBM Plex Sans",system-ui,-apple-system,Segoe UI,sans-serif;
  --display:"Archivo","IBM Plex Sans",system-ui,sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper:#0e1315; --card:#161d20; --ink:#e6ecea; --ink-2:#b8c4c2;
    --muted:#87969a; --rule:#273134; --rule-2:#1e2629;
    --magenta:#f06bab; --magenta-soft:#2b1522; --blue:#6fb2dc; --blue-soft:#11242f;
    --rwy:#5d6a74; --cl:#0e1315;
    --vfr:#3fbc79; --mvfr:#6fb2dc; --ifr:#f2666b; --lifr:#d98ad2;
    --shadow:0 1px 2px rgba(0,0,0,.5), 0 8px 24px -12px rgba(0,0,0,.7);
  }
}
:root[data-theme="dark"] {
  --paper:#0e1315; --card:#161d20; --ink:#e6ecea; --ink-2:#b8c4c2;
  --muted:#87969a; --rule:#273134; --rule-2:#1e2629;
  --magenta:#f06bab; --magenta-soft:#2b1522; --blue:#6fb2dc; --blue-soft:#11242f;
  --rwy:#5d6a74; --cl:#0e1315;
  --vfr:#3fbc79; --mvfr:#6fb2dc; --ifr:#f2666b; --lifr:#d98ad2;
  --shadow:0 1px 2px rgba(0,0,0,.5), 0 8px 24px -12px rgba(0,0,0,.7);
}

* { box-sizing:border-box; }
body {
  background:var(--paper); color:var(--ink); font-family:var(--sans);
  font-size:15px; line-height:1.55; margin:0;
  -webkit-font-smoothing:antialiased;
}
.wrap { max-width:1120px; margin:0 auto; padding:32px 24px 96px; }

/* ---- masthead ---- */
.mast { display:flex; flex-wrap:wrap; align-items:flex-end; gap:20px 28px;
        padding-bottom:20px; border-bottom:2px solid var(--ink); }
.ident { font-family:var(--display); font-weight:700; font-size:clamp(44px,8vw,76px);
         line-height:.88; letter-spacing:-.03em; margin:0; text-wrap:balance; }
.ident span { color:var(--magenta); }
.mast-meta { flex:1 1 260px; min-width:0; }
.apt-name { font-family:var(--display); font-weight:600; font-size:19px;
            letter-spacing:-.01em; margin:0 0 2px; text-wrap:balance; }
.apt-where { color:var(--muted); font-size:14px; margin:0; }
.chip {
  display:inline-flex; align-items:center; gap:7px; padding:5px 11px;
  border-radius:3px; font-family:var(--mono); font-size:12px; font-weight:600;
  letter-spacing:.06em; text-transform:uppercase; white-space:nowrap;
}
.chip.cat { color:var(--cl); }
.cat-VFR { background:var(--vfr); } .cat-MVFR { background:var(--mvfr); }
.cat-IFR { background:var(--ifr); } .cat-LIFR { background:var(--lifr); }
.cat-none { background:var(--muted); }

/* ---- vitals ---- */
.vitals { display:grid; gap:0; background:var(--card);
          grid-template-columns:repeat(auto-fit,minmax(132px,1fr));
          border-top:1px solid var(--rule); border-left:1px solid var(--rule);
          margin:0 0 40px; }
.vital { padding:12px 14px;
         border-right:1px solid var(--rule); border-bottom:1px solid var(--rule); }
.vital dt { font-family:var(--mono); font-size:10.5px; letter-spacing:.1em;
            text-transform:uppercase; color:var(--muted); margin:0 0 3px; }
.vital dd { font-family:var(--display); font-weight:600; font-size:19px;
            margin:0; font-variant-numeric:tabular-nums; letter-spacing:-.01em; }
.vital dd small { font-size:12px; font-weight:500; color:var(--muted); }

/* ---- sections ---- */
section { margin:0 0 44px; scroll-margin-top:16px; }
h2 { font-family:var(--display); font-size:13px; font-weight:700;
     letter-spacing:.14em; text-transform:uppercase; color:var(--ink-2);
     margin:0 0 14px; padding-bottom:7px; border-bottom:1px solid var(--rule);
     display:flex; align-items:baseline; gap:10px; }
h2 .count { font-family:var(--mono); font-weight:500; color:var(--muted);
            letter-spacing:.04em; }
h3 { font-family:var(--display); font-size:15px; font-weight:600; margin:22px 0 8px;
     letter-spacing:-.01em; }

.scroller { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:14px; min-width:520px; }
th { font-family:var(--mono); font-size:10.5px; letter-spacing:.09em;
     text-transform:uppercase; color:var(--muted); text-align:left;
     font-weight:500; padding:0 14px 7px 0; white-space:nowrap; }
td { padding:9px 14px 9px 0; border-top:1px solid var(--rule-2);
     vertical-align:top; font-variant-numeric:tabular-nums; }
td.num { white-space:nowrap; }
.rwy-id { font-family:var(--display); font-weight:700; font-size:16px;
          letter-spacing:.01em; white-space:nowrap; }
.tag { font-family:var(--mono); font-size:11px; padding:1px 6px; border-radius:2px;
       background:var(--blue-soft); color:var(--blue); white-space:nowrap;
       display:inline-block; margin:0 4px 3px 0; }
.tag.warn { background:var(--magenta-soft); color:var(--magenta); }

/* ---- diagram ---- */
.diagram { background:var(--card); border:1px solid var(--rule);
           box-shadow:var(--shadow); padding:8px; margin:0 0 8px; }
.diagram svg { display:block; width:100%; height:auto; }
.figcap { font-family:var(--mono); font-size:11px; color:var(--muted);
          margin:0 0 22px; }

/* ---- metar ---- */
.metar { font-family:var(--mono); font-size:13.5px; line-height:1.7;
         background:var(--card); border:1px solid var(--rule);
         border-left:3px solid var(--magenta); padding:13px 15px;
         overflow-x:auto; white-space:pre-wrap; word-break:break-word; margin:0 0 12px; }
.wx-facts { display:flex; flex-wrap:wrap; gap:6px 18px; font-size:13.5px;
            color:var(--ink-2); margin:0 0 4px; font-variant-numeric:tabular-nums; }
.wx-facts b { font-weight:600; color:var(--ink); }

/* ---- filters ---- */
.controls { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:0 0 16px; }
.search { flex:1 1 220px; min-width:170px; font:inherit; font-size:14px;
          padding:8px 11px; border:1px solid var(--rule); border-radius:3px;
          background:var(--card); color:var(--ink); }
.search:focus-visible, .filter:focus-visible, .proc-f:focus-visible {
  outline:2px solid var(--magenta); outline-offset:1px; }
.filter, .proc-f {
  font-family:var(--mono); font-size:11.5px; letter-spacing:.05em;
  text-transform:uppercase; padding:6px 11px; border:1px solid var(--rule);
  background:var(--card); color:var(--ink-2); border-radius:3px; cursor:pointer;
}
.filter[aria-pressed="true"], .proc-f[aria-pressed="true"] {
  background:var(--ink); color:var(--paper); border-color:var(--ink);
}
.group-head { font-family:var(--display); font-weight:700; font-size:12px;
              letter-spacing:.12em; text-transform:uppercase; color:var(--magenta);
              margin:26px 0 8px; padding-bottom:5px;
              border-bottom:1px solid var(--rule-2); }
.group-head:first-of-type { margin-top:6px; }
.poi { display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 12px;
       padding:7px 0; border-top:1px solid var(--rule-2); }
.poi-name { font-weight:600; flex:0 1 auto; }
.poi-meta { color:var(--muted); font-size:13px; }
.poi-hours { font-family:var(--mono); font-size:12px; color:var(--ink-2);
             margin-left:auto; white-space:nowrap; }
.empty { color:var(--muted); font-style:italic; padding:14px 0; }

/* ---- links / lists ---- */
a { color:var(--magenta); text-underline-offset:2px; }
a:hover { text-decoration-thickness:2px; }
.proc-row { display:flex; flex-wrap:wrap; gap:4px 12px; align-items:baseline;
            padding:7px 0; border-top:1px solid var(--rule-2); }
.proc-rwy { font-family:var(--mono); font-size:11.5px; letter-spacing:.06em;
            color:var(--muted); min-width:74px; text-transform:uppercase; }
.proc-name { font-weight:500; }
.cont { font-family:var(--mono); font-size:11.5px; color:var(--muted); }

.notes { background:var(--magenta-soft); border:1px solid var(--rule);
         border-left:3px solid var(--magenta); padding:14px 17px; }
.notes ul { margin:0; padding-left:19px; }
.notes li { margin:4px 0; }
.notes h3 { margin-top:0; }

.remarks li { margin:5px 0; }
.remarks { font-size:14px; color:var(--ink-2); padding-left:19px; margin:0; }

footer { border-top:2px solid var(--ink); padding-top:16px; margin-top:52px;
         font-size:13px; color:var(--muted); }
footer .warn { font-family:var(--display); font-weight:700; letter-spacing:.06em;
               text-transform:uppercase; color:var(--magenta); font-size:12.5px;
               display:block; margin-bottom:7px; }
footer a { color:var(--blue); }
.srcs { display:flex; flex-wrap:wrap; gap:6px 16px; margin:10px 0 0; padding:0;
        list-style:none; font-family:var(--mono); font-size:11.5px; }

@media (max-width:620px) {
  .wrap { padding:22px 15px 72px; }
  .poi-hours { margin-left:0; flex-basis:100%; }
}
@media (prefers-reduced-motion:reduce) { * { transition:none !important; } }
"""

FONTS = ('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=Archivo:wght@600;700&family=IBM+Plex+Mono:wght@400;500;600&'
         'family=IBM+Plex+Sans:wght@400;500;600&display=swap">')


# --------------------------------------------------------------------------
# Fragments
# --------------------------------------------------------------------------

def vitals_block(rec, faa, metar, freqs, tpa=""):
    items = []

    def add(label, value, sub=""):
        if value not in (None, "", "-"):
            items.append("<div class='vital'><dt>%s</dt><dd>%s%s</dd></div>"
                         % (esc(label), esc(value),
                            "<small> %s</small>" % esc(sub) if sub else ""))

    add("Field elevation", apt.fmt_ft(rec["elev"]) if rec["elev"] is not None else "")
    if tpa:
        add("Pattern altitude", tpa if len(tpa) < 22 else "see remarks",
            "" if len(tpa) < 22 else "")
    ctaf = apt.pick_freq(freqs, "CTAF")
    twr = apt.pick_freq(freqs, "LCL")
    if ctaf:
        add("CTAF", ctaf["freq"])
    if twr:
        add("Tower", twr["freq"])
    gnd = apt.pick_freq(freqs, "GND")
    if gnd:
        add("Ground", gnd["freq"])
    atis = apt.pick_freq(freqs, "ATIS", "ASOS", "AWOS")
    if atis:
        add(atis["use"].split("/")[0] or "ATIS", atis["freq"])
    fuels = apt.decode_fuel(faa.get("FUEL_TYPES", ""))
    add("Fuel", ", ".join(fuels) if fuels else "None")
    if faa.get("LNDG_FEE_FLAG"):
        add("Landing fee", "Yes" if faa["LNDG_FEE_FLAG"] == "Y" else "No")
    if faa.get("MAG_VARN"):
        add("Magnetic var", "%s°%s" % (faa["MAG_VARN"], faa.get("MAG_HEMIS", "")))
    if isinstance(metar, dict) and metar.get("temp") is not None and rec["elev"] is not None:
        alt = metar.get("altim")
        if alt:
            pa = rec["elev"] + (29.92 - alt / 33.8639) * 1000
            isa = 15 - 2 * (rec["elev"] / 1000.0)
            add("Density altitude", apt.fmt_ft(pa + 120 * (metar["temp"] - isa)))
    if not items:
        return ""
    return "<dl class='vitals'>%s</dl>" % "".join(items)


def runway_section(rec, runways, svg):
    if not runways:
        return ""
    out = ["<section id='runways'><h2>Runways <span class='count'>%d</span></h2>"
           % len(runways)]
    if svg:
        out.append("<figure class='diagram'>%s</figure>" % svg)
        out.append("<p class='figcap'>Plotted from FAA runway-end coordinates. "
                   "Not to be used for navigation or taxi planning.</p>")
    out.append("<div class='scroller'><table><thead><tr>"
               "<th>Rwy</th><th>Dimensions</th><th>Surface</th><th>Lighting</th>"
               "<th>Ends</th></tr></thead><tbody>")
    for r in runways:
        ends = []
        for e in r.get("ends", []):
            tags = []
            if e.get("ils"):
                tags.append(e["ils"])
            if e.get("approach_lights"):
                tags.append(e["approach_lights"])
            if e.get("vgsi") and e["vgsi"] != "none":
                tags.append(e["vgsi"])
            warn = []
            if e.get("displaced_thr"):
                warn.append("displaced thr %s" % apt.fmt_ft(e["displaced_thr"]))
            if e.get("right_traffic") == "Y":
                warn.append("right traffic")
            if e.get("lda") and r.get("length") and \
                    (apt._fnum(e["lda"]) or 0) < (apt._fnum(r["length"]) or 0):
                warn.append("LDA %s" % apt.fmt_ft(e["lda"]))
            chips = "".join("<span class='tag'>%s</span>" % esc(t) for t in tags)
            chips += "".join("<span class='tag warn'>%s</span>" % esc(w) for w in warn)
            ends.append("<div><span class='rwy-id'>%s</span>%s%s</div>"
                        % (esc(e["id"]), "&nbsp;&nbsp;" if chips else "", chips))
        out.append(
            "<tr><td class='rwy-id'>%s</td><td class='num'>%s &times; %s</td>"
            "<td>%s</td><td>%s</td><td>%s</td></tr>" % (
                esc(r["id"]), apt.fmt_ft(r["length"]), apt.fmt_ft(r["width"]),
                esc(r.get("surface", "")), esc(r.get("lighting", "") or "—"),
                "".join(ends) or "—"))
    out.append("</tbody></table></div></section>")
    return "".join(out)


def freq_section(freqs):
    rows = []
    seen = set()
    for f in freqs:
        if f["uhf"]:
            continue
        key = (f["freq"], f["use"])
        if key in seen:
            continue
        seen.add(key)
        hours = re.sub(r"\s+", " ", f["tower_hours"]) if f["tower_hours"] else ""
        rows.append("<tr><td class='num'><b>%s</b></td><td>%s</td><td>%s</td>"
                    "<td>%s</td></tr>" % (esc(f["freq"]), esc(f["use"]),
                                          esc(f["fac_type"]), esc(hours)))
    if not rows:
        return ""
    return ("<section id='freqs'><h2>Frequencies <span class='count'>%d</span></h2>"
            "<div class='scroller'><table><thead><tr><th>Freq</th><th>Use</th>"
            "<th>Facility</th><th>Hours</th></tr></thead><tbody>%s</tbody></table>"
            "</div></section>" % (len(rows), "".join(rows)))


def procedures_section(procs):
    approaches = procs.get("approaches") or []
    buckets = [("departures", "Departures (SIDs)"),
               ("obstacle_departures", "Obstacle departures"),
               ("arrivals", "Arrivals (STARs)"),
               ("diverse_vector", "Diverse vector area"),
               ("minimums", "Takeoff &amp; alternate minimums"),
               ("hot_spots", "Hot spots"), ("lahso", "LAHSO"), ("other", "Other")]
    total = len(approaches) + sum(len(procs.get(b) or []) for b, _ in buckets)
    if not total:
        return ""

    out = ["<section id='procedures'><h2>Instrument procedures "
           "<span class='count'>%d &middot; cycle %s, expires %s</span></h2>"
           % (total, esc(procs.get("cycle", "")), esc(procs.get("expires", "")))]

    diagram = procs.get("airport_diagram") or []
    if diagram:
        out.append("<div class='proc-row'><span class='proc-rwy'>Diagram</span>"
                   "<a class='proc-name' href='%s'>Airport Diagram (APD)</a></div>"
                   % esc(diagram[0]["url"]))

    if approaches:
        runways = sorted({a["runway"] for a in approaches if a["runway"]},
                         key=lambda r: (int(re.sub(r"[^0-9]", "", r) or 99), r))
        chips = "".join(
            "<button class='proc-f' type='button' data-rwy='%s' aria-pressed='false'>"
            "%s</button>" % (esc(r), esc(r)) for r in runways)
        out.append("<h3>Approaches</h3>")
        if chips:
            out.append("<div class='controls'>"
                       "<button class='proc-f' type='button' data-rwy='' "
                       "aria-pressed='true'>All runways</button>%s</div>" % chips)
        for a in approaches:
            label = a["runway"] or ("circling" if a["circling"] else "all rwys")
            conts = "".join(
                " <a class='cont' href='%s'>cont.%d</a>" % (esc(u), i + 1)
                for i, u in enumerate(a["pages"]))
            out.append("<div class='proc-row' data-rwy='%s'>"
                       "<span class='proc-rwy'>%s</span>"
                       "<a class='proc-name' href='%s'>%s</a>%s</div>"
                       % (esc(a["runway"]), esc(label), esc(a["url"]),
                          esc(a["name"]), conts))

    for key, title in buckets:
        items = procs.get(key) or []
        if not items:
            continue
        out.append("<h3>%s <span class='count'>%d</span></h3>" % (title, len(items)))
        for item in items:
            conts = "".join(
                " <a class='cont' href='%s'>cont.%d</a>" % (esc(u), i + 1)
                for i, u in enumerate(item["pages"]))
            out.append("<div class='proc-row'><a class='proc-name' href='%s'>%s</a>%s"
                       "</div>" % (esc(item["url"]), esc(item["name"]), conts))
    if procs.get("cs"):
        out.append("<div class='proc-row'><span class='proc-rwy'>Supplement</span>"
                   "<a class='proc-name' href='%s'>Chart Supplement page</a></div>"
                   % esc(procs["cs"]))
    out.append("</section>")
    return "".join(out)


def wx_section(rec, metar, taf, twilight):
    if not metar and not taf:
        return ""
    out = ["<section id='weather'><h2>Weather</h2>"]
    if isinstance(metar, dict) and metar.get("rawOb"):
        out.append("<div class='metar'>%s</div>" % esc(metar["rawOb"]))
        facts = []
        if metar.get("temp") is not None:
            facts.append("<span>Temp <b>%.0f&deg;C</b></span>" % metar["temp"])
        if metar.get("dewp") is not None:
            facts.append("<span>Dewpoint <b>%.0f&deg;C</b></span>" % metar["dewp"])
        if metar.get("wdir") is not None:
            facts.append("<span>Wind <b>%s&deg; @ %s kt</b></span>"
                         % (metar["wdir"], metar.get("wspd")))
        if metar.get("visib"):
            facts.append("<span>Visibility <b>%s sm</b></span>" % esc(metar["visib"]))
        if metar.get("altim"):
            facts.append("<span>Altimeter <b>%.2f inHg</b></span>"
                         % (metar["altim"] / 33.8639))
        if facts:
            out.append("<p class='wx-facts'>%s</p>" % "".join(facts))
    elif isinstance(metar, dict) and metar.get("error"):
        out.append("<p class='empty'>METAR unavailable: %s</p>" % esc(metar["error"]))
    else:
        out.append("<p class='empty'>No weather station reports for this field.</p>")

    if isinstance(taf, dict) and taf.get("rawTAF"):
        lines = re.split(r"\s+(?=FM\d|TEMPO|BECMG|PROB)", taf["rawTAF"])
        out.append("<h3>Forecast</h3><div class='metar'>%s</div>"
                   % esc("\n".join(l.strip() for l in lines)))
    if twilight:
        out.append("<p class='wx-facts'><span>Civil twilight <b>%s&ndash;%sZ</b></span>"
                   "<span>Sunrise <b>%sZ</b></span><span>Sunset <b>%sZ</b></span></p>"
                   % (twilight["civil_twilight_begin"][11:16],
                      twilight["civil_twilight_end"][11:16],
                      twilight["sunrise"][11:16], twilight["sunset"][11:16]))
    out.append("</section>")
    return "".join(out)


def amenities_section(data):
    pois = data.get("pois") or []
    if not pois:
        return ""
    terminals = sorted({p["terminal"] for p in pois if p["terminal"]})
    kinds = [("food", "Food &amp; drink"), ("lounge", "Lounges"),
             ("shop", "Shops"), ("service", "Services")]
    present = [(k, label) for k, label in kinds if any(p["kind"] == k for p in pois)]

    chips = ["<button class='filter' type='button' data-kind='' aria-pressed='true'>"
             "Everything</button>"]
    chips += ["<button class='filter' type='button' data-kind='%s' aria-pressed='false'>"
              "%s</button>" % (k, label) for k, label in present]
    term_chips = ""
    if terminals:
        term_chips = ("<div class='controls'>"
                      "<button class='filter' type='button' data-term='' "
                      "aria-pressed='true'>All areas</button>%s</div>"
                      % "".join("<button class='filter' type='button' data-term='%s' "
                                "aria-pressed='false'>%s</button>" % (esc(t), esc(t))
                                for t in terminals))

    rows = []
    groups = {}
    for poi in pois:
        groups.setdefault(poi["terminal"] or "Elsewhere on the field", []).append(poi)
    for group in sorted(groups, key=lambda g: (g == "Elsewhere on the field", g)):
        rows.append("<div class='group-head' data-group='%s'>%s <span class='count'>"
                    "%d</span></div>" % (esc(group), esc(group), len(groups[group])))
        for poi in sorted(groups[group], key=lambda p: (p["kind"], p["name"])):
            meta = []
            if poi["kind"] == "lounge":
                meta.append("lounge")
            if poi["cuisine"]:
                meta.append(poi["cuisine"].replace(";", ", "))
            elif poi["shop"]:
                meta.append(poi["shop"].replace("_", " "))
            elif poi["amenity"]:
                meta.append(poi["amenity"].replace("_", " "))
            if poi["level"]:
                meta.append("level %s" % poi["level"])
            haystack = " ".join([poi["name"], poi["cuisine"], poi["shop"],
                                 poi["amenity"], poi["operator"] or ""]).lower()
            rows.append(
                "<div class='poi' data-kind='%s' data-term='%s' data-q='%s'>"
                "<span class='poi-name'>%s</span>"
                "<span class='poi-meta'>%s</span>"
                "<span class='poi-hours'>%s</span></div>"
                % (esc(poi["kind"]), esc(poi["terminal"]), esc(haystack),
                   esc(poi["name"]), " &middot; ".join(esc(m) for m in meta),
                   esc(poi["hours"])))

    return ("<section id='amenities'><h2>Food, shops &amp; lounges "
            "<span class='count'>%d mapped</span></h2>"
            "<div class='controls'>"
            "<input class='search' id='poi-q' type='search' "
            "placeholder='Search by name or cuisine&hellip;' "
            "aria-label='Search amenities'>%s</div>%s"
            "<div id='poi-list'>%s</div>"
            "<p class='empty' id='poi-none' hidden>Nothing matches those filters.</p>"
            "</section>" % (len(pois), "".join(chips), term_chips, "".join(rows)))


def notes_section(notes):
    if not notes.strip():
        return ""
    items = []
    heading = ""
    for line in notes.splitlines():
        line = line.strip()
        if line.startswith("#"):
            heading = line.lstrip("# ").strip()
        elif line.startswith(("- ", "* ")):
            items.append("<li>%s</li>" % esc(line[2:]))
        elif line:
            items.append("<li>%s</li>" % esc(line))
    return ("<section id='notes'><h2>Your notes</h2><div class='notes'>%s<ul>%s</ul>"
            "</div></section>" % ("<h3>%s</h3>" % esc(heading) if heading else "",
                                  "".join(items)))


def remarks_section(remarks):
    if not remarks:
        return ""
    return ("<section id='remarks'><h2>FAA remarks <span class='count'>%d</span></h2>"
            "<ul class='remarks'>%s</ul></section>"
            % (len(remarks), "".join("<li>%s</li>" % esc(r) for r in remarks)))


JS = """
(function () {
  var kind = '', term = '', q = '';
  var list = document.getElementById('poi-list');
  var none = document.getElementById('poi-none');
  function press(btn, on) { btn.setAttribute('aria-pressed', on ? 'true' : 'false'); }

  function applyPois() {
    if (!list) return;
    var shown = 0;
    list.querySelectorAll('.poi').forEach(function (el) {
      var ok = (!kind || el.dataset.kind === kind)
        && (!term || el.dataset.term === term)
        && (!q || el.dataset.q.indexOf(q) !== -1);
      el.hidden = !ok;
      if (ok) shown++;
    });
    list.querySelectorAll('.group-head').forEach(function (head) {
      var any = false, el = head.nextElementSibling;
      while (el && !el.classList.contains('group-head')) {
        if (el.classList.contains('poi') && !el.hidden) { any = true; break; }
        el = el.nextElementSibling;
      }
      head.hidden = !any;
    });
    if (none) none.hidden = shown !== 0;
  }

  document.querySelectorAll('.filter[data-kind]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      kind = btn.dataset.kind;
      document.querySelectorAll('.filter[data-kind]').forEach(function (b) {
        press(b, b === btn);
      });
      applyPois();
    });
  });
  document.querySelectorAll('.filter[data-term]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      term = btn.dataset.term;
      document.querySelectorAll('.filter[data-term]').forEach(function (b) {
        press(b, b === btn);
      });
      applyPois();
    });
  });
  var search = document.getElementById('poi-q');
  if (search) {
    search.addEventListener('input', function () {
      q = search.value.trim().toLowerCase();
      applyPois();
    });
  }

  document.querySelectorAll('.proc-f').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var want = btn.dataset.rwy;
      document.querySelectorAll('.proc-f').forEach(function (b) { press(b, b === btn); });
      document.querySelectorAll('.proc-row[data-rwy]').forEach(function (row) {
        row.hidden = !!want && row.dataset.rwy !== want && row.dataset.rwy !== '';
      });
    });
  });
})();
"""


def build(rec, payload, amenities):
    faa = rec["faa"] or {}
    ident = rec["icao"] or rec["id"]
    metar = payload.get("metar")
    cat = (metar or {}).get("fltCat") if isinstance(metar, dict) else None
    runways = payload["runways"]
    svg = apt.runway_svg(rec, runways)

    where = ", ".join(x for x in (rec["city"], rec["state_name"] or rec["state"]) if x)
    site = apt.SITE_TYPES.get(rec["site_type"], "")
    subtitle = " &middot; ".join(x for x in (where, site) if x)

    head = ["<div class='mast'>",
            "<h1 class='ident'>%s<span>%s</span></h1>" % (esc(ident[:1]), esc(ident[1:]))
            if len(ident) > 1 else "<h1 class='ident'>%s</h1>" % esc(ident),
            "<div class='mast-meta'><p class='apt-name'>%s</p>"
            "<p class='apt-where'>%s%s</p></div>" % (
                esc(rec["name"]), subtitle,
                " &middot; FAA %s" % esc(rec["id"]) if rec["id"] != ident else ""),
            "<span class='chip cat cat-%s'>%s</span>" % (esc(cat or "none"),
                                                         esc(cat or "no report")),
            "</div>"]

    links = payload.get("links", {})
    src_items = ["<li><a href='%s'>%s</a></li>" % (esc(v), esc(k.replace("_", " ")))
                 for k, v in links.items()]

    body = [
        "".join(head),
        vitals_block(rec, faa, metar, payload["frequencies"],
                     payload.get("pattern_altitude", "")),
        runway_section(rec, runways, svg),
        freq_section(payload["frequencies"]),
        procedures_section(payload.get("procedures") or {}),
        wx_section(rec, metar, payload.get("taf"), payload.get("twilight")),
        amenities_section(amenities) if amenities else "",
        notes_section(payload.get("notes") or ""),
        remarks_section(payload.get("remarks") or []),
        "<footer><span class='warn'>Not for navigation</span>"
        "Reference only. Verify every figure against current FAA publications and "
        "obtain an official preflight briefing including NOTAMs and TFRs before any "
        "flight. Airport and runway data from the FAA NASR 28-day subscription; "
        "charts from FAA d-TPP; weather from aviationweather.gov; amenities from "
        "OpenStreetMap contributors (ODbL). %s"
        "<ul class='srcs'>%s</ul></footer>" % (esc(payload.get("cycle", "")),
                                               "".join(src_items)),
    ]

    return ("<!doctype html>\n<html lang='en'>\n<head>\n<meta charset='utf-8'>\n"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>\n"
            "<title>%s Airport Brief</title>\n%s\n<style>\n"
            "*{box-sizing:border-box}img{max-width:100%%}[hidden]{display:none!important}\n"
            "%s</style>\n</head>\n<body>\n"
            "<div class='wrap'>%s</div>\n<script>%s</script>\n</body>\n</html>\n"
            % (esc(ident), FONTS, CSS, "".join(body), JS))


def main():
    p = argparse.ArgumentParser(description="Render an airport Artifact page.")
    p.add_argument("airport")
    p.add_argument("--amenities", action="store_true",
                   help="include the food/shops/lounges browser")
    p.add_argument("--no-live", action="store_true", help="skip weather fetches")
    p.add_argument("--out", required=True, help="path to write the HTML to")
    args = p.parse_args()

    conn = apt.db_connect()
    rec = apt.need_airport(conn, args.airport)
    payload = {
        "cycle": apt.cycle_note(conn),
        "runways": apt.get_runways(conn, rec),
        "frequencies": apt.get_freqs(conn, rec),
        "pattern_altitude": apt.pattern_altitude(conn, rec),
        "procedures": apt.get_procedures(conn, rec),
        "remarks": apt.get_remarks(conn, rec),
        "notes": apt.read_notes(rec["id"]),
        "links": apt.official_links(rec),
    }
    if not args.no_live:
        station = apt.wx_ident(rec)
        payload["metar"] = apt.fetch_metar(station)
        payload["taf"] = apt.fetch_taf(station)
        if rec["lat"] is not None:
            payload["twilight"] = apt.fetch_twilight(rec["lat"], rec["lon"])

    amenities = apt.fetch_amenities(rec) if args.amenities else None
    if amenities and amenities.get("error"):
        print("warning: amenities unavailable (%s)" % amenities["error"], file=sys.stderr)
        amenities = None

    Path(args.out).write_text(build(rec, payload, amenities), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
