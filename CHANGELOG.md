# Changelog — science-research

Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).
История до 1.0.0 — плагин `jadlis-research` 1.0.0–1.3.0 в репо [jadlis-start](https://github.com/beCyborg/jadlis-start) (`plugins/jadlis-research/CHANGELOG.md` до split).

## [Unreleased]

## [1.0.1] — 2026-09-07

### Для человека

- Починены пути к протоколам: после сплита они указывали на папку `skills/search-paper`, которой в репозитории нет, — агенты получали несуществующие адреса протоколов, `quality-framework.md` и `sample-report.md`.

### For agents

- `workflows/search-paper-core.js:61` and the constants block of `skills/science-research/SKILL.md`: `${PLUGIN_ROOT}/skills/search-paper` → `${PLUGIN_ROOT}/skills/science-research`. Leftover from the 1.0.0 split of `jadlis-research` 1.3.0, where the skill folder was renamed but the paths were not.

## [1.0.0] — 2026-09-07

### Для человека

- Первый релиз под именем `science-research`: выделен из `jadlis-research` 1.3.0 (репо на плагин, команда `/science-research`).

### For agents

- Split of `jadlis-research` 1.3.0 by `tools/split-research.py` (hub). Namespaces: MCP tools `mcp__plugin_search_*`, agents `science-research:*`, commands `/search`, `/search:keys`, `/research`, `/science-research`, `/verif`.
