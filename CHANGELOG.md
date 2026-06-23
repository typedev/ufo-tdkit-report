# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.1.0] - 2026-06-23

### Added
- Initial standalone release, extracted from TDKit's `tdkit.report`.
- Semantic source-change diff: outlines (coordinate-based), kerning/groups, fontinfo,
  OpenType features (`feaLib` rule level), designspace, and build-profile YAML.
- Working-tree commit assistant (`tdreport`, `tdreport <repo>`, `tdreport ... commit`).
- Range / release-notes aggregation (`tdreport <range>`, `tdreport --notes`).
- Repo name registry (`tdreport add <name> <path>`) — explicit registration; cwd and
  explicit paths work without it.
- Opt-in grounded AI narration (`--ai-note`, `ANTHROPIC_API_KEY`), facts attached for
  verification.

### Changed (vs. the in-TDKit version)
- Repo-centric instead of profile-centric: addressed by cwd / registered name / path,
  not by a build-profile name.
- Build-tool-agnostic: no dependency on a profile database or an option schema. The
  profile-option *consequence* schema is injected by the consumer (`fold_facts(schema=)`)
  rather than self-loaded.
- AI key / config resolved from this tool's own config dir (`~/.config/ufo-tdkit-report/`).
