# Changelog — jadlis-science-research

Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).
История до 1.0.0 — плагин `jadlis-research` 1.0.0–1.3.0 в репо [jadlis-start](https://github.com/beCyborg/jadlis-start) (`plugins/jadlis-research/CHANGELOG.md` до split).

## [Unreleased]

## [2.3.1] — 2026-09-22

### Для человека

- Поведение не меняется: описания двух агентов синтеза выровнены с плагином `jadlis-research`, чтобы у обоих плагинов они совпадали слово в слово.

### For agents

- Changed: `agents/synth-opus.md` and `agents/synth-fable.md` copied byte-identical from `jadlis-research` 2.6.0 (tag `jadlis-research--v2.6.0`); only the `description:` lines differed from 2.3.0. Model and `effort:` unchanged (`synth-opus` xhigh, `synth-fable` high).

## [2.3.0] — 2026-09-22 — Синтез на Opus 5.5 xhigh / Synthesis on Opus 5.5 xhigh

### Для человека

- **Итоговый отчёт теперь по умолчанию пишет Opus 5.5 на уровне рассуждения xhigh, а не Fable 5.1.**
  По замерам Artificial Analysis он сильнее на задачах, похожих на наши: GDPval 1820 против 1617
  у Fable 5.1, реже отвечает наугад (0,66 против 0,69); на научном коде SciCode переход с high на
  xhigh даёт 60,4 → 65,0. Задача обходится дешевле и не расходует отдельный недельный лимит Fable.
- **Fable остаётся доступен:** `fableBridge: true` в аргументах возвращает синтез на Fable 5.1.
  Поиск по очень длинному контексту у Opus 5.5 ещё не измерен — если отчёт начнёт терять факты из
  собранных материалов, это первый выключатель.
- **Отчёт не пропадает из-за отказа одной модели.** Если синтез вернулся пустым, он один раз
  повторяется на модели другого семейства, в обе стороны: Opus → Fable, Fable → Opus. Раньше повтор
  был только с Fable на Opus. В свойствах отчёта `ai_model` — та модель, что реально его написала.
- **Критик отчёта думает глубже (xhigh), механические шаги — короче (medium):** слияние дублей,
  совместное цитирование и проверка DOI по Crossref долгих рассуждений не требуют.

### For agents

- Changed: `workflows/search-paper-core.js` — `FABLE_SYNTH = A.fableBridge === true` (was `!== false`); synthesis defaults to `jadlis-science-research:synth-opus`.
- Changed: synthesis retry is symmetric — gate `if (!synth)` (was `if (!synth && FABLE_SYNTH)`), one retry on the new `SYNTH_AGENT_RETRY` (the other family; label `synth→fable-retry` or `synth→opus-retry`); `AI_MODEL_RETRY` derives from the branch; `aiModelActual = (FABLE_SYNTH !== synthFellBack) ? fable : opus`. First-call labels unchanged: `synth` (Opus), `synth→fable` (Fable).
- Changed: per-call `effort` in `agent()` options (overrides the `researcher-opus` frontmatter `high`): adversarial critic `xhigh`; dedup, co-citation and enrich batches `medium`. Query builder, source searchers, citation chasers, fulltext readers and fix unchanged (`high` from frontmatter; fix is mechanical by its own prompt).
- Changed: `agents/synth-opus.md` `effort: high` → `xhigh`, description marks it as the default; `agents/synth-fable.md` description marks it as opt-in / retry. `skills/science-research/SKILL.md` — model paragraph, Phase C step 2a, summary line and `synthesis-failed` text follow the new default.
- Changed: `tests/sp_dryrun.js` finds the synthesis prompt by the `synth` label prefix instead of the literal `synth→fable` (it asserted the old Fable default), records `effort`/`agentType` per call and asserts the default synth agent and the effort map; `tests/sp_units.js` adds A10 — both branches with 0, 1 and 2 null synthesis answers (retry agent, `ai_model` in the retry prompt, `aiModelActual`, `synthesis-failed`).
- Migration: callers that relied on the implicit Fable default pass `fableBridge: true`. Reason: Artificial Analysis GDPval-AA Opus 5.5 xhigh 1820 vs Fable 5.1 high 1617, guessing rate 0.66 vs 0.69, SciCode high 60.4 → xhigh 65.0, lower cost per task, no Fable weekly cap. Long-context retrieval (MLCR) of Opus 5.5 is not yet measured — `fableBridge: true` is the rollback.

## [2.2.2] — 2026-09-22 — Переход на Opus 5.5 / Switch to Opus 5.5

### Для человека

- Поиск статей, снежный ком по цитированиям, обогащение, критик и запасной синтез теперь работают на Opus 5.5 вместо Opus 5; главным синтезом по-прежнему занимается Fable 5.1.
- В свойствах отчёта `ai_model` пишется `claude-opus-5-5`, если отчёт дописывал Opus.
- Плагин требует Claude Code ≥ 2.1.280: более старые версии не знают новую модель.

### For agents

- Changed: model `claude-opus-5` → `claude-opus-5-5` (Opus 5.5, 1M context native, no `[1m]` suffix) in `agents/researcher-opus.md`, `agents/synth-opus.md` (frontmatter `model:` + description), `skills/science-research/SKILL.md` (frontmatter `model:`), `workflows/search-paper-core.js` (`AI_MODEL`, `AI_MODEL_RETRY`, `aiModelActual`); prose naming the current model "Opus 5" → "Opus 5.5" in the same files. `effort:` values unchanged. `agents/researcher-opus.md` and `agents/synth-opus.md` copied byte-identical from `jadlis-research` 2.5.3.
- Migration: requires Claude Code ≥ 2.1.280 — older versions may reject the unknown model ID `claude-opus-5-5` in agent/skill frontmatter. `skills/science-research/examples/sample-report.md` and the dated observations in `references/gotchas.md` keep "Opus 5" as history.

## [2.2.1] — 2026-09-21

### Для человека

- Научный отчёт сразу получает короткий английский адрес для Obsidian Publish: в свойствах появляется `permalink`, и ссылка на опубликованную заметку больше не состоит из длинной закодированной кириллицы.

### For agents

- Changed: `skills/science-research/SKILL.md` Phase C — new step 2c adds `permalink: <slug>` (2–4 English words, ASCII, unique in the vault) to the draft frontmatter before the vault write.

## [2.2.0] — 2026-09-21

### Для человека

- **Вопрос из многих подтем больше не ищется одной строкой.** Раньше на весь запрос шёл один запрос
  на источник: в прогоне про никотиновые пакетики (286 статей) слова «кофеин», «L-теанин» и
  «модафинил» не встречались ни в одном запросе, а «сперма» и «сон» сидели по одному слову внутри
  длинного перечисления и наверх выдачи не выходили. Теперь вопрос сначала раскладывается на
  подвопросы, и каждый непокрытый получает собственный короткий запрос к PubMed, Europe PMC и
  OpenAlex (до шести на источник). Подвопрос, который не несёт ни один запрос, невозможен: если
  план его пропустил, запрос достраивается из терминов подтемы, и это пишется в лог.
- **Все запросы источника исполняются одним вызовом.** Стоимость сбора определяется числом ходов
  агента, поэтому семь запросов не превращаются в семь ходов: скрипт принимает список запросов,
  делит бюджет (не меньше восьми записей на запрос), дедуплицирует между ними и отдаёт один файл.
  За основным запросом остаётся ранжирование — доп. запросы только добавляют то, чего он не нашёл.
- **PubMed получил третий проход — наблюдательные исследования.** Два прохода отдавали две трети
  мест фильтру «РКИ / мета-анализ / обзор», и когорты бились за оставшуюся треть: работа про снюс
  и число сперматозоидов оказалась 19-й при 10 слотах, работа про снюс и диабет 2 типа — 79-й, хотя обе
  были в выдаче. Теперь места делятся как половина : четверть : четверть — доказательные,
  наблюдательные, общий.
- **При упоре в потолок корпус режется по рангу, а не по порядку ответа баз.** Каждой подтеме
  гарантируется минимум пять статей, остальное добирается по числу закрытых подтем, совпадению
  терминов и цитируемости с поправкой на свежесть. Раньше узкая подтема из пяти работ вымывалась
  целиком просто потому, что её база ответила позже.
- **Добор по общим ссылкам обзоров переехал в конец и ужался вдвое** (40 → 20 статей). На том же
  прогоне он занимал 40 мест потолка и не дал ни одной из 38 процитированных в отчёте работ, а
  добору по цитированиям комнаты не оставалось. Теперь он забирает только то, что осталось
  свободным после чейсинга.
- **Серая литература больше не исчезает молча.** DOI, которого нет в Crossref, проверяется в
  DataCite: нашёлся — это отчёт ведомства, диссертация или репозиторный препринт, и работа
  допускается в выводы с пометкой «отчёт ведомства, не журнал». Не нашёлся нигде — работа
  исключается и **попадает в счётчик**: раньше такой DOI не считался вообще, и лог писал
  «не верифицировано: 0», пока работа тихо не доезжала до отчёта.
- **Работа, которую критик назвал пропущенной, доходит до отчёта.** Раньше критик мог найти
  недостающее исследование и упомянуть его только в тексте разбора — правки читает другой агент, и
  работа терялась второй раз. Теперь все такие работы идут отдельным списком, и агент правок обязан
  вписать каждую. Плюс сверочный шаг: по подтемам, где в подборке ноль статей, критик делает до пяти
  веб-запросов, и найденный DOI принимается только после проверки в Crossref или DataCite.
- **Отчёт написан простым языком.** Видимая часть: уверенность словами («уверенность средняя —
  скорее всего так, но новые данные могут поправить»), ссылки сносками вместо меток вида
  `[em1·MODERATE]`, размер эффекта бытовым сравнением вместо «g 0,16–0,44», риск — «примерно вдвое
  чаще» вместо «OR 2,82 (95% CI …)». Доверительные интервалы, p, I² и коды статей остаются в
  свёрнутых таблицах внизу. Каждый пункт «Что делать» строится как «что происходит → почему → что
  это значит для тебя»; краткая сводка — ответ одной фразой и ровно три пункта.
- **Служебные метки `[AR-fix]` убраны из текста отчёта.** Что именно поправил агент правок, теперь
  видно в разборе критика — отдельной таблицей применённого, а не пометками посреди фразы.
- **Видно, чего в данных нет.** По каждой подтеме в отчёт и в лог пишется, сколько статей нашлось.
  Ноль или одна — это дыра, и она видна сразу, а не при сверке с чужим отчётом.

### Изменено

- `PER_SOURCE_TOP` 30 → 40; `COCITE_MAX` 40 → 20; co-citation исполняется после snowball.
- `SEARCH_PLAN`: добавлены `subquestions[]`, `extraQueries[]`, `coverage[]` (все в `required`).
  `ENRICH_ITEM`: добавлен `greyLit`. `ADVERSARIAL`: добавлен `missingPapers[]`.
- `scripts/source-fetch.py`: `--query` повторяемый, добавлен `--queries-file`; в выводе появились
  `queries[]` и `queryIndex` у статьи; у PubMed три прохода вместо двух.
- `capStats`: добавлены `subquestions`, `coverage`, `greyLit`, `excludedSilently`. Во frontmatter
  отчёта — `coverage`. SKILL.md Phase C терпит старые рабочие папки без этих полей.
- Обновлены `references/plain-language.md` (новый файл — обязателен к чтению синтезатором и агентом
  правок), `examples/sample-report.md` (переписан под новый вид), `references/source-registry.md`
  (колонка лимита), `references/gotchas.md` (диагностика частичного `fix` — по таблице применённого).

### Исправлено

- Проверка потолка внутри цикла snowball стояла хвостом однострочного комментария на 272 символа и
  никогда не исполнялась — телеметрия `cap_hit_snowball` врала. Вынесена на свою строку и покрыта
  тестом.
- `isUnverifiedItem` требовал `crossrefVerified`, из-за чего нерезолвящиеся DOI не попадали ни в один
  счётчик.

### Тесты

- `tests/sp_units.js` + `tests/test_sp_units.py` — юнит-тесты чистых функций ядра (ранжированная
  обрезка на синтетическом корпусе из 300 статей, покрытие подтем, серая литература, телеметрия) и
  регрессия на потолок корпуса.
- `tests/sp_dryrun.js` — контракт промптов: один вызов скрипта на все запросы источника, ссылка на
  `plain-language.md`, отсутствие `[AR-fix]` в инструкции агенту правок.
- `tests/test_sp_plain_language.py` — образец отчёта проверяется по правилам простого языка.
- `tests/test_sp_recall_network.py` (маркер `network`, вне CI и вне прогона по умолчанию) — живая
  регрессия на четырёх потерянных работах прогона про никотин. Прогон 21.09.2026: все четыре PMID
  возвращаются (35642735, 28164394, 32547048, 24946991), 22 уникальных статьи на четыре запроса.

## [2.1.0] — 2026-09-21

### Для человека

- **Поиск по научным базам подешевел так же, как добор по цитированиям.** Запросы к шести API
  (PubMed, Europe PMC, OpenAlex, Semantic Scholar, CORE, ClinicalTrials), разбор ответов и приведение
  их к общему виду теперь делает скрипт `scripts/source-fetch.py`, а модель только оценивает
  релевантность и ранжирует. Замер 21.09.2026 показал, что стоимость сбора определяется числом ходов
  агента — каждый ход перечитывает 70–100 тысяч токенов контекста, — и агенты-источники тратили на
  возню с API от 14 до 52 ходов (Cochrane 52, Semantic Scholar 40, PubMed 28). В протоколах прописан
  бюджет: 5–8 ходов на источник вместо прежних 14–52. Ровно этот же ход в фазе добора по цитированиям
  дал падение с 24–34 ходов до 6–7. Живая проверка всех шести: 1–3 секунды на источник, 21–32 статьи
  с аннотациями.
- **Три источника без API (Cochrane и гайдлайны, эксперты в вебе, Epistemonikos) получили правило
  экономии вместо скрипта**: независимые поисковые вызовы идут одним сообщением в параллель,
  страницы выдачи поодиночке не открываются, потолок — 10 ходов.
- **Полный текст работы из CORE больше не может попасть в контекст агента.** Раньше это зависело от
  того, не забыл ли агент вырезать его командой; теперь поле просто не доходит до вывода (80–180 тысяч
  знаков на запись, десятки записей за запрос), остаётся только отметка «полный текст есть».
- **Europe PMC умеет отказывать молча.** 21.09.2026 он весь день отвечал «200 OK» с пустым телом —
  теперь повтор при таком ответе делает скрипт, и не только на основном запросе: на живой проверке
  один прогон из трёх попадал на такой пустой ответ и без повтора терял весь проход за свежими
  работами.
- **Europe PMC и OpenAlex перестали приносить знаменитое вместо нужного.** Оба источника искали по
  полному тексту и сортировали по цитируемости — наверх всплывали известные статьи, где термин упомянут
  мимоходом (в замере первой строкой шла работа про токсичность тяжёлых металлов по запросу про
  мелатонин и фазу сна). Теперь поиск идёт по заголовку и аннотации, плюс отдельный проход за свежими
  работами. Замер 21.09.2026 против списков литературы двух систематических обзоров (88 работ по теме),
  только параллельный поиск, без добора по цитированиям: было 2 попадания, стало 13; одни лишь
  исправленные запросы дают 9, один лишь подъём лимита — 4.
- **PubMed ищет по релевантности и в два прохода.** Без явного параметра PubMed отдавал самые свежие
  записи, а не самые подходящие (в замере — 0 попаданий в первых пятидесяти против 5). Теперь сортировка
  по релевантности, и отдельный проход только за РКИ, мета-анализами, систематическими обзорами и
  гайдлайнами: 13 попаданий против 5.
- **Общие ссылки обзоров — отдельный шаг добора.** У найденных обзоров и мета-анализов (до 20) берутся
  списки литературы, в корпус идут работы, на которые ссылаются хотя бы два из них. Отбор делает скрипт
  `scripts/cocite.py`, без модели: один запрос к OpenAlex на обзор. Замер на двух темах: случайная
  ссылка обзора оказывается нужной работой в 3–6% случаев, общая для двух обзоров — в 20–40%, для трёх —
  в 46–56%. Выключается аргументом `cocite: false`.
- **Добор по цитированиям подешевел.** Запросы к базам, разбор ответов и отсев уже найденного теперь
  делает скрипт `scripts/chase.py` (5 секунд на опорную статью: кто её цитирует, её список литературы,
  запасной путь через OpenCitations), а модель только отбирает подходящее по теме. На замере 21.09.2026
  шесть таких агентов были самой дорогой фазой сбора: по 24–34 хода ручной работы с API каждый.
- **Добранные статьи доходят до отчёта с содержанием.** Раньше работы, найденные по цитированиям,
  попадали к автору отчёта только в виде DOI с метаданными Crossref — без сути. Теперь каждый шаг добора
  пишет свой файл (`snowball_*.md`, `cocite.md`), и они входят в материалы для отчёта.
- **Корпус больше не упирается в потолок раньше времени.** Замер 21.09.2026 показал, что старый лимит
  (120 статей, по 20 с источника) съедался одним только параллельным поиском — добору по спискам
  цитирования не оставалось мест. Теперь берём по 30 статей с источника, потолок корпуса 240,
  полные тексты тянем у 10 верхних открытых работ вместо 6; пороги бюджета подняты под новый объём.
  Все три числа можно переопределить при запуске, чтобы сравнивать старую и новую полноту на одном коде.
- **Видно, что обрезалось.** В заметку записывается, чем закончился сбор (насыщение, потолок, бюджет),
  сколько статей нашлось сырыми и сколько осталось после склейки дублей. Раньше это жило только в чате
  и умирало вместе с сессией.
- **Новый источник — CORE.** Диссертации, отчёты, рабочие бумаги и репозиторные открытые копии: то,
  чего нет в журнальных базах. Это же спасательный круг для полного текста — если открытой копии
  не нашлось у Unpaywall, статья ищется в репозиториях по DOI.
- **Препринты в биомедицине.** Europe PMC теперь спрашивается вторым запросом про препринты
  (bioRxiv/medRxiv и прочие) — до 10 штук сверх основной выдачи, отдельной секцией и с честной
  пометкой «не прошёл рецензирование». У самих bioRxiv/medRxiv поиска по словам нет.
- **Europe PMC умеет отказывать молча.** 21.09.2026 он весь день отвечал «200 OK» с пустым телом —
  для агента это выглядело как «ничего не нашлось». Теперь живым ответ считается только при наличии
  поля `hitCount`, иначе — повтор и запасной путь. Ноль найденных статей отказом не считается.
- **Отозванные статьи ловятся четвёртым способом.** Добавлен обратный поиск: «есть ли уведомление об
  отзыве, указывающее на эту статью» — он находит отзыв даже тогда, когда в записи самой статьи о нём
  ни слова. Запрос дорогой по лимитам, поэтому идёт только по верхнему слою корпуса
  (мета-анализы, систематические обзоры, RCT и самые цитируемые).
- **Ссылка проверяется по трём полям, а не по одному.** К сверке заголовка добавились год публикации
  (с допуском в год — онлайн-первым и в номере) и фамилия первого автора. Совпал заголовок, но
  разъехались и год, и автор — статья помечается неверифицированной и в доказательную таблицу не идёт.
- **Добор по цитированиям пережил отказ двух API.** Если легли и OpenAlex, и Semantic Scholar,
  подключается третий, бесплатный и без ключа, — OpenCitations.
- **Дешёвый режим замера.** Можно остановить прогон сразу после сбора корпуса, без синтеза и критика,
  чтобы просто посмотреть на полноту выборки.

### For agents

- `scripts/source-fetch.py` — new. One subcommand per API source
  (`pubmed|europepmc|openalex|s2|core|clinicaltrials`), common CLI
  `--query --limit --year-from --preprints --out`, stdlib only, system python3 (3.9.6). It runs the
  passes each protocol prescribes (PubMed: `sort=relevance` + evidence-`[pt]` pass at ⅔ LIMIT +
  general at ⅓, then efetch XML → abstract/pubTypes/year/DOI, `PubmedBookArticle` included;
  Europe PMC: `CITED desc` + recency window + optional `SRC:PPR` on top of LIMIT;
  OpenAlex: `title_and_abstract.search` + `cited_by_count:desc` + relevance/last-3-years,
  abstract rebuilt from `abstract_inverted_index`; S2 relevance at 1 RPS with 429 backoff;
  CORE with the trailing slash, `fullText` never emitted (`hasFullText` boolean instead);
  ClinicalTrials v2 → NCT/status/phase/`sampleN`/summary string), merges and dedupes them, and writes
  `{source, apiStatus, total, passes[], truncated, remaining, note, papers[]}` with one normalized
  PAPER shape. Exit 0 for `ok`/`empty`, **exit 2 for `unavailable`** → the agent takes the protocol's
  documented fallback. Missing fields are `null`; key values are redacted out of every output.
  Europe PMC's retry lives in the source function, not in the transport: its failure mode is HTTP 200
  with a body lacking `hitCount`, which `request()` cannot see as an error.
- protocols: each of the six API protocols opens with «Primary: скрипт (начни отсюда)» — exact
  command, the JSON shape, the rule «exit 2 / `apiStatus=unavailable` → ручной путь ниже и его
  фоллбэк; иначе ручные curl НЕ нужны», and a 5–8 turn budget with a hard cap of 3 script runs.
  The manual REST sections stay as reference + fallback (`> Ручной путь…`), including the parts the
  script does not cover (S2 `/citations`, `/references`, `/batch`; CORE by-DOI; CT single study).
  `cochrane-guidelines`, `web-experts`, `epistemonikos` get a «Бюджет ходов» note instead: fire the
  protocol's independent MCP calls in ONE turn in parallel, target ≤10 turns.
- `workflows/search-paper-core.js` `sourcePrompt`: the ПРОТОКОЛ line now says to start from the
  «Primary: скрипт» section when the protocol has one and not to hand-write curl while the script
  works, and passes `WORK_DIR` for the script output.
- `tests/test_sp_source_fetch.py` — new: py39 parse, subcommand set, the script-first section present
  in all six protocols (and absent from the three MCP ones, which must carry «Бюджет ходов» instead),
  DOI normalization, inverted-index abstract + cap, PubMed efetch XML → record (journal article and
  book chapter), the Europe PMC `hitCount` criterion, CORE record dropping `fullText`, CT
  normalization, pass merging with preprints on top of LIMIT, and key redaction.
- `workflows/search-paper-core.js`:
  - caps are arg-overridable via `capArg(A.…)`: `PER_SOURCE_TOP` (new, default 30, substituted into
    protocol `{LIMIT}`), `PAPER_CAP` 120 → 240, `FULLTEXT_CAP` 6 → 10; budget floors
    `SNOWBALL_BUDGET_FLOOR` 80k → 120k, `FULLTEXT_BUDGET_FLOOR` 50k → 80k.
  - `capStats` hoisted out of the return object (`stoppedBy`, `capHitFanout`, `capHitSnowball`,
    `rawPapers`, `uniquePapers`, `paperCap`, `perSourceTop`); new `corpusOnly` arg returns
    `status: 'corpus-only'` with a `corpus[]` right after Snowball, skipping Enrich/Synthesize/Adversarial.
  - new source `core` in `ALL_SOURCES` (prefix `cr` — `co` is Cochrane), in `defaultSources()` base
    (ON for every discipline), and in `SEARCH_PLAN.queries` properties + `required[]`;
    `meta.phases` Fan-out now says 10 sources and stays a pure literal.
  - `HUB` gains a required nullable `doi`; `dedupPrompt` asks for it and the JS frontier-hub builder
    passes `normDoi(p.doi)`. `chasePrompt` is now a three-rung ladder
    OpenAlex → S2 → **OpenCitations Index v2** (`/index/v2/{citations,references}/doi:{DOI}`, keyless,
    used only when both failed AND the hub has a DOI), with a mandatory batch hydration of the new DOIs
    through Crossref/OpenAlex — OpenCitations returns identifiers only, no titles.
  - `enrichPrompt(dois, idx, topTier)`: 4th retraction signal
    `works?filter=updates:{DOI},update-type:retraction&rows=1` (`total-results > 0` → retracted),
    run **only** for the top tier computed in JS (`studyType ∈ {meta-analysis, systematic-review, rct}`
    or citations in the corpus' top third) — it is a list query, 3 RPS polite, not 10.
  - `ENRICH_ITEM` gains `yearMatch` / `authorMatch` (`boolean|null`); `titleMatch` semantics unchanged.
    New helper `isUnverifiedItem(e)` = `!titleMatch || (yearMatch === false && authorMatch === false)`,
    used by `unverifiedCount`, `synthPrompt`'s UNVERIFIED list and the fulltext OA candidate filter.
  - `fulltextPrompt`: after `pdf-fetch.sh` exit 2 and a second Unpaywall locus, a CORE-by-DOI rung
    (`q=doi:"{DOI}"`, `limit=1`, `downloadUrl`) before returning `extracted: false`.
  - `sourcePrompt` rule 1 rewritten around `{LIMIT}` = `PER_SOURCE_TOP`.
- `skills/science-research/protocols/core-protocol.md` — new. Trailing slash on `/v3/search/works/` is
  mandatory (301 + HTML redirect body otherwise; always `curl -sL`); `Authorization: Bearer`;
  `x-ratelimit-{limit,remaining,retry-after}` with back-off below 5; `fullText` (80–180k chars/record)
  MUST be stripped with `jq 'del(.results[].fullText)'` before reading; `doi` may be null;
  `downloadUrl` is a direct PDF; query syntax limited to keywords + `AND`/`OR`; no Brave fallback.
- `protocols/europe-pmc-protocol.md`: unavailability criterion is the **absence of `hitCount`**,
  regardless of HTTP status (`jq -e 'has("hitCount")'`); `hitCount: 0` is a legitimate empty result.
  Preprint sub-query `AND SRC:PPR`, `pageSize=10`, `sort=P_PDATE_D desc` — **not verified against the
  live API (search was down all of 21.09.2026)**, documented fallback is to repeat without `sort` and
  sort by `firstPublicationDate` locally. Preprints are +10 on top of LIMIT, separate dump section,
  `qualitySignals: preprint`, `studyType` from the normal enum.
- `protocols/openalex-protocol.md`: `mailto` is no longer a rate-limit lever (key sets
  `x-ratelimit-limit-usd` 1 vs 0.1) — `&api_key=` only, `OPENALEX_MAILTO` is a contact;
  read `x-ratelimit-remaining-usd` from the headers into the dump's Мета, and below 0.05 send the
  chaser straight to S2/OpenCitations.
- `protocols/{arxiv,europe-pmc,openalex,pubmed,s2}-protocol.md`: `TOP-20` → `TOP-LIMIT` in the size cap.
- `references/live-rate-limits.md`: new «Снимок 2026-09-21» (OpenAlex usd headers, CORE v3,
  OpenCitations v2, Crossref retraction filter, bioRxiv/medRxiv = date dump only, Europe PMC silent
  failure, scite/Consensus pricing) + measurements added while wiring the sources.
- `references/quality-framework.md`: retraction row is four signals now; new anti-hallucination
  section (title / year ±1 / first-author family, and what counts as unverified).
- `references/source-registry.md`: v5.2, CORE moved from «будущее расширение» into the active table,
  OpenCitations added to enrichment, preprint channel documented, «добавление источника» steps
  rewritten around the workflow and the test.
- `skills/science-research/SKILL.md`: step 2b writes `capStats` into the draft frontmatter
  (`stopped_by`, `papers_raw`, `papers_unique`, `paper_cap`, `cap_hit_*`); fan-out count 9 → 10.
- `tests/test_sp_sources_registry.py` — new: every `ALL_SOURCES` key has a protocol file, prefixes are
  unique, every source is in `defaultSources()` and in `SEARCH_PLAN.queries` (properties + `required`),
  `meta` holds no template literals or variables, caps are `capArg(A.…)`-overridable.
- `references/gotchas.md` fan-out count, README/README.en source list, retraction and reference-check rows.

## [2.0.1] — 2026-09-19

### Для человека

- Научный ресёрч снова сам сохраняет отчёт. Claude Code с версии 2.1.276 запрещает субагентам писать файлы с именем
  `report*.md`; черновик теперь называется `draft.md`.

### For agents

- SYNTH draft `${WORK_DIR}/report.md` → `${WORK_DIR}/draft.md` (CC 2.1.276+ blocks subagent Write to
  `^(REPORT|SUMMARY|FINDINGS|ANALYSIS).*\.md$`, errorCode 5); `reportPath` contract unchanged.
- `tests/test_sp_workdir_names.py` guards every `${WORK_DIR}/…` name in `workflows/*.js`; gotcha added.

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
