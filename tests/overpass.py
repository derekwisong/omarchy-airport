#!/usr/bin/env python3
"""Overpass mirror rotation, offline.

The failure that hurts is not a mirror that refuses - it is one that accepts
the connection and then sits on it. ATL cost about a hundred seconds that way
while the other two mirrors were answering the same query in three, so the
rotation has to give every mirror a short look before any of them gets the
patient one.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.argv = ["apt.py"]
import apt  # noqa: E402

failed = 0


def check(name, got, want):
    global failed
    if got != want:
        failed += 1
        print("FAIL %s\n     wanted: %s\n     got:    %s" % (name, want, got))
    else:
        print("ok   %s" % name)


class FakeHttp:
    """Records the timeout each attempt was given, and answers on cue."""

    def __init__(self, answer_on=None):
        self.calls = []          # (endpoint, timeout)
        self.answer_on = answer_on

    def get(self, url, data=None, timeout=90, retries=3, **kw):
        self.calls.append((url, timeout))
        if self.answer_on is not None and url == self.answer_on:
            return '{"elements": []}'
        raise TimeoutError("the read operation timed out")


def run(answer_on=None):
    fake = FakeHttp(answer_on)
    real_get, real_sleep = apt.Http.get, apt.time.sleep
    apt.Http.get = fake.get
    apt.time.sleep = lambda _s: None
    try:
        try:
            result = apt.overpass_query("[out:json];out;")
        except Exception as exc:
            result = exc
    finally:
        apt.Http.get, apt.time.sleep = real_get, real_sleep
    return fake.calls, result


first, last = apt.OVERPASS_ENDPOINTS[0], apt.OVERPASS_ENDPOINTS[-1]
mirrors = len(apt.OVERPASS_ENDPOINTS)

# A stuck first mirror must not eat the whole budget before the second is
# tried: every mirror gets the short timeout before any gets the long one.
calls, _ = run()
check("every mirror tried twice", len(calls), mirrors * 2)
check("first pass is short on every mirror",
      [t for _, t in calls[:mirrors]], [apt.OVERPASS_FIRST_PASS] * mirrors)
check("second pass is patient on every mirror",
      [t for _, t in calls[mirrors:]], [90] * mirrors)
check("first pass reaches the last mirror",
      calls[mirrors - 1][0], last)

# The short pass is a real attempt, not a probe: an answer there ends it.
calls, result = run(answer_on=last)
check("an answer on the short pass stops the rotation", len(calls), mirrors)
check("and returns the parsed body", result, {"elements": []})

# A mirror answering immediately costs exactly one call.
calls, _ = run(answer_on=first)
check("a healthy first mirror costs one call", len(calls), 1)

# The declared server-side timeout must be collectable: a server still working
# past the client's patience is doing work nobody can ever read.
for name, query in (("q_pois", apt.q_pois((33.6, -84.5, 33.7, -84.4))),
                    ("q_aerodrome", apt.q_aerodrome(33.6, -84.4))):
    declared = int(query.split("timeout:")[1].split("]")[0])
    check("%s server timeout is under the client's" % name, declared < 90, True)

sys.exit(1 if failed else 0)
