// A few panel rows are Text.RichText so they can carry a link, and an
// OpenStreetMap place is named by whoever mapped it. Anything interpolated
// into markup has to be escaped, and anything reaching an href has to be a
// URL we would be willing to open.
const fs = require("fs");
const src = fs.readFileSync(__dirname + "/../Model.js", "utf8")
  .split("\n").filter(l => !l.trim().startsWith(".pragma")).join("\n");
const m = {};
new Function("e", src + "; e.escapeHtml = escapeHtml; e.safeUrl = safeUrl;"
  + " e.statusLink = statusLink; e.statusLines = statusLines;")(m);

let failed = 0;
function check(name, got, want) {
  if (got === want) return;
  failed++;
  console.log("FAIL " + name + "\n     wanted: " + want + "\n     got:    " + got);
}

check("tags are neutralised",
  m.escapeHtml("<b>x</b>"), "&lt;b&gt;x&lt;/b&gt;");
check("ampersands are neutralised",
  m.escapeHtml("Bar & Grill"), "Bar &amp; Grill");
check("quotes cannot close an attribute",
  m.escapeHtml("a'b\"c"), "a&#39;b&quot;c");
check("null name does not crash", m.escapeHtml(null), "");

check("https passes", m.safeUrl("https://a/b"), "https://a/b");
check("file: is refused", m.safeUrl("file:///etc/passwd"), "");
check("javascript: is refused", m.safeUrl("javascript:alert(1)"), "");
check("bare path is refused", m.safeUrl("node/1"), "");
check("quote in a url is encoded",
  m.safeUrl("https://a/b' onclick='x"), "https://a/b%27 onclick=%27x");

// The advisory URL comes out of the FAA feed and lands in an href.
check("advisory link is built",
  m.statusLink("https://www.fly.faa.gov/adv/x.jsp?a=1&b=2"),
  "   <a href='https://www.fly.faa.gov/adv/x.jsp?a=1&amp;b=2'>FAA advisory</a>");
check("advisory title's spaces are encoded",
  m.statusLink("https://a/b?title=CDM GROUND STOP"),
  "   <a href='https://a/b?title=CDM%20GROUND%20STOP'>FAA advisory</a>");
check("no url, no link", m.statusLink(""), "");
check("javascript: url draws no link", m.statusLink("javascript:alert(1)"), "");

// A ground stop line is bold body text; nothing in it may be markup.
const rows = m.statusLines({ available: true, items: [{
  label: "Ground stop", text: "arrivals from <b>ZDC</b> held",
  caption: "Bar & Grill", url: "https://a/b" }] });
check("row headline is escaped",
  rows[0].html, "Ground stop — arrivals from &lt;b&gt;ZDC&lt;/b&gt; held");
check("row caption is escaped and carries the link",
  rows[1].html, "Bar &amp; Grill   <a href='https://a/b'>FAA advisory</a>");

if (failed) process.exit(1);
console.log("escaping ok");
