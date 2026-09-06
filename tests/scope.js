// The traffic scope draws onto a 2D context, which means it normally only runs
// inside a live shell. This feeds it a recording context instead, so the thing
// that would otherwise be checked by squinting at a panel is checked here.
const fs = require("fs");
const src = fs.readFileSync(__dirname + "/../Model.js", "utf8")
  .split("\n").filter(l => !l.trim().startsWith(".pragma")).join("\n");
const m = {};
new Function("e", src + "; e.paintScope = paintScope; e.scopeRings = scopeRings;")(m);

let failed = 0;
function check(name, got, want) {
  if (got === want) return;
  failed++;
  console.log("FAIL " + name + "\n     wanted: " + want + "\n     got:    " + got);
}

function ctx() {
  const c = { ops: 0, texts: [], fills: 0, strokes: 0 };
  ["reset", "beginPath", "arc", "moveTo", "lineTo", "closePath", "save",
   "restore", "translate", "rotate", "setLineDash"].forEach(k => c[k] = () => c.ops++);
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

check("rings for an odd range", m.scopeRings(37).join(","), "19,37");
check("rings for a preset range", m.scopeRings(50).join(","), "10,25,50");

if (failed) process.exit(1);
console.log("scope ok");
