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

## Weather data

Live weather uses the [Open-Meteo APIs](https://open-meteo.com/) and displays
the required attribution in terminal output. Use is subject to Open-Meteo's
[terms](https://open-meteo.com/en/terms); data is fetched at request time and is
not included in this repository.

