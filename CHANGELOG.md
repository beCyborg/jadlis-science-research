# Changelog — jadlis-science-research

Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).
История до 1.0.0 — плагин `jadlis-research` 1.0.0–1.3.0 в репо [jadlis-start](https://github.com/beCyborg/jadlis-start) (`plugins/jadlis-research/CHANGELOG.md` до split).

## [Unreleased]

## [2.0.0] — 2026-09-10

### Для человека

- Плагин переименован: `science-research` → `jadlis-science-research`. Строка установки теперь `claude plugin install jadlis-science-research@jadlis`, маркетплейс добавляется из `https://github.com/beCyborg/jadlis-hub`. Короткая команда `/science-research` не изменилась; полная форма стала `/jadlis-science-research:science-research`.
- Зависимость `search` переименована в `jadlis-search` — ставить её нужно первой и сразу с ключами: `claude plugin install jadlis-search@jadlis --config BRAVE_API_KEY=… --config FIRECRAWL_API_KEY=…`. Совместимости со старыми именами нет: переустанови оба плагина.
- README (RU и EN): убраны два места с «[уточнить]» — сказано прямо, что ключи лежат в Связке ключей macOS, аналога `security`-помощника на Linux нет и под Linux ничего не проверялось, а сам плагин проверялся только на macOS.

### For agents

- `.claude-plugin/plugin.json`: `name` → `jadlis-science-research`, `version` → 2.0.0, dependency `search ^1` → `jadlis-search ^2` (old tags `search--v1.x` carry a different prefix and no longer match).
- `workflows/search-paper-core.js` and `skills/science-research/SKILL.md`: agent ids `science-research:{researcher-opus,synth-fable,synth-opus}` → `jadlis-science-research:*`.
- MCP tool names `mcp__plugin_search_*` → `mcp__plugin_jadlis-search_*` across SKILL.md, protocols, references and `scripts/places-fetch.sh`.
- `scripts/secret.sh`: plugin id for the class-A key lookup `search@jadlis` → `jadlis-search@jadlis` (and the prefix fallback `search@` → `jadlis-search@`); `/search:keys` → `/jadlis-search:keys` in scripts and docs.
- `SHARED_FROM.txt` / `tools/sync-shared.sh`: source plugin renamed to `jadlis-search`; the recorded tag `search--v1.0.0` and its SHA stay as they are — that is the tag the vendored copy actually came from.
- `.github/workflows/ci.yml`: the reusable-workflow caller now points at `beCyborg/jadlis-hub`.
- Skill folders are not renamed; frontmatter `name: science-research` stays bare, so `/science-research` keeps working.

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
