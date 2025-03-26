# datasette-profiles

[![PyPI](https://img.shields.io/pypi/v/datasette-profiles.svg)](https://pypi.org/project/datasette-profiles/)
[![Changelog](https://img.shields.io/github/v/release/datasette/datasette-profiles?include_prereleases&label=changelog)](https://github.com/datasette/datasette-profiles/releases)
[![Tests](https://github.com/datasette/datasette-profiles/actions/workflows/test.yml/badge.svg)](https://github.com/datasette/datasette-profiles/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/datasette/datasette-profiles/blob/main/LICENSE)

Editable user profile pages for Datasette

## Installation

Install this plugin in the same environment as Datasette.
```bash
datasette install datasette-profiles
```
## Usage

Usage instructions go here.

## Development

To set up this plugin locally, first checkout the code. Then create a new virtual environment:
```bash
cd datasette-profiles
python -m venv venv
source venv/bin/activate
```
Now install the dependencies and test dependencies:
```bash
pip install -e '.[test]'
```
To run the tests:
```bash
python -m pytest
```
