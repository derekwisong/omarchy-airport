# Development

Symlink the repo in and the shell loads from your working tree:

```bash
ln -s "$PWD" ~/.config/omarchy/plugins/derekwisong.airport
omarchy-shell shell rescanPlugins
omarchy restart shell      # required to pick up QML changes
```

`omarchy plugin remove` unlinks rather than deleting the target. To test what a user gets,
remove it and `omarchy plugin add .` instead.

```bash
omarchy plugin validate .     # manifest schema — run it after every change
./tests/smoke.sh              # ~120 checks, network required (--with-osm adds Overpass, AirNav)
python3 tests/limits.py       # download ceilings, hosts, redirects, zip bounds
```

The rest of `tests/` runs offline and takes no arguments — `wx.py`, `geometry.py`,
`traffic.py`, `transport.py`, `overpass.py`, and `escaping.js`, `scope.js`, `wind.js`
under `node`.

NASR rows are positional arrays over the allowlists at the top of `apt.py`; a column not on its
list reads back as absent, so add it there and rebuild. Never name a QML property `data` —
`Item.data` is the default children list and shadows it silently.

