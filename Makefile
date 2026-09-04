# Release plumbing for ufo-tdkit-report.
#
# `make publish` is the only irreversible target in here, and PyPI is unusually
# unforgiving about it: a version number can be yanked but never re-uploaded, so a
# wrong artefact is permanent under that number. Everything before the upload is
# therefore a gate, and each one exists because it is cheap here and expensive after.
#
# Credentials are never stored in this file. `uv publish` reads UV_PUBLISH_TOKEN, or
# ~/.pypirc. Better still, publish from CI with PyPI Trusted Publishing and keep no
# token anywhere -- see the note at the bottom of this file.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

NAME    := ufo-tdkit-report
VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)
TAG     := v$(VERSION)

.DEFAULT_GOAL := help
.PHONY: help test lint check build verify clean guard-clean guard-tag guard-unpublished publish-test publish release-checklist

help: ## Show this list
	@grep -hE '^[a-z][a-zA-Z0-9_-]*:.*?## ' $(MAKEFILE_LIST) \
	  | awk -F':.*?## ' '{printf "  \033[1m%-20s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  $(NAME) $(VERSION)  (tag $(TAG))"

test: ## Run the full suite
	uv run --extra dev pytest -q

lint: ## Ruff
	uv run --extra dev ruff check .

check: test lint ## Suite + lint

clean: ## Remove built artefacts
	rm -rf dist build *.egg-info

build: clean ## Build the sdist and the wheel from a clean dist/
	uv build
	@ls -1 dist/

# --- gates -------------------------------------------------------------------------

guard-clean: ## Fail unless the working tree is clean and matches origin/main
	@test -z "$$(git status --porcelain)" \
	  || { echo "error: working tree is dirty; publishing it would ship something no commit records"; exit 1; }
	@test "$$(git rev-parse --abbrev-ref HEAD)" = "main" \
	  || { echo "error: not on main (on $$(git rev-parse --abbrev-ref HEAD))"; exit 1; }
	@git fetch --quiet origin main
	@test "$$(git rev-parse HEAD)" = "$$(git rev-parse origin/main)" \
	  || { echo "error: HEAD and origin/main differ; push or pull first"; exit 1; }

guard-tag: ## Fail unless tag v<version> exists and points at HEAD
	@git rev-parse -q --verify "refs/tags/$(TAG)" >/dev/null \
	  || { echo "error: tag $(TAG) does not exist. Cut the release first (see CLAUDE.md), then publish."; exit 1; }
	@test "$$(git rev-parse "$(TAG)^{commit}")" = "$$(git rev-parse HEAD)" \
	  || { echo "error: $(TAG) does not point at HEAD -- you would publish code the tag does not describe"; exit 1; }

guard-unpublished: ## Fail if this version is already on PyPI
	@code=$$(curl -sS -o /dev/null -w '%{http_code}' "https://pypi.org/pypi/$(NAME)/$(VERSION)/json" || echo 000); \
	if [ "$$code" = "200" ]; then \
	  echo "error: $(NAME) $(VERSION) is already on PyPI. A version can be yanked but never re-uploaded -- bump the version."; exit 1; \
	elif [ "$$code" != "404" ]; then \
	  echo "error: could not reach PyPI to check (HTTP $$code); refusing to guess"; exit 1; \
	fi

verify: build ## Check the metadata renders, and that the built wheel actually runs
	uvx twine check --strict dist/*
	@tmp=$$(mktemp -d); \
	uv venv --quiet "$$tmp/venv"; \
	VIRTUAL_ENV="$$tmp/venv" uv pip install --quiet dist/*.whl; \
	got=$$("$$tmp/venv/bin/tdreport" --version); \
	rm -rf "$$tmp"; \
	test "$$got" = "tdreport $(VERSION)" \
	  || { echo "error: installed wheel reports '$$got', expected 'tdreport $(VERSION)'"; exit 1; }
	@echo "ok: wheel installs clean and the entry point runs"

# --- publishing --------------------------------------------------------------------

publish-test: verify ## Upload to TestPyPI (safe rehearsal; needs UV_PUBLISH_TOKEN for TestPyPI)
	uv publish --publish-url https://test.pypi.org/legacy/ dist/*
	@echo
	@echo "Installed check:"
	@echo "  uv tool install --index-url https://test.pypi.org/simple/ \\"
	@echo "    --extra-index-url https://pypi.org/simple/ $(NAME)==$(VERSION)"

publish: guard-clean guard-tag guard-unpublished check verify ## Upload to PyPI (IRREVERSIBLE)
	@echo
	@echo "  About to publish $(NAME) $(VERSION) to PyPI from $(TAG)."
	@echo "  This cannot be undone: the version can be yanked, never replaced."
	@echo
	@if [ "$${CONFIRM:-}" != "yes" ]; then \
	  read -r -p "  Type the version to confirm: " answer; \
	  test "$$answer" = "$(VERSION)" || { echo "  aborted"; exit 1; }; \
	fi
	uv publish dist/*
	@echo
	@echo "Published. Remaining steps that PyPI does not do for you:"
	@echo "  - gh release create $(TAG) --title $(TAG) --notes-file <CHANGELOG section> --verify-tag --latest"
	@echo "  - tell consumers pinning by git tag (TDKit) that a version range now works"

release-checklist: ## Print the order of operations, without doing anything
	@echo "  1. move [Unreleased] into [X.Y.Z] - <today> in CHANGELOG.md, add the compare link"
	@echo "  2. bump version in pyproject.toml, then: uv lock"
	@echo "  3. make check"
	@echo "  4. git commit -am 'chore(release): X.Y.Z' && git tag -a vX.Y.Z -m vX.Y.Z"
	@echo "  5. git push origin main --follow-tags"
	@echo "  6. make publish-test   # optional rehearsal on TestPyPI"
	@echo "  7. make publish"
	@echo "  8. gh release create vX.Y.Z ...   # a pushed tag is NOT a Release"

# Trusted Publishing (recommended once the repo is public)
# ------------------------------------------------------------------------------------
# PyPI can accept uploads from a named GitHub Actions workflow with no token at all,
# which removes the only long-lived secret this project would otherwise have. Configure
# it at https://pypi.org/manage/project/ufo-tdkit-report/settings/publishing/ and add a
# workflow with `permissions: id-token: write` that runs `uv build` then `uv publish`.
# The gates above still apply locally; `make publish` remains the manual path.
