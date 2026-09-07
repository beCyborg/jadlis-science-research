Русский · [English](#english)

# Как предложить правку

Репозиторий публичный, пишет в него только владелец. Правки — через **форк + pull request**.

1. Форк и ветка от `main`.
2. Перед коммитом: `claude plugin validate . --strict`, `gitleaks git .`; README — по контракту (RU + EN, одинаковые H2, без Mermaid).
3. Одна тема — один PR. В описании — что меняется для получателя.
4. Ключи, почты, личные пути в репо не попадают.

`scripts/` и `shared/` — копия из плагина `search` (источник правды — репо `jadlis-search`). Не правь их здесь: `bash tools/sync-shared.sh <search--vX.Y.Z>` обновляет копию и `SHARED_FROM.txt`.

Релизы и теги (`science-research--vX.Y.Z`) делает владелец. Тексты и код написаны вместе с Claude Code; за содержание отвечает владелец.

---

## English

Public repository, owner-only writes. Contributions via **fork + pull request**: branch from `main`, run `claude plugin validate . --strict` and `gitleaks git .`, keep README RU/EN in sync (same H2 set, no Mermaid), one topic per PR, no keys or personal paths.
`scripts/` and `shared/` are vendored from the `search` plugin — do not edit them here, run `tools/sync-shared.sh`.
Releases and tags (`science-research--vX.Y.Z`) are cut by the owner. Text and code are written together with Claude Code; the owner is accountable for the content.
