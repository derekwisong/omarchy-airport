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
function summaryRows(s, header) {
  if (!s) return []
  var rows = []
  function add(k, v) { if (v) rows.push({ k: k, v: v }) }

  // Location, elevation and conditions are in the header, on every page. The
  // Summary used to repeat all three word for word; it now starts with what
  // the header does not already say.

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

// ---- local time -----------------------------------------------------------
// The clock at the airport, ticked by the panel rather than read out of the
// payload: the engine's timestamp is minutes old by the time anyone looks. The
// engine supplies the offset, recomputed from the zone on every build, so this
// stays right across a daylight-saving change without refetching anything.
//
// Empty when the zone was never established. No FAA product publishes one, so
// it is looked up per airport and cached, and an airport whose lookup has not
// happened yet shows no time at all rather than a guessed one.
var CLOCK_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
var CLOCK_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

// The tick argument is unused: it exists so a binding re-evaluates every
// minute, the same way the forecast band's readouts do.
function localAt(local) {
  if (!local || local.offset_minutes === undefined
      || local.offset_minutes === null) return null
  // Shift into the airport's offset, then read the shifted instant as UTC.
  return new Date(Date.now() + local.offset_minutes * 60000)
}


function localClock(local, tick) {
  var d = localAt(local)
  if (!d) return ""
  return ("0" + d.getUTCHours()).slice(-2) + ":" + ("0" + d.getUTCMinutes()).slice(-2)
    + (local.abbrev ? " " + local.abbrev : "")
}


function localDate(local, tick) {
  var d = localAt(local)
  if (!d) return ""
  return CLOCK_DAYS[d.getUTCDay()] + " " + d.getUTCDate()
    + " " + CLOCK_MONTHS[d.getUTCMonth()]
}


// The facts that used to each own a line: the ICAO form you file under, where
// the field is, and how high. One muted line under the name instead of three
// stacked ones, because none of them is worth a line of its own.
function headerFacts(header) {
  if (!header) return ""
  var bits = []
  if (header.icao) bits.push(header.icao)
  if (header.where) bits.push(header.where)
  if (header.elev !== null && header.elev !== undefined)
    bits.push("elev " + feet(header.elev))
  return bits.join("  ·  ")
}


// ---- live traffic ---------------------------------------------------------
// ADS-B is what volunteer receivers heard, which is not what is flying. Every
// line here is phrased as seen, the count says so, and an empty list says the
// receivers are quiet rather than the sky is.
//
// Phase is inferred from altitude and vertical rate - ADS-B carries no origin
// or destination - so these are headed the way the data says, not the way a
// flight plan says.
var TRAFFIC_GROUPS = [
  { key: "arriving",  title: "Arriving" },
  { key: "departing", title: "Departing" },
  { key: "ground",    title: "On the ground" },
  { key: "over",      title: "Passing over" }
]

function trafficGroups(traffic) {
  if (!traffic || !traffic.available) return []
  var list = traffic.aircraft || []
  var out = []
  for (var g = 0; g < TRAFFIC_GROUPS.length; g++) {
    var rows = []
    for (var i = 0; i < list.length; i++)
      if (list[i].phase === TRAFFIC_GROUPS[g].key) rows.push(trafficRow(list[i]))
    if (rows.length)
      out.push({ title: TRAFFIC_GROUPS[g].title, count: rows.length, rows: rows })
  }
  return out
}


// Range rings for the scope: a couple of intermediate marks plus the radius
// actually asked for, which is always the last and is drawn solid.
var SCOPE_RINGS = { 10: [2, 5, 10], 25: [5, 10, 25], 50: [10, 25, 50],
                    100: [25, 50, 100] }

// The scope, drawn onto a 2D context.
//
// A plan view centred on the field rather than a globe, because 25 nm is 0.42
// degrees of latitude: on a globe drawn from any ordinary country outline the
// whole picture is one dot. Everything here is local-flat - at these ranges
// the error against a proper projection is far under a pixel.
//
// Lives here rather than inline in the Canvas so it can be rendered and looked
// at without a running shell.
function paintScope(ctx, o) {
  var centre = o.payload ? o.payload.center : null
  var cx = o.width / 2, cy = o.height / 2
  var rpx = Math.min(o.width, o.height) / 2 - o.pad
  ctx.reset()
  if (!ctx || rpx <= 4 || !centre) return false
  var scale = rpx / Math.max(1, o.range)
  var coslat = Math.cos(centre.lat * Math.PI / 180)
  ctx.font = o.font

  function at(lat, lon) {
    return [cx + (lon - centre.lon) * 60 * coslat * scale,
            cy - (lat - centre.lat) * 60 * scale]
  }

  // Range rings. The outermost is the radius actually asked for, so it is
  // solid and the intermediate marks are dashed.
  var rings = o.rings || []
  ctx.strokeStyle = o.muted
  ctx.lineWidth = 1
  for (var i = 0; i < rings.length; i++) {
    var rr = rings[i] * scale
    if (rr > rpx + 0.5) continue
    ctx.globalAlpha = 0.35
    ctx.beginPath()
    ctx.setLineDash(i === rings.length - 1 ? [] : [3, 5])
    ctx.arc(cx, cy, rr, 0, Math.PI * 2)
    ctx.stroke()
  }
  ctx.setLineDash([])

  // Ring labels on the north-east diagonal, where nothing else lives; on the
  // north spoke they fought with the "N". Drawn first and their boxes kept, so
  // an aircraft tag later on gives way to them rather than overprinting.
  var placed = []
  ctx.globalAlpha = 0.8
  ctx.fillStyle = o.muted
  ctx.textAlign = "center"
  for (i = 0; i < rings.length; i++) {
    rr = rings[i] * scale
    if (rr > rpx + 0.5) continue
    var lx = cx + Math.SQRT1_2 * rr, ly = cy - Math.SQRT1_2 * rr - 3
    var label = rings[i] + " nm"
    placed.push([lx - label.length * 3.3, ly - 8, lx + label.length * 3.3, ly + 4])
    ctx.fillText(label, lx, ly)
  }
  var marks = [[0, "N"], [90, "E"], [180, "S"], [270, "W"]]
  for (i = 0; i < marks.length; i++) {
    var a = marks[i][0] * Math.PI / 180
    ctx.fillText(marks[i][1], cx + Math.sin(a) * (rpx + o.pad * 0.55),
                 cy - Math.cos(a) * (rpx + o.pad * 0.55) + 4)
  }
  ctx.globalAlpha = 1

  // The field itself, to scale, from runway end coordinates already in hand.
  ctx.strokeStyle = o.ink
  ctx.lineWidth = o.runwayWidth
  ctx.lineCap = "butt"
  var strips = o.strips || []
  for (i = 0; i < strips.length; i++) {
    var ends = strips[i].ends || []
    if (ends.length !== 2 || !ends[0].lat || !ends[1].lat) continue
    var p = at(ends[0].lat, ends[0].lon), q = at(ends[1].lat, ends[1].lon)
    ctx.beginPath()
    ctx.moveTo(p[0], p[1])
    ctx.lineTo(q[0], q[1])
    ctx.stroke()
  }

  var list = (o.payload && o.payload.aircraft) || []
  var drawn = 0
  for (i = 0; i < list.length; i++) {
    var ac = list[i]
    if (ac.lat === null || ac.lat === undefined) continue
    var pt = at(ac.lat, ac.lon)
    var off = Math.sqrt((pt[0] - cx) * (pt[0] - cx) + (pt[1] - cy) * (pt[1] - cy))
    if (off > rpx) continue
    drawn++
    if (ac.phase === "ground") {
      ctx.globalAlpha = 0.45
      ctx.fillStyle = o.muted
      ctx.beginPath()
      ctx.arc(pt[0], pt[1], 1.6, 0, Math.PI * 2)
      ctx.fill()
      ctx.globalAlpha = 1
      continue
    }
    // Filled for arriving, hollow for departing: the two are told apart by
    // shape as well as colour, so the scope still reads on a theme where the
    // two tints land close together, or to a colourblind eye.
    var arriving = ac.phase === "arriving", departing = ac.phase === "departing"
    var tint = arriving ? o.accent : (departing ? o.ink : o.muted)
    ctx.save()
    ctx.translate(pt[0], pt[1])
    ctx.rotate((ac.track || 0) * Math.PI / 180)
    ctx.beginPath()
    ctx.moveTo(0, -7)
    ctx.lineTo(4.6, 6)
    ctx.lineTo(0, 3.2)
    ctx.lineTo(-4.6, 6)
    ctx.closePath()
    if (departing) {
      ctx.strokeStyle = tint
      ctx.lineWidth = 1.4
      ctx.stroke()
    } else {
      ctx.fillStyle = tint
      ctx.globalAlpha = arriving ? 1 : 0.5
      ctx.fill()
      ctx.globalAlpha = 1
    }
    ctx.restore()

    if (!arriving && !departing) continue
    var name = ac.flight || ac.reg || ""
    if (!name) continue
    // A tag that would land on one already drawn is dropped. A clean scope
    // missing a few labels beats an unreadable one.
    var box = [pt[0] + 7, pt[1] - 8, pt[0] + 7 + name.length * 6.5, pt[1] + 4]
    var clash = false
    for (var j = 0; j < placed.length; j++) {
      var b = placed[j]
      if (box[0] < b[2] && b[0] < box[2] && box[1] < b[3] && b[1] < box[3]) {
        clash = true
        break
      }
    }
    if (clash) continue
    placed.push(box)
    ctx.textAlign = "left"
    ctx.fillStyle = tint
    ctx.fillText(name, pt[0] + 7, pt[1] + 1)
  }
  return drawn
}


function scopeRings(range) {
  return SCOPE_RINGS[range] || [Math.round(range / 2), range]
}


function trafficRow(a) {
  return {
    call: a.flight || a.reg || (a.squawk ? "squawk " + a.squawk : "unknown"),
    type: a.type || "",
    detail: trafficDetail(a),
    emergency: a.emergency === true
  }
}


function trafficDetail(a) {
  var bits = []
  if (a.phase === "ground") bits.push("on the ground")
  else if (a.altitude !== null && a.altitude !== undefined)
    bits.push(commas(a.altitude) + " ft")
  // Height, then which way, then how fast - the order you would ask them in.
  // Zero-padded to three digits, the way a heading is written and read.
  if (a.track !== null && a.track !== undefined && a.phase !== "ground")
    bits.push(("00" + Math.round(a.track % 360)).slice(-3) + "°")
  if (a.speed) bits.push(a.speed + " kt")
  if (a.distance_nm !== null && a.distance_nm !== undefined)
    bits.push(a.distance_nm + " nm")
  return bits.join("  ·  ")
}


function commas(n) {
  var s = String(Math.round(Number(n) || 0)), out = ""
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 === 0) out += ","
    out += s[i]
  }
  return out
}


// What the list above is and is not, said once under it.
function trafficNote(traffic) {
  if (!traffic) return ""
  if (!traffic.available)
    return "Could not reach the traffic feed. This says nothing about the sky - "
      + "only that the report did not arrive."
  var n = traffic.seen || 0
  if (!n)
    return "Nothing seen within " + (traffic.radius_nm || 25) + " nm. Coverage is "
      + "volunteer receivers, so this is not the same as an empty sky."
  return n + " aircraft seen within " + (traffic.radius_nm || 25) + " nm. ADS-B is "
    + "what receivers heard: anything without ADS-B out, or below their horizon, "
    + "is not here. © " + (traffic.attribution || "adsb.lol contributors, ODbL")
}


// ---- TFRs, by distance ----------------------------------------------------

// The FAA's own list page, for everything the rows below do not carry.
var TFR_LIST_URL = "https://tfr.faa.gov/tfr3/?page=list"

// How many restrictions the Summary carries before it stops being a summary.
var TFR_ROWS = 5

// Individual restrictions, nearest first, each linked to the FAA page for it.
//
// This used to be a count by state, which answered a question nobody asked:
// a restriction 200 miles away is not in your way, and one 20 miles over the
// state line does not stop being in your way because the line is there. The
// engine locates every active TFR now, so these are the ones near this field.
//
// Three columns rather than a sentence per restriction. An airport under a
// presidential visit has nine of these at once, and as one bold line each they
// were a wall of text with the distance - the only part anyone scans for -
// buried in the middle of it.
function tfrRows(t, us, tint) {
  if (us === false) return []
  if (!t || !t.available) return []
  var list = t.tfrs || []
  var out = []
  for (var i = 0; i < list.length && i < TFR_ROWS; i++) {
    var f = list[i]
    var what = f.place || f.description || ""
    // Only the distance is emphasised, because it is the one column that
    // decides whether the rest of the row matters to you.
    out.push({
      near: f.distance_nm > 0 ? f.distance_nm + " nm" : "inside",
      inside: !(f.distance_nm > 0),
      kind: (f.type || "").toLowerCase(),
      html: escapeHtml(statusTrim(what))
        + (f.when ? "  <i>" + escapeHtml(f.when) + "</i>" : "")
        + advisoryLink(f.url, "detail", tint)
    })
  }
  return out
}


// What the rows leave out, and what could not be placed on a map at all. Shown
// even when there are no rows, because "none within 50 nm" is the answer to
// the question the heading just asked.
function tfrNote(t, us, tint) {
  if (us === false) return ""
  if (!t || !t.available) return ""
  var list = t.tfrs || []
  var radius = t.radius_nm || 50
  var notes = []
  if (!list.length) notes.push("None within " + radius + " nm")
  else if (list.length > TFR_ROWS)
    notes.push((list.length - TFR_ROWS) + " more within " + radius + " nm")
  // A standing national notice is not near this field; it is near every field,
  // which is a different claim and does not belong in the list above.
  if (t.nationwide)
    notes.push(t.nationwide + " standing nationwide notice"
               + (t.nationwide === 1 ? "" : "s"))
  if (t.unlocated) notes.push(t.unlocated + " could not be located")
  return escapeHtml(notes.join(" · ")) + advisoryLink(TFR_LIST_URL, "TFR list", tint)
}


// How long a programme has left, worked out when the panel draws rather than
// when the feed was fetched — a cached "in 40 minutes" is wrong a minute after
// it is written. Nothing past a day, where the date the line already carries
// says more than a countdown does.
function statusRemaining(iso) {
  if (!iso) return ""
  var end = Date.parse(String(iso))
  if (isNaN(end)) return ""
  var mins = Math.floor((end - Date.now()) / 60000)
  if (mins <= 0) return "past its end time"
  if (mins > 24 * 60) return ""
  if (mins < 60) return "in " + mins + " minute" + (mins === 1 ? "" : "s")
  var hours = Math.floor(mins / 60), rest = mins % 60
  return "in " + hours + " hour" + (hours === 1 ? "" : "s")
    + (rest ? " " + rest + " minutes" : "")
}


// FAA-reported delays and closures for the Summary. An empty list from a feed
// that answered means the FAA is reporting nothing; a feed that did not answer
// returns no rows at all, because "unknown" and "fine" are different claims.
//
// A ground stop is an arrival programme: it holds flights bound for the field,
// at the field they are leaving from, and usually only those filed out of a
// named few centres. It says nothing about the runways. Labelled on its own,
// next to a row reading "Airport closure", it was read as the airport being
// shut — so the headline names who is actually held and the caption says the
// field is open.
function statusLines(s, tint) {
  if (!s || !s.available) return []
  var items = s.items || []
  var out = []
  for (var i = 0; i < items.length; i++) {
    var it = items[i]
    // Raw NOTAM text runs to several lines and would swamp the Summary.
    var head = statusTrim(it.text || it.detail || it.reason || "")
    var left = statusRemaining(it.ends)
    if (left) head += (head ? "  " : "") + "(" + left + ")"
    var headline = it.label ? it.label + " — " + head : head
    out.push({ label: it.label, text: head, alert: true,
               html: escapeHtml(headline) })
    // The caption is not trimmed: it is the line carrying "the field is open",
    // and a cut there loses exactly the thing this row exists to say.
    var caption = (it.caption && it.caption !== head) ? it.caption : ""
    var link = statusLink(it.url, tint)
    if (caption || link)
      out.push({ label: "", text: caption, alert: false,
                 html: escapeHtml(caption) + link })
  }
  if (!out.length)
    out.push({ label: "", text: "No delays or closures reported by the FAA.",
               alert: false, html: "No delays or closures reported by the FAA." })
  return out
}


// The advisory the FAA actually published. These lines are a summary of it,
// and a summary is where a ground stop turns into "the airport is closed" -
// so the row carries a way to go and read the thing it is summarising.
//
// The URL comes out of the feed, so it goes through the same two gates as any
// other mapped data reaching markup: http(s) only, then escaped. The FAA
// writes the advisory title into the query string, spaces and all.
function statusLink(url, tint) {
  return advisoryLink(url, "FAA advisory", tint)
}


// The colour is passed in and written into the tag rather than left to the
// Text's linkColor, which is what every other link in the panel does and is
// the only way the theme's accent actually reaches an anchor.
function advisoryLink(url, label, tint) {
  var safe = safeUrl(url)
  if (!safe) return ""
  return "   <a href=\'" + escapeHtml(safe.replace(/ /g, "%20")) + "\'"
    + (tint ? " style=\'color:" + escapeHtml(tint) + "\'" : "") + ">"
    + escapeHtml(label) + "</a>"
}


function statusTrim(text) {
  var s = String(text || "")
  return s.length <= 120 ? s : s.substr(0, 119).replace(/\s+\S*$/, "") + "…"
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
  // Timeline only. TEMPO and PROB groups are not drawn on the band, so listing
  // their colours in its key points at something that is not there; the
  // headline already calls those out in words.
  var all = outlook.timeline || []
  for (var i = 0; i < all.length; i++) {
    var c = all[i].category
    if (!c || seen[c]) continue
    seen[c] = true
    out.push({ category: c, text: plainCategory(c) })
  }
  // `order[c] || 9` put VFR last, because its rank is 0 and 0 is falsy.
  var order = { VFR: 0, MVFR: 1, IFR: 2, LIFR: 3 }
  function rank(c) { return c in order ? order[c] : 9 }
  out.sort(function (a, b) { return rank(a.category) - rank(b.category) })
  return out
}


// ---- which runway the wind favours -----------------------------------------
// METAR wind is true-north referenced and NASR's TRUE_ALIGNMENT is too, so
// these compare directly. Runway *numbers* are magnetic - 34 at HPN points
// 330 true - which is exactly why the sum uses the alignment and not the
// number on the tarmac.

function windComponents(trueAlign, windDir, windSpeed) {
  var offset = ((windDir - trueAlign + 540) % 360) - 180   // -180..180
  var rad = offset * Math.PI / 180
  return {
    head: windSpeed * Math.cos(rad),
    cross: Math.abs(windSpeed * Math.sin(rad)),
    fromRight: offset > 0
  }
}

// The end with the most headwind. Null when there is nothing to favour: calm,
// variable, or no report at all - all of which are silence rather than a guess.
function favouredEnd(runwayData, weather) {
  if (!runwayData || !weather || !weather.available) return null
  var dir = weather.wind_dir, speed = weather.wind_speed
  if (dir === null || dir === undefined || !(speed >= 3)) return null
  var best = null
  var runways = runwayData.runways || []
  for (var i = 0; i < runways.length; i++) {
    var ends = runways[i].ends || []
    for (var j = 0; j < ends.length; j++) {
      var align = parseFloat(ends[j].true_align)
      if (!(align >= 0)) continue
      var c = windComponents(align, dir, speed)
      if (!best || c.head > best.head)
        best = { id: ends[j].id, runway: runways[i].id, head: c.head,
                 cross: c.cross, fromRight: c.fromRight }
    }
  }
  // A runway with the wind behind it is not favoured, it is merely least bad.
  return (best && best.head > 0) ? best : null
}

function favouredLine(runwayData, weather) {
  var best = favouredEnd(runwayData, weather)
  if (!best) {
    if (weather && weather.available && !(weather.wind_speed >= 3))
      return "Wind is light and variable — no runway is favoured."
    return ""
  }
  var cross = Math.round(best.cross)
  return "Wind favours runway " + best.id + " — headwind "
    + Math.round(best.head) + " kt"
    + (cross > 0 ? ", crosswind " + cross + " kt from the "
                   + (best.fromRight ? "right" : "left") : ", no crosswind")
}


// True when this table row is the end the wind favours, so the table can mark
// it without the caller recomputing the sum per row.
function isFavouredEnd(row, runwayData, weather) {
  if (!row || row.runway) return false
  var best = favouredEnd(runwayData, weather)
  return !!best && best.id === row.id
}


// ---- putting data into markup ---------------------------------------------
// A few Text items use Text.RichText so a row can carry a link. Anything
// interpolated into one is markup, not text: an OpenStreetMap place is named
// by whoever added it, and a name containing a tag would be rendered as one.

function escapeHtml(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
}

// Only http(s) may reach an href. A file: or javascript: URL arriving from
// mapped data would otherwise be a link the panel drew and vouched for.
function safeUrl(u) {
  var s = String(u === null || u === undefined ? "" : u)
  return /^https?:\/\//i.test(s) ? s.replace(/'/g, "%27") : ""
}
