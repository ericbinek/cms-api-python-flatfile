# Contributing to cms-api-python-flatfile

Thanks for taking a look. This is a build-in-public project at version 0.4.0, so it is still moving and contributions of every kind are welcome: bug reports, questions, ideas, and code.

## Ground rules

- Stay on the standard library. The point of this project is the standard library, so please do not add pip packages.
- The conformance test suite is the contract. If you change behavior, change the tests in the same pull request and explain why. Keep them green.
- This is not production software, and the README says so. Please keep that framing.

## Getting started

```sh
git clone https://github.com/ericbinek/cms-api-python-flatfile.git
cd cms-api-python-flatfile
cp .env.example .env
```

Run it:

```sh
python3 -m app
```

Run the tests:

```sh
python3 -m unittest discover tests
```

There is no `pip install` and no virtual environment to manage: the standard library is all you need.

## Sending a change

1. For anything beyond a small fix, open an issue or discussion first so we do not duplicate work.
2. Keep each pull request focused on one thing.
3. Run the test suite locally and make sure it is green before you open the pull request.
4. Describe what changed and why.

## Style

Type hints and the standard library, no framework. Match the surrounding code.
