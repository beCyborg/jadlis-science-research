# Live Rate Limits — Snapshot 2026-04-20

## Semantic Scholar API
- **Unauthenticated:** 1000 RPS shared среди ВСЕХ неаутентифицированных пользователей (фактически непредсказуемо, throttling при высокой нагрузке)
- **Authenticated (API Key):** 1 RPS на пользователя (базовый лимит для всех ключей)
- **Повышенные лимиты:** возможны по запросу после ревью (review process)
- **API Key:** рекомендуется; некоторые эндпоинты требуют обязательно
- **Получение ключа:** через форму на semanticscholar.org/product/api (приходит на email)
- **Source:** https://www.semanticscholar.org/product/api

## PubMed E-utilities
- **With API Key:** 10 RPS (по умолчанию; более высокие лимиты доступны по запросу в NCBI)
- **Without API Key:** 3 RPS (превышение приводит к блокировке IP)
- **API Key:** рекомендуется; получить в Settings аккаунта NCBI
- **Дополнительно:** обязательна регистрация параметров `tool` и `email` при систематическом использовании
- **Ограничение по времени:** большие задачи — ночью или в выходные (EST)
- **Source:** https://www.ncbi.nlm.nih.gov/books/NBK25497/

## OpenAlex API
- **Auth required:** да, API key нужен для масштабного использования (с 2025 freemium-модель)
- **Rate limit (RPS):** 100 RPS максимум (при превышении — 429 Too Many Requests)
- **Основное ограничение:** cost-based дневной бюджет, а не чистый RPS
- **Бесплатный лимит:** $1/день (singleton — бесплатно, list+filter — $0.10/1000, search — $1/1000)
- **mailto policy:** заменена на api_key; старый `mailto:` параметр более не актуален
- **API Key:** бесплатный, получить за 30 сек на openalex.org/settings/api
- **Source:** https://developers.openalex.org/api-reference/authentication

## Crossref REST (с 1 декабря 2025)
- **Polite pool (с mailto в параметре запроса):**
  - Single DOI record: 10 RPS, concurrency 3
  - List/queries/filters: 3 RPS, concurrency 3
- **Public pool (без mailto):**
  - Single record: 5 RPS, concurrency 1
  - List/queries/filters: 1 RPS, concurrency 1
- **Как попасть в Polite pool:** добавить `mailto=your@email.com` в параметры запроса
- **Metadata Plus:** отдельный тариф, без этих ограничений
- **Source:** https://www.crossref.org/blog/announcing-changes-to-rest-api-rate-limits/

---

# Снимок 2026-09-21 — измерено прямыми запросами

Секции выше — снимок 2026-04-20, не перепроверялись. Ниже только то, что снято живым `curl` или с официальной страницы 21.09.2026.

## OpenAlex (заголовки ответа)
- С ключом: `x-ratelimit-limit-usd: 1`, 10 000 кредитов/день; search-запрос = 10 кредитов = $0.001.
- Без ключа: `x-ratelimit-limit-usd: 0.1`, 1 000 кредитов/день — 100 search-запросов, snowball на этом не живёт.
- Ключ принимается **обоими** способами: `&api_key=` и `Authorization: Bearer` — оба дают 200 и списывают с одного счётчика.
- Остаток дня виден в `x-ratelimit-remaining-usd` — читать его перед snowball, а не ждать 429.

## CORE API v3
- `GET https://api.core.ac.uk/v3/search/works/` — **со слэшем на конце**; без него 301, и `curl` без `-L` отдаёт вместо JSON страницу редиректа (HTML на ~776 байт) — для агента это выглядит как пустой ответ.
- `Authorization: Bearer ${CORE_API_KEY}`; заголовки `x-ratelimit-limit: 150`, `x-ratelimit-remaining`, `x-ratelimit-retry-after` (окно ~1 мин).
- Поле `fullText` приходит прямо в ответе поиска (80–180 тыс. символов на запись), плюс `downloadUrl` на PDF — полнотекст без отдельного запроса. DOI бывает `null`.
- Пробел между словами CORE трактует широко: `omega-3 triglycerides` → 18 335 861 попаданий, `omega-3 AND triglycerides` → 1 312. `AND` между концептами обязателен.
- Поиск по DOI работает: `q=doi:"10.3390/nu2030375"` → 2 записи, `downloadUrl` = прямой PDF. Слэш внутри DOI кодировать не обязательно.

## OpenCitations Index v2
- `GET https://api.opencitations.net/index/v2/citation-count/doi:{DOI}` — 200 за ~0.2 с, без ключа; заголовков лимита нет.
- Эндпоинты графа: `/citations/doi:{DOI}` (кто цитирует), `/references/doi:{DOI}` (кого цитирует). На DOI 10.1177/1758835919874651: 45 цитирующих и 37 ссылок.
- **Метаданных нет вообще** — ни title, ни года, ни счётчиков. Элемент: `{"oci","citing","cited","creation","timespan","journal_sc","author_sc"}`, где `citing`/`cited` — ОДНА строка с идентификаторами через пробел (`omid:br/… doi:… openalex:W… pmid:…`, pmid бывает несколько). Новые DOI нужно гидрировать пакетным Crossref/OpenAlex.

## Crossref — пакетный фильтр ретракций
- `GET /works?filter=update-type:retraction` — 75 616 записей; у элемента `update-to[].source` = `retraction-watch` | `publisher`, `update-to[].DOI` = DOI отозванной статьи.
- Обратный поиск по одной статье: `GET /works?filter=updates:{DOI},update-type:retraction&rows=1` → `total-results > 0` значит, что уведомление об отзыве указывает на этот DOI. Проверено на 10.1177/1758835919874651: `total-results: 1`, уведомление 10.1177/17588359211061903, `update-to[0].updated.date-parts: [[2021,12,15]]`, `source: retraction-watch`. Контроль на чистом DOI 10.3390/nu2030375 → `total-results: 0`. Это **list-запрос**: polite pool даёт по нему 3 RPS, а не 10.

## bioRxiv / medRxiv API
- `api.biorxiv.org/details/{server}/{from}/{to}/{cursor}` — **только выгрузка по диапазону дат**, поиска по ключевым словам нет. Канал препринтов = Europe PMC с `SRC:PPR`, не отдельный протокол.

## Europe PMC — тихий отказ поиска
- 21.09.2026 `rest/search` и `rest/searchPOST` на любой запрос отвечали `HTTP 200` с телом `{"version":"6.9"}` — без `hitCount` и `resultList`; `rest/article/MED/{pmid}` при этом работал. 16.09 поиск был исправен.
- Позже в тот же день тот же `rest/search` отдавал уже `HTTP 503` (nginx), а `rest/article/MED/31579114` продолжал возвращать `{"version":"6.9","hitCount":1,…}` — то есть отказ поиска за день сменил форму, а живой ответ во всех случаях узнаётся по одному признаку.
- HTTP-код не сигналит отказ: критерий недоступности — **отсутствие поля `hitCount`**, а не статус ответа. `hitCount: 0` — законный пустой результат, фоллбэк не запускает.
- К вечеру поиск поднялся, синтаксис подзапроса препринтов проверен: `query=melatonin AND SRC:PPR` + `sort=P_PDATE_D desc` → `HTTP 200`, `hitCount: 1049`. Фоллбэк «повторить без `sort`» в протоколе оставлен.

## Платные кандидаты (официальные страницы)
- **scite** (`scite.ai/pricing.md`, обновлено 25.08.2026): MCP без аккаунта — 10 запросов; Free — 25 MCP-кредитов/мес; Basic $20/мес ($144/год) — 250 кредитов, REST API нет; Pro $50/мес — 2 500 кредитов + API. Remote MCP `https://api.scite.ai/mcp`.
- **Consensus** (help.consensus.app, статья «The Consensus API», 10.09.2026): API и MCP делят один месячный пул. Free 30 вызовов, без доплат; Pro 500 (до 1 000 с доплатой); Deep 2 000 (до 10 000). Перерасход **$0.05/вызов**, выключен по умолчанию. 1 вызов = до 100 статей; лимит 1 запрос/с; ключ в заголовке `x-api-key`.

---

## Практические выводы для search-paper skill

| API | Безопасный RPS (без ключа) | Безопасный RPS (с ключом) | Рекомендация |
|-----|---------------------------|--------------------------|--------------|
| Semantic Scholar | ~0.5 (shared pool нестабилен) | 1 | Всегда использовать API key |
| PubMed E-utilities | 3 | 10 | API key + зарегистрировать tool/email |
| OpenAlex | N/A (нужен ключ) | 100 (но ограничен бюджетом $1/день) | API key обязателен |
| Crossref | 1 (list) / 5 (single) | 3 (list) / 10 (single) с mailto | Всегда добавлять mailto |

**Общая стратегия:** при параллельных запросах к нескольким API — Semantic Scholar является bottleneck (1 RPS). Планировать batching и bulk endpoints S2 для обхода.
