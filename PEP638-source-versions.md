# PEP 638 build: exact source versions

Read from the checkouts used for the build (2026-10-11).

## Patched repositories

| Repository | Tag | Commit |
|---|---|---|
| `python/cpython` | `v3.14.2` | `df793163d5821791d4e7caf88885a2c11a107986` |
| `pyodide/pyodide` | `314.0.7` | `b1e4fcc2488962f6360a97f19b9982d6fdb5d16f` |
| `emscripten-core/emscripten` | `5.0.3` | `285c424dfa9e83b03cf8490c65ceadb7c45f28eb` |

### CPython

`pep638-cpython-3.14.2.patch` applies on top of the commit above. The local commit holding
the work is `babbdd7db40501074e0529c227f4bc8915ac9ce9`; it exists only in the build session's
checkout, so the patch file is the portable form.

### Pyodide

`pep638-pyodide-314.0.7.patch` applies on top of the commit above (console macro persistence).

Two further local edits are not in the patch, because they only work around blocked downloads
in the build sandbox:

- `cpython/Makefile`: local sources for xz, zstd and SQLite.
- `packages/pydoc_data/meta.yaml` and `packages/test/meta.yaml`: local CPython tarball instead
  of the python.org download.

### Emscripten

On top of the tag:

- Pyodide's own five patches from `emsdk/patches/`.
- `-Werror` removed on line 61 of `tools/system_libs.py`, because LLVM 23.1.3 raises warnings
  in Emscripten's system libraries that the LLVM snapshot it was developed against did not.

## Unpatched dependencies

| Component | Version | Commit / source |
|---|---|---|
| `pyodide/pyodide-build` (submodule) | `0.37.0-11` | `79fb82b2a576a833a12f3889061ca976de2f4167` |
| `libffi/libffi` | pinned by Pyodide | `f08493d249d2067c8b3207ba46693dd858f95db3` |
| `pyodide/hiwire` | pinned by Pyodide | `6a1e67280a15d929ebeceee54a6358c9c8d5f697` |
| `madler/zlib` | `v1.3.1` | `51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf` |
| `emscripten-ports/bzip2` | `1.0.6` | `60ce9dfe9a75f7ee92956aba8a83d1a37625bc1d` |
| LLVM | `llvmorg-23.1.3` release binary (`LLVM-23.1.3-Linux-X64.tar.xz`) | clang reports `0d261d1ca552c95a8f007e061c787ac7132fbcbc` |
| Binaryen | `version_127` release binary | n/a |
| xz | 5.2.2 release tarball (`xz-mirror/xz`) | n/a |
| zstd | 1.5.7 release tarball (`facebook/zstd`) | n/a |
| SQLite | 3.52.0 | amalgamation shipped in npm `sqlite3@6.0.1` |

## Differences from a stock Pyodide 314.0.7 build

- LLVM and Binaryen come from their GitHub releases rather than the emsdk snapshot.
- zstd comes from the `facebook/zstd` release rather than `python/cpython-source-deps`.
- SQLite is 3.52.0 rather than 3.39.0.
