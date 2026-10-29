# Third-party test data

The repositories below are downloaded into the ignored `test-data/` directory
for local parser and retrieval testing. Their contents are not vendored or
redistributed by this project.

| Project | Inspected commit | Local use | License |
| --- | --- | --- | --- |
| [py-pdf/sample-files](https://github.com/py-pdf/sample-files) | `02b8203bf416db3db03438bc8278dfcb0555f3` | PDF extraction fixtures | CC BY-SA 4.0 |
| [commonmark/commonmark-spec](https://github.com/commonmark/commonmark-spec) | `8a5f7646e9f67c3004f023d262b3e6b596afc2ed` | Markdown/text retrieval corpus | Spec content CC BY-SA 4.0; test software BSD-style |

No upstream scripts are executed as part of indexing or tests.

## Local history evaluation corpus

The ignored `test-data/history/` directory contains plain-text editions of the
following works downloaded from Project Gutenberg. Project Gutenberg marks each
selected work as public domain in the United States.

| Project Gutenberg eBook | Work |
| --- | --- |
| [1](https://www.gutenberg.org/ebooks/1) | Thomas Jefferson, *The Declaration of Independence* |
| [5](https://www.gutenberg.org/ebooks/5) | *The United States Constitution* |
| [147](https://www.gutenberg.org/ebooks/147) | Thomas Paine, *Common Sense* |
| [18](https://www.gutenberg.org/ebooks/18) | Hamilton, Jay, and Madison, *The Federalist Papers* |
| [16960](https://www.gutenberg.org/ebooks/16960) | Charles A. Beard and Mary Ritter Beard, *History of the United States* (1921) |

The Beard textbook is historical source material with period-specific language,
interpretations, inclusions, and omissions. It is not labeled or treated as
current scholarly consensus.

## Local runtime models

The following models are downloaded to Ollama's user model store and are not
vendored by this repository:

| Model | Local ID | License shown by Ollama | Use |
| --- | --- | --- | --- |
| `qwen3:4b-instruct` | `0edcdef34593` | Apache 2.0 | Default non-thinking generation and tool selection |
| `qwen3:4b` | `359d7dd4bcda` | Apache 2.0 | Earlier thinking build, retained locally |
| `qwen3-embedding:0.6b` | `ac6da0dfba84` | Apache 2.0 | Local document/query embeddings |

## Code sandbox runtime (trial)

Used by the WebAssembly sandbox trial in `evals/sandbox_trial/`. Neither is
vendored by this repository.

| Component | Version | Source | License |
| --- | --- | --- | --- |
| `wasmtime` (Python package) | 50.0.1 | [PyPI](https://pypi.org/project/wasmtime/), installed with `pip install -e ".[sandbox]"` | Apache-2.0 WITH LLVM-exception |
| CPython for WASI | 3.14.9 (`wasi_sdk-24`) | [brettcannon/cpython-wasi-build](https://github.com/brettcannon/cpython-wasi-build/releases/tag/v3.14.9), zip sha256 `8de7834105edef8db8a13299e2587cf8945021dd8764f2691d83bbc25129dfa2`, unpacked under `%LOCALAPPDATA%\kiki\wasi-python\` | PSF License |

## Weather data

Live weather uses the [Open-Meteo APIs](https://open-meteo.com/) and displays
the required attribution in terminal output. Use is subject to Open-Meteo's
[terms](https://open-meteo.com/en/terms); data is fetched at request time and is
not included in this repository.


## Adapted source code

| Project | Commit | Files | Used in | License |
| --- | --- | --- | --- | --- |
| [rhenryliu/zotero-rag](https://github.com/rhenryliu/zotero-rag) | `a9f308d27d6074c3a8c0478af23787ae4251acd1` | `rag/chunking.py` (`chunk_document`, `_hard_split`) | `src/kiki/pdf_chunking.py` | MIT |

What was adapted: the page-tagged paragraph stream, character-budget packing,
and sentence-boundary splitting of oversized paragraphs. Kiki changed overlap
(whole paragraph with its own pages instead of a character tail credited to the
next page), added cross-page sentence joining, per-offset page maps for split
pieces, and running header/footer removal. Zotero RAG's `rag/reranking.py`
was studied for design only (fallback to retrieval order, calibrated score
bands); none of its code is included.

The license of the adapted code:

```text
MIT License

Copyright (c) 2026 R. Henry Liu

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
