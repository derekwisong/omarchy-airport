// Wind components per runway end, and how old the observation they came from
// is. Both are sums the panel prints as fact, so they are checked here rather
// than by squinting at a running shell on a windy day.
const fs = require("fs");
const src = fs.readFileSync(__dirname + "/../Model.js", "utf8")
  .split("\n").filter(l => !l.trim().startsWith(".pragma")).join("\n");
const m = {};
// Model.js formats lengths through QML's locale, which a shell supplies and
// node does not - and QML's Number.toLocaleString(locale, "f", 0) is not the
// signature node's takes. Nothing under test formats a length, but runwayRows
// does on its way past, so both are stubbed for the length of this file.
const Qt = { locale: () => "en-US" };
Number.prototype.toLocaleString = function () { return String(this); };
new Function("e", "Qt", src + "; e.windCell = windCell; e.windReady = windReady;"
  + " e.favouredEnd = favouredEnd; e.runwayRows = runwayRows;"
  + " e.observedAge = observedAge;")(m, Qt);

let failed = 0;
function check(name, got, want) {
  if (got === want) return;
  failed++;
  console.log("FAIL " + name + "\n     wanted: " + want + "\n     got:    " + got);
}

function wx(dir, speed) {
  return { available: true, wind_dir: dir, wind_speed: speed };
}

// Straight down the runway is all headwind and no crosswind, and the reverse
// end of the same strip is all tailwind.
check("wind down the runway", m.windCell("90", wx(90, 8)), "8 hw");
check("wind up the other end", m.windCell("270", wx(90, 8)), "8 tw");

// A wind 90° off is all crosswind, and the side it comes from is the side of
// the nose it is on - 360 at a runway facing east crosses from the left.
check("wind across from the left", m.windCell("90", wx(360, 10)), "10 xw L");
check("wind across from the right", m.windCell("90", wx(180, 10)), "10 xw R");

// 45° off splits it, and both halves are named.
check("wind on the quarter", m.windCell("90", wx(45, 14)), "10 hw  ·  10 xw L");

// Silence, not arithmetic on noise: calm, variable, or no report at all.
check("calm resolves to nothing", m.windCell("90", wx(90, 2)), "");
check("a variable wind resolves to nothing", m.windCell("90", wx(null, 12)), "");
check("no report resolves to nothing", m.windCell("90", null), "");
check("an end with no alignment resolves to nothing",
      m.windCell("", wx(90, 12)), "");
check("windReady agrees with the cells", m.windReady(wx(90, 2)), false);

// The favoured end is marked on the row the table draws, so the table does not
// have to re-run the sum once per row to find it.
const strip = { runways: [{ id: "09/27", length: 5000, width: 100,
  ends: [{ id: "09", true_align: "87" }, { id: "27", true_align: "267" }] }] };
const rows = m.runwayRows(strip, wx(90, 10));
check("the into-wind end is the favoured one",
      rows.filter(r => r.favoured).map(r => r.id).join(","), "09");
check("the downwind end is not favoured",
      rows.filter(r => r.id === "27")[0].favoured, false);
check("a calm day favours nothing",
      m.runwayRows(strip, wx(90, 1)).filter(r => r.favoured).length, 0);
check("the pair row carries the size, not a wind",
      m.runwayRows(strip, wx(90, 10))[0].wind, undefined);

// The age of the observation, which is the difference between a report worth
// planning on and one that only looks like it.
const now = Date.now() / 1000;
function age(minutes) { return m.observedAge({ observed_epoch: now - minutes * 60 }, 0); }
check("minutes are minutes", age(22).text, "22 min ago");
check("an hour is hours and minutes", age(95).text, "1h 35m ago");
check("a fresh report says so", age(0.2).text, "just now");
check("an hour-old report is not stale", age(60).stale, false);
check("a missed cycle is stale", age(80).stale, true);
// A machine clock ahead of the feed is not an age, and must not print as one.
check("a report from the future is silent", age(-5), null);
check("no timestamp is silent", m.observedAge({ observed: "13:53Z" }, 0), null);

if (failed) process.exit(1);
console.log("wind and observation age ok");
