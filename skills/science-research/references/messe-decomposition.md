# MESSE Decomposition Reference

**Версия:** v2.0 (адаптация из search-paper v2.2.0)
**Дата:** 2026-04-20

---

## 1. Overview

MESSE — метод структурированной декомпозиции научного запроса на 5 компонентов: **M**ethod, **E**ntity, **S**cope, **S**pan, **E**vidence. Используется в Phase 2 SKILL.md для определения дисциплины запроса и маршрутизации агентов.

**Статус:** Advisory + metadata. Discipline определяется и сохраняется, но влияет только на:
- Включение/выключение arXiv агента (skip для biomedical без "preprint")
- Включение/выключение cochrane-guidelines агента (skip для cs/physics)
- S2 `fieldsOfStudy` фильтр
- Discipline weights в quality score (weighted_source_count_norm)

---

## 2. Компоненты MESSE

| Компонент | Описание | Примеры значений |
|-----------|----------|-----------------|
| **M**ethod | Тип исследования / методология | RCT, meta-analysis, review, cohort, case study, observational, computational, theoretical, experimental |
| **E**ntity | Ключевые сущности (объекты исследования) | drugs (metformin), organisms (E. coli), techniques (CRISPR), concepts (attention mechanism), materials (graphene) |
| **S**cope | Область / дисциплина | biomedical, cs, social_science, physics, general |
| **S**pan | Временной период / контекст | recent (last 5 years), historical, specific years (2020-2025), not specified |
| **E**vidence | Уровень доказательств | clinical (human trials), preclinical (animal/in vitro), theoretical, computational, empirical |

---

## 3. Discipline Determination

| Discipline | Индикаторы | Confidence |
|------------|-----------|------------|
| `biomedical` | Медицинские термины, лекарства, болезни, клинические испытания, анатомия, фармакология | HIGH если Entity = drug/disease/organ |
| `cs` | Алгоритмы, нейросети, трансформеры, ML/AI, NLP, компьютерное зрение | HIGH если Entity = algorithm/model/architecture |
| `social_science` | Психология, экономика, социология, образование, политология | HIGH если Method = survey/qualitative |
| `physics` | Квантовая механика, частицы, космология, термодинамика, конденсированное состояние | HIGH если Entity = particles/fields/materials |
| `general` | Неоднозначный, мультидисциплинарный, невозможно определить | DEFAULT при confidence < 70% |

---

## 4. Влияние discipline на Phase 3 агентов

| Discipline | arXiv | cochrane-guidelines | S2 fieldsOfStudy |
|------------|-------|---------------------|-------------------|
| biomedical | SKIP (если нет "preprint") | ACTIVE | Medicine, Biology |
| cs | ACTIVE | SKIP | Computer Science |
| physics | ACTIVE | SKIP | Physics |
| social_science | SKIP | SKIP | Psychology, Economics, Sociology |
| general | ACTIVE | ACTIVE | — (без фильтра) |

---

## 5. Discipline Weights (для weighted_source_count_norm)

| Discipline | pubmed | s2 | openalex | arxiv | europe-pmc | cochrane | web-experts |
|------------|--------|----|----------|-------|------------|----------|-------------|
| biomedical | 1.5 | 1.0 | 1.0 | 0.5 | 1.3 | 1.5 | 1.0 |
| cs | 0.5 | 1.2 | 1.0 | 1.5 | 0.5 | 0.0 | 0.8 |
| physics | 0.5 | 1.0 | 1.0 | 1.5 | 0.5 | 0.0 | 0.8 |
| social_science | 0.8 | 1.0 | 1.3 | 0.5 | 0.8 | 0.5 | 1.0 |
| general | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |

---

## 6. Примеры

### Биомедицинский
**Запрос:** "витамин D депрессия мета-анализ"
- M: meta-analysis | E: витамин D, депрессия | S: biomedical | S: recent | E: clinical
- **Discipline:** `biomedical` (HIGH)

### CS
**Запрос:** "quantum error correction surface code"
- M: theoretical/computational | E: quantum error correction, surface code | S: physics | S: recent | E: theoretical
- **Discipline:** `physics` (HIGH)

### Мультидисциплинарный
**Запрос:** "sleep deprivation cognitive performance"
- M: not specified | E: sleep deprivation, cognitive performance | S: ambiguous | S: recent | E: clinical/experimental
- **Discipline:** `general` (< 70% confidence)
