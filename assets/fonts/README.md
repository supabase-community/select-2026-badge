# `assets/fonts/` -- the one face this project owns

The Tufty's ROM carries 37 PIXEL fonts and no outlines, so every outline face lives on the badge's own filesystem at `/system/assets/fonts/` and `font.load` resolves it by bare name.

A finished badge carries three faces. This export carries one:

| face | in this export | where it comes from |
|---|---|---|
| `MonaSans-Medium.af` | yes | this project's own OFL rebuild; six shipping apps call `font.load("MonaSans-Medium")` |
| `DynaPuff-Medium.af` | no | yours: the Badgeware v3.0.2 release |
| `IndieFlower-Regular.af` | no | yours: the Badgeware v3.0.2 release |

## The two stock faces are a BUILD INPUT you supply

**They are an ARGUMENT to the build, not something it resolves**, because a build that reaches the network is not a build we would ask you to trust. `BUILDING.md` section 2.3 specifies the step; this is the short version:

```sh
python3 tools/build.py --stock-fonts <badgeware>/firmware/assets/fonts ...
```

You are Pimoroni, so the input is already on your disk. In a **v3.0.2** release clone the two faces sit at:

```
<badgeware>/firmware/assets/fonts/DynaPuff-Medium.af
<badgeware>/firmware/assets/fonts/IndieFlower-Regular.af
```

The build verifies both against these pinned SHA-256s BEFORE copying, so a release that moved underneath us is a refusal rather than a silent substitution:

| face | SHA-256 |
|---|---|
| `DynaPuff-Medium.af` | `e15bd8b9709b6196da4b4fa74a94ca3f23a24d9b9fd8d8776d733136cd74649b` |
| `IndieFlower-Regular.af` | `a917728b392046f7bcd90575652613884af7bd3e9c435b7ca8b93cb07fae935c` |

These are the same constants the bytecode exporter refuses on, so the two artifacts cannot disagree about which bytes a badge carries.

**Without `--stock-fonts` the build stops.** `--no-stock-fonts` overrides that and is an explicit, printed decision to ship a `/system` with one face: the tree replaces `/system` wholesale, so dropping either stock face is a REMOVAL from a stock badge rather than an omission from a package. 19,444 bytes of a 12 MB volume is not a budget argument.

They are not committed to this project's repository because the pinned release publishes no licence grant for them; they travel under the release's own terms, which is why there is no licence file here for them and there is one for MonaSans.

## MonaSans-Medium

Rebuilt from a pinned OFL release rather than from Google Fonts' moving main branch, because newer Mona Sans releases changed both coverage and advances and this project measures text.

- upstream: `github:github/mona-sans`
- pinned release: `2.0.8`
- rebuild quality: 180 px
- licence: `LICENSE-MonaSans` in this directory (SIL Open Font License)

The rebuild recipe itself is host tooling and is not in this export.
