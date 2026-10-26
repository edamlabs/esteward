# Upstream issue drafts

Texts ready to file, one per upstream repository. The org's classifier blocks the engine's instances from
opening issues on third-party repositories, so Damien files them. Data verified against crates.io and OSV
on 2026-10-26; chains are the exact output of `cargo tree -i` on our lockfiles (edamlabs/e-voice,
edamlabs/anytomd), reproduced by esteward's act stage.

## 1 · npyz — https://github.com/ExpHP/npyz

**Title:** Allow `zip ^9` (and consider dropping zip's default features): `zip 0.6` carries RUSTSEC-2026-0367/0368/0369

**Body:**

npyz 0.9.1 (the latest release) depends on `zip ^0.6` with default features on non-wasm targets. Downstream
lockfiles therefore pin `zip 0.6.6` and, through zip's defaults, `zstd 0.11.2+zstd.1.5.2` /
`zstd-safe 5.0.2+zstd.1.5.2`:

- `zip 0.6.6`: RUSTSEC-2026-0367, RUSTSEC-2026-0368, RUSTSEC-2026-0369 — fixed in zip 9.0.0.
- `zstd-safe 5.0.2+zstd.1.5.2`: RUSTSEC-2026-0395, -0397, -0399, -0400, -0401, -0402, -0403, -0404, -0406 —
  fixed in zstd-safe 8.2.0, reachable only through zstd ≥ 0.14.3; zip 0.6's `zstd ^0.11.2` can never get there.

We hit this in edamlabs/e-voice (`evoice-tts → npyz 0.9.1 → zip 0.6.6`). We never call
`ZipArchive::extract`, the affected path, but every consumer ends up documenting why they are unaffected,
forever.

The ask: the wasm32 dependency already uses `default-features = false, features = ["deflate"]` — npz only
needs deflate. Doing the same on non-wasm targets, and widening the requirement to `zip ^9` (≥ 9.1.2, which
moved its optional zstd to `^0.14.2`), clears the zip advisories and the whole zstd chain in one change.
For reference, calamine 0.37 already ships `zip ^9.0`.

## 2 · sherpa-onnx — https://github.com/k2-fsa/sherpa-onnx

**Title:** Backport the `zip ^9` build dependency to the 1.x line (sherpa-onnx-sys)

**Body:**

sherpa-onnx-sys 1.13.8 declares `zip ^2` as a build dependency, which pins `zip 2.6.1` downstream and,
through zip's default features, `zstd 0.13.3` / `zstd-safe 7.3.0`:

- `zip 2.6.1`: RUSTSEC-2026-0367, RUSTSEC-2026-0368, RUSTSEC-2026-0369 — fixed in zip 9.0.0.
- `zstd 0.13.3`: RUSTSEC-2026-0391 — fixed in zstd 0.14.3.
- `zstd-safe 7.3.0`: RUSTSEC-2026-0395 through RUSTSEC-2026-0406 (12 advisories) — fixed in zstd-safe 8.2.0.

sherpa-onnx-sys 2.0.0 already declares `zip ^9`, which resolves all of the above (zip 9.1.2 requires
`zstd ^0.14.2`). Projects on the 1.x API cannot consume that without a major upgrade; ours
(edamlabs/e-voice: `evoice-core/stt/tts → sherpa-onnx 1.13.8`) pins 1.13.8.

The ask: a patch release on the 1.x line (e.g. 1.13.9) carrying the same `zip ^9` build dependency as
2.0.0. The build script extracts bundled archives, so `default-features = false` with only the needed
codecs would additionally keep the tree off zstd entirely.

## 3 · anytomd-rs — https://github.com/developer0hye/anytomd-rs

**Title:** Allow `zip ^9`: `zip 8.6.0` carries RUSTSEC-2026-0367/0368/0369

**Body:**

anytomd 1.3.1 requires `zip ^8.2`, which pins `zip 8.6.0` downstream:

- `zip 8.6.0`: RUSTSEC-2026-0367, RUSTSEC-2026-0368, RUSTSEC-2026-0369 — fixed in zip 9.0.0.

We hit this in edamlabs/anytomd (`anytomd 1.3.1 ← anytomd-native`, our Python extension).

The ask: widen the requirement to `zip ^9`. anytomd 1.3.1 also depends on `calamine ^0.36`; calamine 0.37
already uses `zip ^9.0`, so bumping both lands the whole tree on a single, fixed zip.
