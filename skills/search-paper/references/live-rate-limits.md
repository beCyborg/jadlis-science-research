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

## Практические выводы для search-paper skill

| API | Безопасный RPS (без ключа) | Безопасный RPS (с ключом) | Рекомендация |
|-----|---------------------------|--------------------------|--------------|
| Semantic Scholar | ~0.5 (shared pool нестабилен) | 1 | Всегда использовать API key |
| PubMed E-utilities | 3 | 10 | API key + зарегистрировать tool/email |
| OpenAlex | N/A (нужен ключ) | 100 (но ограничен бюджетом $1/день) | API key обязателен |
| Crossref | 1 (list) / 5 (single) | 3 (list) / 10 (single) с mailto | Всегда добавлять mailto |

**Общая стратегия:** при параллельных запросах к нескольким API — Semantic Scholar является bottleneck (1 RPS). Планировать batching и bulk endpoints S2 для обхода.
