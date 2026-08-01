# Quality Framework — Scientific Evidence Assessment

**Версия:** v1.0
**Дата:** 2026-04-20
**Статус:** AI-drafted, requires enrichment from `/full-research` Phase 0 reports

---

## 1. GRADE Per-Outcome Assessment

GRADE (Grading of Recommendations, Assessment, Development and Evaluation) оценивает качество **per outcome**, НЕ per study type. Мета-анализ плохих RCT ≠ высокое качество.

### Starting Quality

| Study Design | Starting Level |
|-------------|---------------|
| RCT | HIGH |
| Observational (cohort, case-control, cross-sectional) | LOW |

### 5 Downgrade Factors (-1 или -2 каждый)

| Factor | Что проверять | Серьёзный (-1) | Очень серьёзный (-2) |
|--------|--------------|----------------|----------------------|
| **Risk of Bias** | RoB 2.0 (RCT) / NOS (observational) | ≥2 домена "some concerns" | ≥1 домен "high risk" |
| **Inconsistency** | I² heterogeneity, direction of effects | I² 50-75%, разные magnitude | I² >75%, разные directions |
| **Indirectness** | PICO mismatch с целевым вопросом | Частичный PICO mismatch | Другая популяция + outcome |
| **Imprecision** | Confidence intervals, sample size | Wide CI, пересекает null | Very wide CI, N < 100 для RCT |
| **Publication Bias** | Funnel plot, Egger's test | Некоторая асимметрия | Egger's p < 0.10, strong asymmetry |

### 3 Upgrade Factors (только для observational, +1 каждый)

| Factor | Критерий |
|--------|---------|
| **Large effect** | RR > 2.0 или < 0.5, consistent across studies |
| **Dose-response** | Чёткий градиент доза-эффект |
| **Plausible confounders** | Все правдоподобные confounders уменьшили бы эффект |

### Final Quality Levels

| Level | Значение |
|-------|---------|
| **HIGH** | Очень уверены, что истинный эффект близок к оценке |
| **MODERATE** | Умеренно уверены; истинный эффект вероятно близок, но может отличаться |
| **LOW** | Уверенность ограничена; истинный эффект может существенно отличаться |
| **VERY LOW** | Очень мало уверенности; истинный эффект вероятно существенно отличается |

---

## 2. Cochrane Risk of Bias 2.0 (RoB 2.0) — для RCT

### 5 доменов

| Домен | Вопрос | Оценка |
|-------|--------|--------|
| D1: Randomization | Был ли процесс рандомизации адекватным? | Low / Some concerns / High |
| D2: Deviations | Были ли отклонения от intended interventions? | Low / Some concerns / High |
| D3: Missing data | Были ли пропущенные данные по outcome? | Low / Some concerns / High |
| D4: Measurement | Была ли оценка outcome адекватной? | Low / Some concerns / High |
| D5: Reporting | Были ли выборочно представлены результаты? | Low / Some concerns / High |

### Overall judgement

- **Low risk:** Все 5 доменов "Low"
- **Some concerns:** ≥1 домен "Some concerns", ни одного "High"
- **High risk:** ≥1 домен "High" ИЛИ множественные "Some concerns"

### ROBUST-RCT (упрощённая альтернатива для AI-автоматизации)

Для случаев, когда полная RoB 2.0 невозможна (нет fulltext), используем heuristics:
- Sample size (N ≥ 100 для RCT → lower risk)
- Multi-center (≥3 центров → lower risk)
- Pre-registered (ClinicalTrials.gov / PROSPERO → lower risk)
- Blinding reported (double-blind → lower risk)
- ITT analysis reported → lower risk

---

## 3. PICO Template (для Phase 1 Intent Clarification)

При клинических запросах структурировать через PICO:

| Component | Описание | Пример (витамин D + депрессия) |
|-----------|----------|-------------------------------|
| **P**opulation | Целевая популяция | Взрослые с диагностированной депрессией |
| **I**ntervention | Интервенция | Витамин D supplementation (≥1000 IU/day) |
| **C**omparison | Сравнение | Плацебо или отсутствие supplementation |
| **O**utcome | Исход | Изменение в депрессивной симптоматике (PHQ-9, BDI) |

### Когда использовать PICO

- Запрос содержит клинические/медицинские термины
- Есть явная пара "интервенция → эффект"
- Discipline = biomedical

### Когда НЕ использовать

- CS/physics запросы
- Обзорные запросы без конкретной интервенции ("что известно о X")

---

## 4. PRISMA 2020 Checklist Markers (27 items)

Для оценки найденных systematic reviews — "это hygienic SR или mess?"

### Ключевые маркеры (top-10 для AI-проверки)

| # | Item | Что искать в тексте |
|---|------|-------------------|
| 1 | Registration | PROSPERO ID или ClinicalTrials.gov |
| 2 | Eligibility criteria | Explicit inclusion/exclusion criteria |
| 3 | Information sources | ≥2 databases searched |
| 4 | Search strategy | Full search strategy reported |
| 5 | Selection process | ≥2 reviewers independently |
| 6 | Risk of bias assessment | Named tool (RoB 2.0, NOS, etc.) |
| 7 | Synthesis methods | Statistical methods for meta-analysis |
| 8 | Results of synthesis | Forest plot или numerical summary |
| 9 | Publication bias | Funnel plot или Egger's test |
| 10 | Certainty of evidence | GRADE или equivalent |

### Scoring heuristic

- 8-10 markers present → **HIGH quality SR**
- 5-7 markers → **MODERATE quality SR**
- < 5 markers → **LOW quality SR** (flag в Red flags)

---

## 5. AMSTAR 2 (16 items) — для Systematic Reviews

### 7 Critical Items (failure = LOW/CRITICALLY LOW)

| # | Critical Item |
|---|--------------|
| 2 | Protocol registered before start |
| 4 | Adequate literature search (≥2 databases + grey literature) |
| 7 | Justification for excluding studies |
| 9 | Risk of bias assessed with appropriate tool |
| 11 | Appropriate meta-analytic methods |
| 13 | RoB considered in interpreting results |
| 15 | Publication bias investigated |

### Overall Quality (AMSTAR 2 algorithm)

| Quality | Criteria |
|---------|---------|
| HIGH | ≤1 non-critical weakness |
| MODERATE | >1 non-critical weakness |
| LOW | 1 critical flaw ± non-critical weaknesses |
| CRITICALLY LOW | >1 critical flaw ± non-critical weaknesses |

---

## 6. Newcastle-Ottawa Scale (NOS) — для Cohort/Case-Control

### 3 домена, max 9 звёзд

| Домен | Max Stars | Cohort | Case-Control |
|-------|-----------|--------|-------------|
| Selection | 4 | Representativeness, selection of non-exposed, ascertainment of exposure, outcome not present at start | Adequate case definition, representativeness, selection of controls, definition of controls |
| Comparability | 2 | Controls for key factor + additional factor | Controls for key factor + additional factor |
| Outcome/Exposure | 3 | Assessment of outcome, follow-up length, adequacy of follow-up | Ascertainment of exposure, same method, non-response rate |

### Scoring heuristic

- 7-9 stars → **GOOD quality**
- 4-6 stars → **FAIR quality**
- 0-3 stars → **POOR quality**

---

## 7. Red Flags Checklist

### Обязательные проверки для каждой статьи в Evidence Table

| Red Flag | Источник данных | Severity |
|----------|---------------|----------|
| **Industry funding** | Crossref `funder` field | WARNING (не автоматический disqualify) |
| **Retracted** | Crossref `update-to.type == "retraction"` | CRITICAL — исключить из evidence |
| **Predatory journal** | Beall's list (beallslist.net) + Cabells | CRITICAL — исключить из evidence |
| **Small N** | Paper metadata | WARNING если N < 100 для RCT; контекстно для rare diseases |
| **Single-center** | Paper metadata / fulltext | WARNING |
| **Single-country** | Paper metadata | WARNING (geographic bias) |
| **No pre-registration** | ClinicalTrials.gov / PROSPERO / OSF отсутствует | WARNING |
| **p-value clustering at 0.05** | Fulltext (если доступен) | WARNING (p-hacking signal) |
| **Funnel plot asymmetry** | Meta-analysis fulltext, Egger's p < 0.10 | WARNING (publication bias) |

### Severity levels

- **CRITICAL** → Статья исключается из evidence base, отмечается в отчёте
- **WARNING** → Статья остаётся, но с пониженным evidence strength и пометкой

---

## 8. Study Type as Container (НЕ weight)

**Принцип:** Study type определяет какой assessment framework применять, НЕ автоматический rank.

| Study Type | Assessment Framework | Starting GRADE |
|-----------|---------------------|---------------|
| Meta-analysis | AMSTAR 2 (16 items) | Depends on underlying studies |
| Systematic Review | AMSTAR 2 + PRISMA 2020 | Depends on underlying studies |
| RCT | Cochrane RoB 2.0 (5 domains) | HIGH |
| Cohort | Newcastle-Ottawa Scale (9 stars) | LOW |
| Case-Control | Newcastle-Ottawa Scale (9 stars) | LOW |
| Cross-sectional | Modified NOS | LOW |
| Case Report | N/A (descriptive only) | VERY LOW |

Meta-analysis of biased RCTs ≠ HIGH quality. AMSTAR 2 critical flaw → entire SR quality drops to LOW regardless of study count.
