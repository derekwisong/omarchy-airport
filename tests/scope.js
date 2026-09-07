// The traffic scope draws onto a 2D context, which means it normally only runs
// inside a live shell. This feeds it a recording context instead, so the thing
// that would otherwise be checked by squinting at a panel is checked here.
const fs = require("fs");
const src = fs.readFileSync(__dirname + "/../Model.js", "utf8")
  .split("\n").filter(l => !l.trim().startsWith(".pragma")).join("\n");
const m = {};
new Function("e", src + "; e.paintScope = paintScope; e.scopeRings = scopeRings; e.trafficNote = trafficNote;")(m);

let failed = 0;
function check(name, got, want) {
  if (got === want) return;
  failed++;
  console.log("FAIL " + name + "\n     wanted: " + want + "\n     got:    " + got);
}

function ctx() {
  const c = { ops: 0, texts: [], fills: 0, strokes: 0, images: [], clips: 0 };
  ["reset", "beginPath", "arc", "moveTo", "lineTo", "closePath", "save",
   "restore", "translate", "rotate", "setLineDash"].forEach(k => c[k] = () => c.ops++);
  c.clip = () => { c.clips++; c.ops++; };
  c.drawImage = (src, x, y, w, h) => {
    c.images.push({ src: String(src), x: x, y: y, w: w, h: h, at: c.ops });
    c.ops++;
  };
  c.fill = () => { c.fills++; c.ops++; };
  c.stroke = () => { c.strokes++; c.ops++; };
  c.fillText = (t) => { c.texts.push(String(t)); c.ops++; };
  return c;
}

const CENTRE = { lat: 33.6367, lon: -84.4279, ident: "ATL" };
const OPTS = { width: 430, height: 430, range: 25, rings: [5, 10, 25], pad: 16,
               runwayWidth: 3, font: "10px monospace",
               muted: "#888", ink: "#222", accent: "#0a0" };

function paint(aircraft, extra) {
  const c = ctx();
  const o = Object.assign({}, OPTS, extra || {});
  o.payload = { center: CENTRE, aircraft: aircraft };
  const n = m.paintScope(c, o);
  return { c, n };
}

// A quarter degree of latitude north is 15 nm, comfortably inside 25.
const NORTH = { lat: 33.8867, lon: -84.4279, phase: "arriving", track: 180,
                flight: "DAL1", altitude: 4000 };
const FAR = { lat: 34.6367, lon: -84.4279, phase: "arriving", track: 180,
              flight: "DAL2", altitude: 4000 };

check("an aircraft in range is drawn", paint([NORTH]).n, 1);
check("one 60 nm out is not", paint([FAR]).n, 0);
check("no position, not drawn",
      paint([{ lat: null, lon: null, phase: "arriving" }]).n, 0);
check("no payload is refused",
      m.paintScope(ctx(), Object.assign({}, OPTS, { payload: null })), false);
check("a canvas too small to draw on is refused",
      m.paintScope(ctx(), Object.assign({}, OPTS,
        { width: 8, height: 8, payload: { center: CENTRE, aircraft: [] } })), false);

// Arriving is filled and departing is hollow, so the two stay apart on a theme
// where their colours do not, and to a colourblind eye.
const arriving = paint([NORTH]).c;
const departing = paint([Object.assign({}, NORTH, { phase: "departing" })]).c;
check("arriving is filled", arriving.fills > 0, true);
check("departing is not filled", departing.fills, 0);
check("departing is stroked", departing.strokes > arriving.strokes, true);

// Ground traffic is a dot with no tag: at a hub there are dozens on one spot.
const ground = paint([Object.assign({}, NORTH, { phase: "ground" })]).c;
check("ground draws no callsign", ground.texts.indexOf("DAL1"), -1);
const over = paint([Object.assign({}, NORTH, { phase: "over" })]).c;
check("overflights draw no callsign", over.texts.indexOf("DAL1"), -1);
check("arriving draws its callsign", arriving.texts.indexOf("DAL1") >= 0, true);

// Rings and cardinals are labelled once each, whatever the traffic.
const bare = paint([]).c;
["5 nm", "10 nm", "25 nm", "N", "E", "S", "W"].forEach(t =>
  check("labelled " + t, bare.texts.filter(x => x === t).length, 1));

// Two aircraft on the same spot must not print two tags over each other.
const stacked = paint([NORTH, Object.assign({}, NORTH, { flight: "DAL9" })]).c;
check("colliding tags are dropped",
      stacked.texts.filter(t => t === "DAL1" || t === "DAL9").length, 1);

// A runway with no coordinates is skipped rather than drawn at the pole.
const noCoords = paint([], { strips: [{ ends: [{ lat: null }, { lat: null }] }] });
check("a runway without coordinates is skipped", noCoords.n, 0);

// The radar picture goes under the instrument, clipped to it, and is placed
// by its own bounding box rather than by the range that was asked for - so a
// picture that came back covering a different box lands where the geography
// says, not stretched over the rings.
const RADAR = { image: "file:///tmp/radar.png",
                bbox: { south: CENTRE.lat - 25 / 60, north: CENTRE.lat + 25 / 60,
                        west: CENTRE.lon - 25 / (60 * Math.cos(CENTRE.lat * Math.PI / 180)),
                        east: CENTRE.lon + 25 / (60 * Math.cos(CENTRE.lat * Math.PI / 180)) } };
const withRadar = paint([NORTH], { radar: RADAR }).c;
check("the radar is drawn", withRadar.images.length, 1);
check("the radar is clipped to the scope", withRadar.clips > 0, true);
check("the radar is drawn before anything else",
      withRadar.images[0].at < 6, true);
// A 25 nm box on a 430 px scope with 16 px of padding spans the full width.
check("the radar box fills the scope",
      Math.round(withRadar.images[0].w), 2 * (430 / 2 - 16));
check("the radar box is square on the drawing",
      Math.round(withRadar.images[0].w), Math.round(withRadar.images[0].h));
// Half the range means half the picture on screen: the box is placed by where
// its corners fall, so a stale box at the old range does not silently rescale.
const halfBox = { image: "file:///tmp/radar.png",
                  bbox: { south: CENTRE.lat - 12.5 / 60, north: CENTRE.lat + 12.5 / 60,
                          west: CENTRE.lon - 12.5 / (60 * Math.cos(CENTRE.lat * Math.PI / 180)),
                          east: CENTRE.lon + 12.5 / (60 * Math.cos(CENTRE.lat * Math.PI / 180)) } };
check("a smaller box draws smaller",
      Math.round(paint([], { radar: halfBox }).c.images[0].w),
      Math.round(withRadar.images[0].w / 2));
check("no radar, no image", paint([NORTH]).c.images.length, 0);

check("rings for an odd range", m.scopeRings(37).join(","), "19,37");
check("rings for a preset range", m.scopeRings(50).join(","), "10,25,50");
check("rings for the tightest range", m.scopeRings(5).join(","), "1,2,5");

// The note under the traffic list carries a link to the feed it came from,
// and says nothing about the sky beyond what the feed reported.
const note = m.trafficNote({ available: true, seen: 3, radius_nm: 10,
                             attribution: "adsb.lol contributors, ODbL" }, "#0a0");
check("the note links the source", /href='https:\/\/adsb\.lol'/.test(note), true);
check("the note credits ODbL", />adsb\.lol<\/a> contributors, ODbL/.test(note), true);
check("an unreachable feed claims nothing",
      /did not answer/.test(m.trafficNote({ available: false }, "#0a0")), true);

if (failed) process.exit(1);
console.log("scope ok");
