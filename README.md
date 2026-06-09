# schema.org aligned CMS API (Python)

[![Tests](https://github.com/ericbinek/cms-api-python-flatfile/actions/workflows/test.yml/badge.svg)](https://github.com/ericbinek/cms-api-python-flatfile/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)
![Status](https://img.shields.io/badge/status-work_in_progress-orange.svg)
![Build in public](https://img.shields.io/badge/build-in_public-ff69b4.svg)
![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)
![Python 3.14](https://img.shields.io/badge/Python-3.14-blue.svg)

A standalone, schema.org aligned CMS API written in plain Python 3.14.

There is no `requirements.txt` to install and no virtual environment to activate. It runs on the standard library, `http.server` to serve and `unittest` to test.

It exposes CRUD endpoints for 10 schema.org entity types such as BlogPosting, Person, and WebPage, backed by flat-file JSON storage, with validation, pagination, filtering, sorting, ETag caching, and reference embedding.

A conformance test suite defines the HTTP contract.

## Status: work in progress (v0.1.0)

This is an ongoing build-in-public project, shared only for community and communication purposes. Do not deploy it in production. Do not rely on its interfaces or data format remaining stable.

## No virtualenv

Modern Python usually pushes you into a virtual environment before you can `pip install` anything (PEP 668). Here there is nothing to install, so there is no venv to create. The whole thing is the standard library: `http.server`, `json`, `unittest`. Run it with the system `python3`.

## Requirements

- Python 3.14 or newer

## Installation

```sh
git clone https://github.com/ericbinek/cms-api-python-flatfile.git
cd cms-api-python-flatfile
cp .env.example .env
```

## Running

```sh
python3 -m app
```

The server listens on `PORT` (default 3004).

## Usage

```sh
curl http://localhost:3004/blog-postings
```

All list endpoints return `{ items, total }`. See per-entity routes below.

## Entities

- `BlogPosting`
- `Person`
- `WebPage`
- `ImageObject`
- `CategoryCode`
- `CategoryCodeSet`
- `DefinedTerm`
- `DefinedTermSet`
- `Comment`
- `WebSite`

## Testing

```sh
python3 -m unittest discover tests
```

## Contributing

Contributions are welcome. This is a build-in-public project, so issues, questions, and ideas count as much as pull requests. If you send code, keep it on the standard library with no new dependencies, use type hints, and keep the conformance suite green, since the tests are the contract. Run them with `python3 -m unittest discover tests`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guidelines.

## License

MIT. See [LICENSE](LICENSE).
