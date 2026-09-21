# ClinicalTrials.gov Protocol

**Source ID:** clinicaltrials
**Prefix:** `[ct*]`
**Role:** search (trial registry — pre-registration signal, ongoing/unpublished trials, outcome reporting)

---

## Назначение

ClinicalTrials.gov — реестр клинических испытаний. Ценность для научного обзора:
- **Pre-registration signal** — статья из publication, у которой есть NCT-запись, получает quality-сигнал «pre-registered» (снижает RoB).
- **Publication bias** — завершённые испытания без публикации = signal недо-репортинга (negative results прячут).
- **Ongoing trials** — что в процессе (статья ещё не вышла, но направление активно).

НЕ peer-reviewed papers. Записи реестра — это `studyType: "clinical-trial-record"`.

---

## Primary: скрипт (начни отсюда)

```bash
python3 "{PLUGIN_ROOT}/scripts/source-fetch.py" clinicaltrials --query '{REFINED_QUERY_EN}' --limit {LIMIT} --out "{WORK_DIR}/_fetch_clinicaltrials.json"
```

Ключа у ClinicalTrials.gov нет, прелюд `secret.sh` не нужен.

Скрипт: `/api/v2/studies?query.term=…&pageSize={LIMIT}&countTotal=true&sort=LastUpdatePostDate:desc`
и нормализация записи реестра в схему PAPER: `nctId` → `externalId`, `enrollmentInfo.count` →
`sampleN`, conditions/interventions/primary outcome/status сворачиваются в короткую строку
`abstract`, ссылка с `type=RESULT` → `pmid`.

В stdout — одна строка сводки, в `--out` — JSON:
`{source, apiStatus, total (totalCount), passes[], truncated, remaining, note, papers[]}`;
в `papers[]` — `title, externalId` (NCT), `pmid` (если результаты опубликованы), `year`
(**дата первичного завершения**; у набирающего испытания она в будущем — год старта лежит рядом
в `startYear`), `pubTypes[]` (studyType + фазы), `status`, `phase`, `sampleN`, `resultsPosted`,
`abstract`, `pass`. `doi`, `citations`, `influentialCitations`, `fwci` — `null`: у записи реестра
их нет, и выдумывать их нельзя.

`studyType` в дампе — `clinical-trial-record` (см. маппинг ниже), `qualitySignals` —
`pre-registered` + `results-posted` / `no-results-posted` (флаг publication bias) + фаза.

**Правило:** `exit 2` / `apiStatus=unavailable` → ручной путь ниже и его обработка ошибок
(Brave-фоллбэка нет — пишем `## ClinicalTrials UNAVAILABLE`); иначе ручные `curl` НЕ нужны.

**Бюджет ходов: 5–8 на источник** — запустить скрипт → Read JSON → оценить релевантность и
отранжировать до TOP-{LIMIT} → Write дамп → вернуть ответ по схеме. Если первый проход явно мимо
темы или почти пуст, можно запустить скрипт ещё раз с уточнённой строкой запроса, но **не более
3 запусков скрипта суммарно**.

---

## Primary: REST API v2 (без ключа)

> Ручной путь — референс и фоллбэк. Нужен, только если скрипт вернул `exit 2`.
> Запрос одной записи (`/studies/{NCT_ID}`) скриптом не покрыт — он ниже.

**Base:** `https://clinicaltrials.gov/api/v2/studies`

### Search

```bash
curl -s "https://clinicaltrials.gov/api/v2/studies?query.term=${QUERY_URLENCODED}&pageSize=${LIMIT}&format=json&sort=LastUpdatePostDate:desc"
```

Полезные параметры:
- `query.term` — свободный текст (можно использовать строку из SEARCH_PLAN.queries.clinicaltrials).
- `query.cond` — condition (заболевание/состояние).
- `query.intr` — intervention (препарат/вмешательство).
- `filter.overallStatus` — `COMPLETED`, `RECRUITING`, `TERMINATED` (через запятую).
- `pageSize` — до 1000 (для обзора достаточно 20).
- `fields` — ограничить выдачу, напр. `NCTId,BriefTitle,OverallStatus,Phase,EnrollmentCount,StudyType,Condition,InterventionName,PrimaryOutcomeMeasure,ResultsFirstPostDate,ReferencePMID`.

### Response parsing

JSON: `studies[].protocolSection`:
```
identificationModule.nctId                 → NCT-номер (externalId)
identificationModule.briefTitle            → title
statusModule.overallStatus                 → COMPLETED/RECRUITING/...
statusModule.resultsFirstPostDateStruct    → есть ли результаты (publication bias signal)
designModule.studyType                     → INTERVENTIONAL/OBSERVATIONAL
designModule.phases[]                       → PHASE2/PHASE3
designModule.enrollmentInfo.count          → sampleN
conditionsModule.conditions[]
armsInterventionsModule.interventions[].name
outcomesModule.primaryOutcomes[].measure
```
Связанные публикации: `protocolSection.referencesModule.references[]` → `pmid`, `type` (RESULT → результаты опубликованы).

### Single study

```bash
curl -s "https://clinicaltrials.gov/api/v2/studies/${NCT_ID}?format=json"
```

### Rate limits

Жёстких лимитов нет; reasonable use. Последовательные вызовы, без агрессивного параллелизма.

---

## Маппинг в схему PAPER

| Поле PAPER | Источник |
|------------|----------|
| `externalId` | `nctId` (напр. `NCT01234567`) |
| `doi` | null (у записи реестра обычно нет DOI; если в references есть pmid опубликованного результата — укажи `pmid`) |
| `pmid` | `referencesModule.references[].pmid` где `type=RESULT` |
| `studyType` | `"clinical-trial-record"` |
| `sampleN` | `enrollmentInfo.count` |
| `year` | год `statusModule.startDateStruct` |
| `citations`/`influentialCitations`/`fwci` | null |
| `isOA` | false (запись реестра) |
| `qualitySignals` | `["pre-registered"]` + `"results-posted"` если есть результаты, + `"no-results-posted"` (publication-bias flag) если completed без результатов, + фаза |
| `contrib` | primary outcome + статус (1 предложение) |

---

## Error Handling (NO Brave fallback)

1. Retry 1x через 3 сек при сетевой ошибке/не-200.
2. Если повторный fail → записать `{WORK_DIR}/clinicaltrials.md` с `## ClinicalTrials UNAVAILABLE` и причиной.
3. Pipeline продолжит без этого источника (минимум 2 других).

---

## Output format

```markdown
# ClinicalTrials.gov — результаты по "{REFINED_QUERY_EN}"

## Ключевые находки
[3-5 тезисов: сколько completed/ongoing, есть ли крупные фазы 3, публиковались ли результаты]

## Записи
### [ct1] {BriefTitle}
**NCT:** NCT........
**Status:** COMPLETED / RECRUITING / TERMINATED
**Phase:** ...
**Enrollment (N):** ...
**Intervention:** ...
**Primary outcome:** ...
**Results posted:** yes/no (publication-bias signal)
**Linked PMID:** ... (если результаты опубликованы)

## Мета
- Найдено: N
- Completed без публикации результатов: M (publication-bias flag)
```
