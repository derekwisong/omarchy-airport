#!/usr/bin/env python3
"""Present weather: the coded half of a METAR, read out in English.

Offline. These are the groups a pilot reads first and the panel used to drop
entirely - a thunderstorm over the field said nothing at all.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import apt  # noqa: E402

fail = 0


def check(name, got, want):
    global fail
    if got == want:
        return
    fail += 1
    print("FAIL %s\n     wanted: %r\n     got:    %r" % (name, want, got))


# The plain ones: intensity and a thing falling out of the sky.
check("light rain", apt.wx_phrase("-RA"), "light rain")
check("heavy snow", apt.wx_phrase("+SN"), "heavy snow")
check("rain", apt.wx_phrase("RA"), "rain")
check("two things at once", apt.wx_phrase("RASN"), "rain and snow")

# The storm is the headline and the rain in it is a detail of the storm.
check("a thunderstorm with rain in it", apt.wx_phrase("-TSRA"),
      "thunderstorm with light rain")
check("a thunderstorm on its own", apt.wx_phrase("TS"), "thunderstorm")
check("a storm nearby", apt.wx_phrase("VCTS"), "thunderstorm in the vicinity")

# Descriptors change what the phenomenon means, so they are not adjectives.
check("showers", apt.wx_phrase("+SHRA"), "heavy rain showers")
check("showers with nothing named", apt.wx_phrase("SH"), "precipitation showers")
check("freezing fog", apt.wx_phrase("FZFG"), "freezing fog")
check("freezing rain", apt.wx_phrase("FZRA"), "freezing rain")
check("blowing snow", apt.wx_phrase("BLSN"), "blowing snow")
check("low drifting snow", apt.wx_phrase("DRSN"), "low drifting snow")
check("shallow fog", apt.wx_phrase("MIFG"), "shallow fog")
check("patchy fog", apt.wx_phrase("BCFG"), "patchy fog")

# Obscurations have no intensity and need none.
check("mist", apt.wx_phrase("BR"), "mist")
check("haze", apt.wx_phrase("HZ"), "haze")
check("volcanic ash", apt.wx_phrase("VA"), "volcanic ash")

# A tornado is coded as a heavy funnel cloud and is not "heavy funnel cloud".
check("a tornado is named", apt.wx_phrase("+FC"), "tornado or waterspout")
check("a funnel cloud is not a tornado", apt.wx_phrase("FC"), "funnel cloud")

# Groups join in the order the observer wrote them.
check("a whole METAR group", apt.present_weather("-TSRA BR"),
      "thunderstorm with light rain, mist")
check("several groups", apt.present_weather("+SHRA VCTS"),
      "heavy rain showers, thunderstorm in the vicinity")

# Nothing reported is nothing said - never "no weather".
check("clear skies say nothing", apt.present_weather(""), "")
check("None says nothing", apt.present_weather(None), "")
check("nonsense says nothing", apt.wx_phrase("XYZZY"), "")

if fail:
    sys.exit(1)
print("present weather ok")
