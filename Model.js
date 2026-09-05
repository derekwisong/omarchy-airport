.pragma library

// Flight-category colors are the FAA's own encoding, not theme decoration:
// green VFR, blue MVFR, red IFR, magenta LIFR. Pilots read these by color
// before they read the letters, so they stay fixed across themes.
var CATEGORY_COLORS = {
  VFR: "#3fbc79",
  MVFR: "#4a9fd8",
  IFR: "#e2565c",
  LIFR: "#d17ad0"
}

function categoryColor(category, fallback) {
  return CATEGORY_COLORS[String(category || "").toUpperCase()] || fallback
}

function feet(value) {
  if (value === null || value === undefined || value === "") return ""
  var n = Number(value)
  if (isNaN(n)) return String(value)
  return Math.round(n).toLocaleString(Qt.locale("en_US"), "f", 0) + "'"
}

// ---- helpers for the panel tabs -------------------------------------------

function runwayRows(data) {
  var list = (data && data.runways) || []
  var rows = []
  for (var i = 0; i < list.length; i++) {
    var r = list[i]
    var spec = []
    if (r.surface) spec.push(r.surface)
    if (r.lighting && r.lighting !== "none") spec.push(r.lighting)
    rows.push({ runway: true, id: r.id,
                dims: feet(r.length) + " × " + feet(r.width),
                spec: spec.join("  ·  ") })
    var ends = r.ends || []
    for (var j = 0; j < ends.length; j++) {
      var e = ends[j], tags = []
      if (e.true_align) tags.push(e.true_align + "°T")
      if (e.ils) tags.push(e.ils)
      if (e.approach_lights) tags.push(e.approach_lights)
      if (e.vgsi && e.vgsi !== "none") tags.push(e.vgsi)
      if (e.displaced_thr) tags.push("displaced thr " + feet(e.displaced_thr))
      if (e.right_traffic === "Y") tags.push("right traffic")
      if (e.lda && r.length && Number(e.lda) < Number(r.length))
        tags.push("LDA " + feet(e.lda))
      rows.push({ runway: false, id: e.id, dims: "", spec: tags.join("  ·  "),
                  obstruction: e.obstruction
                    ? (e.obstruction.toLowerCase()
                       + (e.obst_height ? " " + e.obst_height + "' high" : "")
                       + (e.obst_dist ? " at " + e.obst_dist + "'" : "")
                       + (e.obst_slope ? ", " + e.obst_slope + ":1" : ""))
                    : "" })
    }
  }
  return rows
}

// Procedures grouped the way a pilot briefs them, with real headings so the
// page does not read as one undifferentiated block of links.
function procedureRows(procs, us) {
  if (!procs) return []
  var rows = []
  function heading(text) { rows.push({ heading: true, label: text, url: "" }) }
  function sub(text) { rows.push({ sub: true, label: text, url: "" }) }
  function item(name, url, pages) {
    rows.push({ label: name, url: url || "", pages: pages || [] })
  }

  var diagram = procs.airport_diagram || []
  if (diagram.length) {
    heading("AIRPORT DIAGRAM")
    item("Airport diagram", diagram[0].url)
  }

  var approaches = procs.approaches || []
  if (approaches.length) {
    heading("APPROACHES  (" + approaches.length + ")")
    var lastRwy = null
    for (var i = 0; i < approaches.length; i++) {
      var a = approaches[i]
      var rwy = a.runway ? "Runway " + a.runway
        : (a.circling ? "Circling" : "All runways")
      if (rwy !== lastRwy) { sub(rwy); lastRwy = rwy }
      item(a.name, a.url, a.pages)
    }
  }

  var groups = [["departures", "DEPARTURES  (SIDs)"],
                ["obstacle_departures", "OBSTACLE DEPARTURES"],
                ["arrivals", "ARRIVALS  (STARs)"],
                ["diverse_vector", "DIVERSE VECTOR AREA"],
                ["minimums", "TAKEOFF & ALTERNATE MINIMUMS"],
                ["hot_spots", "HOT SPOTS"],
                ["lahso", "LAHSO"],
                ["other", "OTHER"]]
  for (var g = 0; g < groups.length; g++) {
    var items = procs[groups[g][0]] || []
    if (!items.length) continue
    heading(groups[g][1] + (items.length > 1 ? "  (" + items.length + ")" : ""))
    for (var j = 0; j < items.length; j++) item(items[j].name, items[j].url, items[j].pages)
  }

  if (procs.cs) {
    heading("CHART SUPPLEMENT")
    item("Chart Supplement page", procs.cs)
  }
  if (!rows.length)
    rows.push({ note: true, url: "", label: us === false
      ? "FAA terminal procedures cover US airports only. For this airport, see the "
        + "national AIP."
      : "No published instrument procedures — this is a VFR-only field." })
  else if (procs.expires)
    rows.push({ note: true, label: "Cycle " + (procs.cycle || "") + " · expires "
                + procs.expires + " · verify currency before use", url: "" })
  return rows
}


function groundRows(g) {
  if (!g) return []
  if (!(g.attended || []).length && !(g.fuel || []).length
      && !(g.contacts || []).length && !(g.services || []).length)
    return [{ k: "", v: "No ground service data published for this airport." }]
  var rows = []
  function add(k, v) { if (v) rows.push({ k: k, v: v }) }
  add("Attended", (g.attended || []).join(" · "))
  add("Fuel", (g.fuel || []).join(", "))
  add("Landing fee", g.landing_fee === "Y" ? "yes (amount not published)"
      : (g.landing_fee === "N" ? "no" : ""))
  var parking = []
  if (g.hangar) parking.push("hangar")
  if (g.tiedown) parking.push("tiedown")
  add("Transient parking", parking.join(", "))
  add("Customs", g.customs ? "available" : "")
  add("Services", (g.services || []).join(", "))
  var contacts = g.contacts || []
  for (var i = 0; i < contacts.length && i < 3; i++) {
    var c = contacts[i]
    add(String(c.title || "").toLowerCase().replace(/^./, function (m) { return m.toUpperCase() }),
        [c.name, c.phone].filter(function (x) { return !!x }).join("  ·  "))
  }
  var fbo = g.fbo_remarks || []
  for (var j = 0; j < fbo.length; j++) add(j === 0 ? "FAA remark" : "", fbo[j])
  return rows
}

function fuelPrices(f) {
  var p = (f && f.prices) || []
  if (!p.length) return ""
  var parts = []
  for (var i = 0; i < p.length; i++)
    parts.push(p[i].fuel + " $" + p[i].price + " " + p[i].service)
  var line = parts.join("   ")
  if (f.prices_updated) line += "   (" + f.prices_updated + ")"
  return line
}

function terminalChips(a) {
  if (!a || !a.pois) return []
  var seen = {}, out = ["All"]
  for (var i = 0; i < a.pois.length; i++) {
    var t = a.pois[i].terminal
    if (t && !seen[t]) { seen[t] = true; out.push(t) }
  }
  return out.length > 1 ? out : []
}

// Grouped, filtered amenity rows as structured columns, so the page can lay
// them out as a table rather than one long pre-formatted string.
function amenityRows(a, terminal) {
  if (!a || !a.pois || !a.pois.length) return []
  var groups = {}, order = []
  for (var i = 0; i < a.pois.length; i++) {
    var p = a.pois[i]
    if (terminal && p.terminal !== terminal) continue
    var key = p.terminal || "Elsewhere on the field"
    if (!groups[key]) { groups[key] = []; order.push(key) }
    groups[key].push(p)
  }
  order.sort()

  var KIND_ORDER = { lounge: 0, food: 1, shop: 2, service: 3 }
  var rows = []
  for (var g = 0; g < order.length; g++) {
    var list = groups[order[g]]
    rows.push({ heading: true, name: order[g], type: "", hours: "",
                count: list.length })
    list.sort(function (x, y) {
      var kx = KIND_ORDER[x.kind] === undefined ? 9 : KIND_ORDER[x.kind]
      var ky = KIND_ORDER[y.kind] === undefined ? 9 : KIND_ORDER[y.kind]
      if (kx !== ky) return kx - ky
      return x.name.toLowerCase() < y.name.toLowerCase() ? -1 : 1
    })
    for (var j = 0; j < list.length; j++) {
      var poi = list[j]
      var type = ""
      if (poi.kind === "lounge") type = "Lounge"
      else if (poi.cuisine) type = poi.cuisine.replace(/_/g, " ").replace(/;/g, ", ")
      else if (poi.shop) type = poi.shop.replace(/_/g, " ")
      else if (poi.amenity) type = poi.amenity.replace(/_/g, " ")
      rows.push({
        heading: false,
        name: poi.name,
        type: type,
        hours: poi.hours || "",
        kind: poi.kind,
        level: poi.level || "",
        url: mapsUrl(poi),
        osm: osmUrl(poi),
        website: poi.website || ""
      })
    }
  }
  return rows
}

// Google Maps link for one place.
//
// NOT "?api=1&query=<name> <lat>,<lon>": that form treats the whole string as
// search text, so Google looks for the literal phrase near *the viewer* and
// lands anywhere. The path form anchors the map viewport at the coordinates
// with "/@lat,lon,zoom", and the search is then resolved inside that view.
function mapsUrl(poi) {
  if (!poi || poi.lat === undefined || poi.lat === null) return ""
  var lat = poi.lat.toFixed(6)
  var lon = poi.lon.toFixed(6)
  var named = poi.name && poi.name !== "(unnamed)"
  if (!named) {
    // Nothing to search for - drop a pin on the exact spot instead.
    return "https://www.google.com/maps/search/?api=1&query=" + lat + "," + lon
  }
  return "https://www.google.com/maps/search/" + encodeURIComponent(poi.name)
    + "/@" + lat + "," + lon + ",19z"
}

// The unambiguous fallback: the exact OpenStreetMap object this row came from.
function osmUrl(poi) {
  if (!poi || !poi.id) return ""
  return "https://www.openstreetmap.org/" + poi.id
}

// Weather detail rows: plain language first, the numbers a pilot needs after.
function weatherRows(w, header) {
  if (!w || !w.available) return []
  var rows = []
  function add(k, v, accent) { if (v) rows.push({ k: k, v: v, accent: accent === true }) }
  add("Flight category", w.category_text || w.category, true)
  add("Wind", w.wind)
  add("Visibility", w.visibility)
  add("Sky", w.sky)
  add("Ceiling", w.ceiling)
  add("Temperature", w.temp)
  add("Dew point", w.dewpoint)
  add("Altimeter", w.altimeter)
  add("Field elevation", header && header.elev !== null && header.elev !== undefined
      ? feet(header.elev) : "")
  add("Pressure altitude", w.pressure_alt ? feet(w.pressure_alt) : "")
  add("Density altitude", w.density_alt ? feet(w.density_alt) : "")
  add("Civil twilight", w.twilight)
  add("Sunrise / sunset", w.sunrise && w.sunset ? w.sunrise + "  /  " + w.sunset : "")
  add("Observed", w.observed)
  return rows
}

function tafLines(taf) {
  if (!taf) return ""
  return String(taf).replace(/\s+(?=FM\d|TEMPO|BECMG|PROB)/g, "\n  ")
}

// Destinations that describe the airport rather than any one page of it. They
// live in the header for that reason: on the Runways page you are no less
// likely to want AirNav than on the Summary. Links that belong to a single row
// - a plate's PDF, a restaurant's map pin - stay with their row.
function linkRows(d) {
  var links = (d && d.links) || {}
  var order = [["diagram", "Airport diagram"],
               ["directions", "Directions"], ["airnav", "AirNav"],
               ["skyvector", "SkyVector"], ["faa_nfdc", "FAA"],
               ["weather", "Weather"],
               // Live tower audio belongs on the front page too, not only
               // beside the frequencies it goes with.
               ["liveatc", "LiveATC"]]
  var out = []
  for (var i = 0; i < order.length; i++) {
    var k = order[i][0]
    if (links[k]) out.push({ label: order[i][1], url: links[k] })
  }
  return out
}

// ---- summary page ---------------------------------------------------------

// The front page: what this airport is and whether you can use it. Written for
// a traveller and a pilot at once - no jargon, no performance numbers.
function summaryRows(s, header, pending) {
  if (!s) return []
  var rows = []
  function add(k, v) { if (v) rows.push({ k: k, v: v }) }

  add("Location", header ? header.where : "")
  add("Elevation", header && header.elev !== null && header.elev !== undefined
      ? feet(header.elev) : "")
  // While the observation is still in flight the row holds its place rather
  // than appearing from nowhere once it lands. It is marked pending so it can
  // be drawn as the placeholder it is, not read as a value.
  if (!s.weather && pending) rows.push({ k: "Conditions", v: "checking…", pending: true })
  else add("Conditions", s.weather)

  var runway = s.longest_runway
  if (runway) {
    if (s.surface) runway += "  " + s.surface
    if (s.runway_count > 1) runway += "   (longest of " + s.runway_count + ")"
  }
  add("Runway", runway)

  // Only assert a negative where the data actually covers it. Outside FAA
  // coverage, "no tower" and "no fuel" mean "not in this dataset", and
  // Heathrow is not a pilot-controlled field.
  var us = header ? header.us !== false : true
  if (s.towered) add("Control tower", s.tower_hours ? "Yes — " + s.tower_hours : "Yes")
  else if (us) add("Control tower", "None — pilot-controlled field")

  if ((s.fuel || []).length) add("Fuel", s.fuel.join(", "))
  else if (us) add("Fuel", "None on the field")
  add("Airspace", s.airspace
      ? s.airspace + (s.airspace_hours ? "   " + s.airspace_hours : "")
      : "")
  if (!us) add("Coverage", "FAA data covers US airports only — tower, fuel, frequencies, "
               + "procedures and services are unavailable here.")
  add("Attended", (s.attended || []).join(" · "))
  add("Landing fee", s.landing_fee === "Y" ? "Yes" : (s.landing_fee === "N" ? "No" : ""))
  return rows
}

function frequencyRows(f) {
  if (!f) return []
  var rows = []
  var field = f.field || []
  // The ones you tune on the field come first; CTAF and tower are the two a
  // pilot reaches for, so they read heavier than the rest.
  var PRIMARY = { CTAF: true, Tower: true }
  if (field.length) rows.push({ heading: true, label: "ON THE FIELD" })
  for (var i = 0; i < field.length; i++)
    rows.push({ label: field[i].label, freq: field[i].freq,
                note: field[i].hours || "", primary: PRIMARY[field[i].label] === true })
  if (f.other_count)
    rows.push({ label: "", freq: "", primary: false,
                note: "+ " + f.other_count + " more (ramp control, emergency, remote outlets)" })

  var approach = f.approach || []
  if (approach.length) {
    rows.push({ heading: true, label: "APPROACH & DEPARTURE" })
    var seen = {}, shown = 0
    for (var j = 0; j < approach.length && shown < 14; j++) {
      var key = approach[j].label + approach[j].freq
      if (seen[key]) continue
      seen[key] = true; shown++
      rows.push({ label: approach[j].label, freq: approach[j].freq, note: "" })
    }
    if (approach.length > shown)
      rows.push({ label: "", freq: "", note: "+ " + (approach.length - shown) + " more" })
  }
  return rows
}

// TFRs, as one honest line.
//
// The FAA publishes geometry only per-NOTAM, so all this knows is the state.
// Listing four statewide TFRs as alerts above an airport's own facts implies a
// proximity that has not been established - so it says how many there are,
// where to look, and nothing more.
function tfrLine(t, us) {
  if (us === false) return ""
  if (!t || !t.available) return ""
  var n = ((t.tfrs || []).length)
  if (!n) return "No active TFRs in " + (t.state || "this state") + "."
  return n + " active TFR" + (n === 1 ? "" : "s") + " in " + t.state
    + " — proximity not checked, see tfr.faa.gov"
}


// FAA-reported delays and closures for the Summary. An empty list from a feed
// that answered means the FAA is reporting nothing; a feed that did not answer
// returns no rows at all, because "unknown" and "fine" are different claims.
function statusLines(s) {
  if (!s || !s.available) return []
  var items = s.items || []
  var out = []
  for (var i = 0; i < items.length; i++) {
    var it = items[i]
    var bits = []
    // Closure reasons are raw NOTAM text and run to several lines; they would
    // swamp the Summary, so only a short reason is shown inline.
    if (it.reason && it.reason.length <= 90) bits.push(it.reason)
    if (it.detail) bits.push(it.detail)
    out.push({ label: it.label, text: bits.join(" — "), alert: true })
  }
  if (!out.length)
    out.push({ label: "", text: "No delays or closures reported by the FAA.",
               alert: false })
  return out
}


// ---- TAF outlook --------------------------------------------------------
// The forecast as a band of time rather than a bulletin: one segment per
// period, width proportional to how long it lasts, coloured by flight
// category. Pilots read the categories, travellers read the summaries.

function outlookSegments(outlook) {
  if (!outlook || !outlook.timeline || !outlook.timeline.length) return []
  var start = Date.parse(outlook.valid_from)
  var end = Date.parse(outlook.valid_to)
  var span = end - start
  if (!(span > 0)) return []
  var out = []
  for (var i = 0; i < outlook.timeline.length; i++) {
    var g = outlook.timeline[i]
    var a = Date.parse(g.from), b = Date.parse(g.to)
    if (!(b > a)) continue
    out.push({
      fraction: (b - a) / span,
      offset: (a - start) / span,
      category: g.category || "",
      from: zulu(g.from),
      to: zulu(g.to)
    })
  }
  return out
}

function zulu(iso) {
  if (!iso) return ""
  var s = String(iso)
  var t = s.indexOf("T")
  return t < 0 ? s : s.substr(t + 1, 5) + "Z"
}

// Hour marks along the band, one every six hours. Each carries both readings:
// Zulu, which is what a TAF is written in and what a pilot briefs against, and
// an offset from now, which is what anyone else can act on without doing
// timezone arithmetic in their head. Callers show whichever their audience
// reads. `tick` is unused - it makes the binding re-evaluate on the clock.
function outlookTicks(outlook, tick) {
  if (!outlook) return []
  var start = Date.parse(outlook.valid_from), end = Date.parse(outlook.valid_to)
  var span = end - start
  if (!(span > 0)) return []
  var now = Date.now()
  var out = []
  var d = new Date(start)
  d.setUTCMinutes(0, 0, 0)
  while (d.getTime() <= end) {
    if (d.getUTCHours() % 6 === 0 && d.getTime() >= start) {
      var delta = Math.round((d.getTime() - now) / 3600000)
      out.push({ offset: (d.getTime() - start) / span,
                 label: ("0" + d.getUTCHours()).slice(-2) + "Z",
                 // A mark in the past is history, not a forecast to plan
                 // against, so it gets no offset rather than a negative one.
                 relative: delta > 0 ? "+" + delta + "h" : "" })
    }
    d = new Date(d.getTime() + 3600000)
  }
  return out
}

// Where "now" falls in the band, 0..1, or -1 when the clock is outside the
// forecast's valid period - an expired TAF must not draw a marker at an edge
// and imply it is current. `tick` is unused: it exists so the QML binding
// re-evaluates on a timer, since Date.now() is not something QML can watch.
function outlookNow(outlook, tick) {
  if (!outlook) return -1
  var start = Date.parse(outlook.valid_from), end = Date.parse(outlook.valid_to)
  var span = end - start
  if (!(span > 0)) return -1
  var fraction = (Date.now() - start) / span
  return (fraction < 0 || fraction > 1) ? -1 : fraction
}

function outlookRows(outlook) {
  if (!outlook) return []
  var out = []
  var line = outlook.timeline || []
  for (var i = 0; i < line.length; i++)
    out.push({ time: zulu(line[i].from) + "-" + zulu(line[i].to),
               category: line[i].category || "", text: line[i].summary || "",
               tag: "" })
  var ov = outlook.overlays || []
  for (var j = 0; j < ov.length; j++) {
    var g = ov[j]
    var tag = g.kind === "prob" ? "" : String(g.kind || "").toUpperCase()
    if (g.probability) tag = ("PROB" + g.probability + " " + tag).trim()
    out.push({ time: zulu(g.from) + "-" + zulu(g.to), category: g.category || "",
               text: g.summary || "", tag: tag || "TEMPO" })
  }
  return out
}


// ---- reading the band without a licence -----------------------------------
// The colours are flight categories, which mean nothing to someone who does
// not fly. These translate them into what the sky is actually doing, and say
// when it changes - in hours from now rather than Zulu, because a traveller
// reading "11:00Z" has to do timezone arithmetic to learn anything.
//
// Deliberately says nothing about delays. Low cloud correlates with them, but
// this forecast does not know about traffic, crews or the rest of the system,
// and a plugin that will not assert a missing NOTAM should not guess at that
// either.

var CATEGORY_PLAIN = {
  VFR:  { short: "clear",                title: "Clear" },
  MVFR: { short: "some cloud or haze",   title: "Some cloud or haze" },
  IFR:  { short: "low cloud, instrument flying",
          title: "Low cloud or poor visibility" },
  LIFR: { short: "very low cloud or fog", title: "Very low cloud or fog" }
}

function plainCategory(c, key) {
  var e = CATEGORY_PLAIN[c]
  return e ? e[key || "short"] : (c || "")
}

function relativeHours(ms) {
  var h = ms / 3600000
  if (h < 0.75) return "within the hour"
  if (h < 1.75) return "in about an hour"
  if (h < 24) return "in about " + Math.round(h) + " hours"
  return "in about " + Math.round(h / 24) + " day" + (h < 36 ? "" : "s")
}

// One line: what it is now, and the next time that changes.
function outlookHeadline(outlook, tick) {
  if (!outlook || !outlook.timeline || !outlook.timeline.length) return ""
  var now = Date.now()
  var line = outlook.timeline
  var current = null, change = null
  for (var i = 0; i < line.length; i++) {
    var a = Date.parse(line[i].from), b = Date.parse(line[i].to)
    if (a <= now && now < b) current = line[i]
    if (current && !change && a > now && line[i].category !== current.category)
      change = line[i]
  }
  // Before the forecast starts, describe its opening period instead.
  if (!current) current = line[0]
  var text = plainCategory(current.category, "title") + " now"
  if (change)
    text += ", turning to " + plainCategory(change.category) + " "
      + relativeHours(Date.parse(change.from) - now)
  else
    text += ", holding through the forecast"

  // Thunderstorms are the one phenomenon worth pulling forward: everyone
  // understands them, and they are why an otherwise fine day goes wrong.
  var storms = null
  var overlays = outlook.overlays || []
  for (var j = 0; j < overlays.length; j++) {
    if (/thunder/i.test(overlays[j].weather || "")) { storms = overlays[j]; break }
  }
  if (storms) {
    var at = Date.parse(storms.from)
    text += " · thunderstorms possible "
      + (at > now ? relativeHours(at - now) : "now")
      + (storms.probability ? " (" + storms.probability + "% chance)" : "")
  }
  return text
}

// Only the categories this forecast actually contains, so a clear day does not
// carry a four-colour key explaining weather it is not having.
function outlookLegend(outlook) {
  if (!outlook || !outlook.timeline) return []
  var seen = {}, out = []
  var all = (outlook.timeline || []).concat(outlook.overlays || [])
  for (var i = 0; i < all.length; i++) {
    var c = all[i].category
    if (!c || seen[c]) continue
    seen[c] = true
    out.push({ category: c, text: plainCategory(c) })
  }
  var order = { VFR: 0, MVFR: 1, IFR: 2, LIFR: 3 }
  out.sort(function (a, b) { return (order[a.category] || 9) - (order[b.category] || 9) })
  return out
}
