# Contributing

This repository is GENERATED. Every file in it is assembled, gated and hashed out of a canonical internal repository by an exporter, and `MANIFEST.json` records the exact canonical commit each publish was cut from. This repository is a projection of that one, never a fork of it.

Pull requests are welcome, and this is what happens to one:

1. You open a PR here, as you would anywhere.
2. An accepted change is re-landed in the canonical repository with your authorship credited, and the next publish carries it back here.
3. A change merged only here and never re-landed is OVERWRITTEN by the next publish. The publish tooling refuses to run while such a change exists, so an accepted contribution cannot be lost silently: it is re-landed first, then republished.

`README.md` explains what this tree is and how to build it. `MANIFEST.json` carries a SHA-256 for every file in the tree except itself -- it cannot hash itself without changing what it says -- so you can verify that the tree you cloned is the tree that was published:

```sh
python3 tools/build.py --verify-manifest
```

**There is no LICENSE file in this tree yet**, and that is an open item rather than an oversight: `assets/fonts/LICENSE-MonaSans` covers the font only, and terms for the rest of this source have not been settled. Ask before you rely on them.
