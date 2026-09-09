#!/usr/bin/env python3
"""Bounds on anything downloaded: size, host, redirect, and zip expansion.

Offline. Every fetch used to read a whole response into memory with no ceiling
and follow redirects wherever they led, so a source having a bad day - or an
imposter answering for one - could hand the plugin as much as it cared to send.
"""
import io
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import apt  # noqa: E402

fail = 0


def check(name, got, want):
    global fail
    if got == want:
        return
    fail += 1
    print("FAIL %s\n     wanted: %r\n     got:    %r" % (name, want, got))


def refuses(name, fn, exc):
    """The call must raise `exc`. Returning normally is the failure."""
    global fail
    try:
        fn()
    except exc:
        return
    except Exception as other:
        fail += 1
        print("FAIL %s\n     wanted: %s\n     got:    %s: %s"
              % (name, exc.__name__, type(other).__name__, other))
        return
    fail += 1
    print("FAIL %s\n     wanted: %s\n     got:    no exception" % (name, exc.__name__))


class Body:
    """A response of n bytes. `declared` is what it claims in Content-Length,
    which is a claim and not a fact - hence the separate streaming check."""

    def __init__(self, n, declared=None):
        self._data = io.BytesIO(b"x" * n)
        self.headers = {} if declared is None else {"Content-Length": str(declared)}

    def read(self, n=-1):
        return self._data.read(n)


# Only https, and only to a source we actually use. The panel hands commands
# whatever it was given, so this is the edge of the world.
refuses("a host we do not use", lambda: apt.Http.get("https://example.com/x"), ValueError)
refuses("plain http to a real source",
        lambda: apt.Http.get("http://aviationweather.gov/x"), ValueError)
refuses("a host that merely ends in one of ours",
        lambda: apt.Http.get("https://nfdc.faa.gov.evil.test/x"), ValueError)
# The host is the parsed hostname, so the usual ways of dressing up a URL to
# read as one of ours do not work: credentials before the @ name the host that
# follows them, and a real host in the path is still just a path.
refuses("an allowed host in the credentials",
        lambda: apt.Http.get("https://nfdc.faa.gov@evil.test/x"), ValueError)
refuses("an allowed host in the path",
        lambda: apt.Http.get("https://evil.test/nfdc.faa.gov"), ValueError)
refuses("a bare address", lambda: apt.Http.get("https://93.184.216.34/x"), ValueError)
# Case is not part of a hostname, so this one has to be allowed.
check("an allowed host shouted", apt._require_fetch_host("https://NFDC.FAA.GOV/x"), None)

# Content-Length is checked before the body is allocated.
refuses("declared over the ceiling",
        lambda: apt._read_capped(Body(10, declared=99 * 1024 * 1024), 1024, "test://big"),
        apt.DownloadTooLarge)

# A body that understates its length, or gives none, is caught while reading.
refuses("understated Content-Length",
        lambda: apt._read_capped(Body(5000, declared=10), 1024, "test://liar"),
        apt.DownloadTooLarge)
refuses("no Content-Length at all",
        lambda: apt._read_capped(Body(5000), 1024, "test://nolen"),
        apt.DownloadTooLarge)

# Under the ceiling the body still arrives whole - a cap that truncates would
# be worse than no cap, because the parse would half-succeed.
check("under the ceiling arrives intact",
      len(apt._read_capped(Body(4096, declared=4096), 8192, "test://ok")), 4096)
check("exactly at the ceiling is allowed",
      len(apt._read_capped(Body(4096, declared=4096), 4096, "test://edge")), 4096)

# urllib follows redirects silently, so each hop is checked on its own.
_guard = apt._RedirectGuard()
_req = urllib.request.Request("https://aeronav.faa.gov/a")


def hop(newurl):
    return _guard.redirect_request(_req, io.BytesIO(b""), 302, "Found", {}, newurl)


refuses("a redirect off our hosts", lambda: hop("https://evil.test/x"), ValueError)
refuses("a redirect downgrading to http",
        lambda: hop("http://aeronav.faa.gov/x"), ValueError)
check("a redirect within our hosts is followed",
      hop("https://aeronav.faa.gov/b").get_full_url(), "https://aeronav.faa.gov/b")

# Every status that redirects has to route through redirect_request, or a hop
# arrives by a door the guard is not standing at.
for _code in (301, 302, 303, 307, 308):
    check("status %d is a redirect the guard sees" % _code,
          hasattr(_guard, "http_error_%d" % _code), True)

# A zip is bounded off its central directory, before anything is decompressed.
apt._load_build_modules()


def _zip(entries, size):
    """An archive whose directory claims `entries` members of `size` each.

    Deflated, so a run of one byte costs almost nothing to store - which is
    exactly the shape of archive the size check exists to refuse."""
    raw = io.BytesIO()
    with apt.zipfile.ZipFile(raw, "w", apt.zipfile.ZIP_DEFLATED) as zf:
        for i in range(entries):
            zf.writestr("m%d.csv" % i, b"y" * size)
    return raw.getvalue()


def _opened(blob):
    return apt.zipfile.ZipFile(io.BytesIO(blob))


refuses("too many entries",
        lambda: apt._zip_within_limits(_opened(_zip(apt.MAX_ZIP_ENTRIES + 1, 1)), "many"),
        apt.DownloadTooLarge)
check("an ordinary archive passes",
      apt._zip_within_limits(_opened(_zip(4, 16)), "ok") is not None, True)

# The point of reading the directory rather than decompressing: this archive is
# a rounding error on disk and eight megabytes once opened. Nothing here is
# inflated to find that out.
_bomb = _zip(2, 4 * 1024 * 1024)
check("the bomb is tiny compressed", len(_bomb) < 64 * 1024, True)
check("and claims 8 MB expanded",
      sum(i.file_size for i in _opened(_bomb).infolist()), 8 * 1024 * 1024)

_ceiling = apt.MAX_ZIP_BYTES
apt.MAX_ZIP_BYTES = 1024 * 1024
refuses("expands past the ceiling",
        lambda: apt._zip_within_limits(_opened(_bomb), "bomb"), apt.DownloadTooLarge)
apt.MAX_ZIP_BYTES = _ceiling
check("and passes once the ceiling clears it",
      apt._zip_within_limits(_opened(_bomb), "bomb") is not None, True)

# The real products must sit under their ceilings, or the plugin cannot build.
# Measured in the 03_Sep_2026 cycle: 7.7 / 1.3 / 0.4 MB compressed, and the
# largest expands to 44 MB across ten members.
check("NASR ceiling clears the measured 7.7 MB",
      apt.MAX_BYTES_NASR > 8 * 1024 * 1024, True)
check("bulk ceiling clears the measured 15.5 MB",
      apt.MAX_BYTES_BULK > 16 * 1024 * 1024, True)
check("zip ceiling clears the measured 44 MB",
      apt.MAX_ZIP_BYTES > 44 * 1024 * 1024, True)
check("zip entry ceiling clears the measured 10", apt.MAX_ZIP_ENTRIES > 10, True)

# A bulk CSV is the one download that fails quietly: DictReader reads an HTML
# error page as rows rather than raising, so the floor is on what parsed, and
# it is checked before the table it replaces is emptied.
_html = ("<!DOCTYPE html>\n<html><body><h1>503 Service Unavailable</h1>\n"
         + "<p>try later</p>\n" * 40 + "</body></html>")
_junk = [(r.get("ident", ""), r.get("name", ""))
         for r in apt.csv.DictReader(io.StringIO(_html))]
check("an error page parses as rows, not an error", len(_junk) > 0, True)
check("but none of them carry an identifier",
      sum(1 for r in _junk if r[0]), 0)
refuses("so the floor refuses it",
        lambda: apt._require_rows("airports.csv", _junk, apt.MIN_OA_AIRPORTS),
        RuntimeError)
refuses("and refuses an empty parse",
        lambda: apt._require_rows("airports.csv", [], apt.MIN_OA_AIRPORTS),
        RuntimeError)

# Rows without an identifier do not count towards the floor - the failure being
# caught produces plenty of rows and no identifiers.
check("a real file passes",
      apt._require_rows("airports.csv", [("K%04d" % i, "x") for i in range(20000)],
                        apt.MIN_OA_AIRPORTS) is not None, True)
refuses("padding with blank rows does not clear the floor",
        lambda: apt._require_rows(
            "airports.csv", [("KATL", "x")] + [("", "")] * 20000, apt.MIN_OA_AIRPORTS),
        RuntimeError)

# The floors must sit under the real files or a good build would be refused.
# Measured: 86,032 world airports and 48,224 runways.
check("airport floor clears the measured 86,032",
      apt.MIN_OA_AIRPORTS < 86032, True)
check("runway floor clears the measured 48,224",
      apt.MIN_OA_RUNWAYS < 48224, True)

if fail:
    sys.exit(1)
print("download limits ok")
