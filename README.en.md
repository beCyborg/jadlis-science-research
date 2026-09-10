English · [Русский](README.md)

# "Science has proven it" usually means a retelling of a retelling — and the paper may have been retracted a year ago

Your question goes straight to the scientific databases, every DOI it finds is checked against
Crossref for retraction and for a matching title, and the conclusion is graded with GRADE — by the
strength of the evidence, not the loudness of the headline.

```
claude plugin marketplace add https://github.com/beCyborg/jadlis-hub
claude plugin install jadlis-search@jadlis --config BRAVE_API_KEY=… --config FIRECRAWL_API_KEY=…
claude plugin install jadlis-science-research@jadlis
```

Order matters: `jadlis-science-research` pulls `jadlis-search` in as a dependency, but
auto-installing a dependency never asks for keys — so you install `jadlis-search` yourself, with
the keys, first.

![One question fans out to the scientific databases, retracted and unverified papers are set aside, and the conclusions carry a strength-of-evidence level](docs/img/hero-jadlis-science-research.webp)

In words: on the left a scientific question, on the right the corpus of papers, with retracted and
unverified ones moved to a separate pile and every surviving conclusion carrying its level of
evidence.

This is my workplace published as it is, not a product: whatever I stopped using, I removed.

## Before → after

| By hand | With an AI chat | With this plugin |
|---|---|---|
| **Where "proven" came from.** Nobody reaches the paper itself: what circulates is a blog retelling a press release. | Retells the same secondary texts; never goes to the full text, and does not always name the source. | Queries PubMed, Europe PMC, Semantic Scholar, OpenAlex, ClinicalTrials.gov, Epistemonikos and the Cochrane, NICE and UpToDate sites in one run, then follows citations forward and backward for more papers. |
| **Retracted papers.** A retracted study keeps being cited for years, and the retelling never shows it. | Answers from what was in its training data: a retraction that happened later is invisible to it. | Every DOI goes through Crossref before synthesis, checked against three retraction signals; retracted papers stay out of the conclusions and are listed separately. |
| **Whether the reference is real.** Nothing to check it with except opening each one and comparing by hand. | The link looks genuine and leads elsewhere: the DOI and the title do not match. | The title Crossref returns is compared with the claimed one; if they diverge, the paper is marked unverified and never enters the evidence table. |
| **How much a finding weighs.** A single preprint and a systematic review weigh the same once retold. | Gives the most confident answer available and hides how uneven the underlying studies are. | Assigns GRADE per outcome, not per study type: a meta-analysis of weak trials does not become strong evidence, and "not enough data" is an answer too. |
| **Who argues with the conclusion.** Nobody: the draft is read by whoever wrote it. | Agrees with itself and only sounds more certain when you push back. | A separate critic hunts for refutations, rechecks retraction on the key DOIs and looks at PubPeer. Key claims are cross-checked, and unchecked ones are marked. |

## How it works

![A question and three interview answers, databases queried in parallel, citation snowballing, retraction check, GRADE synthesis, a critic, and the report as a file](docs/img/how-jadlis-science-research.webp)

Going in: a scientific question and three answers — what decision you will make, which population is
in focus, how wide the coverage should be.
Inside: the databases are queried in parallel, the corpus grows through citations, every DOI passes
a Crossref retraction and title check, then GRADE synthesis and an independent critic with edits.
Coming out: a report as a file in your notes — the verdict for your decision, what to trust, what
the data does not cover and what was filtered out.

In words: question → interview → databases in parallel → citation snowballing → retraction and
title check → GRADE synthesis → critic and edits → report as a file.

A number reaches the report only with a verbatim quote from the paper to locate it: no quote, no
figure — the effect is then described in words.

## Install and first run

**a) Text to paste to an agent.** Copy the whole block into a Claude Code chat:

```
You are an installer. Install the jadlis-science-research plugin from the jadlis marketplace on this Mac.
Run exactly these commands, verbatim, without shortening anything:
1. claude plugin marketplace add https://github.com/beCyborg/jadlis-hub
2. claude plugin install jadlis-search@jadlis --config BRAVE_API_KEY=… --config FIRECRAWL_API_KEY=…
3. claude plugin install jadlis-science-research@jadlis
4. claude plugin list — show me the lines for jadlis-search and jadlis-science-research and their versions.
5. /jadlis-search:keys — set up the scientific source keys: PubMed, Semantic Scholar, OpenAlex
   and the contact emails for Crossref and Unpaywall.
Ask me for the Brave and Firecrawl values and substitute them for the ellipses yourself.
Do not change the order: jadlis-science-research pulls jadlis-search in as a dependency, but
auto-installing a dependency never asks for keys — so jadlis-search is installed separately and
with its keys.
Show me each command in full and wait for a "yes" before running it. If I say "no", do not run it,
tell me exactly what you skipped, and move on.
If a command returns an error, stop, show me the output, and do not go to the next one.
Never print key values: report only "present" or "missing".
```

**b) Commands by hand.**

```
claude plugin marketplace add https://github.com/beCyborg/jadlis-hub
claude plugin install jadlis-search@jadlis --config BRAVE_API_KEY=… --config FIRECRAWL_API_KEY=…
claude plugin install jadlis-science-research@jadlis
claude plugin list
```

The first command installs nothing — it adds the marketplace. Only the second and third install
anything, and it all comes off in one line:
`claude plugin uninstall jadlis-science-research@jadlis --keep-data`.

**c) The short command.** Open Claude Code in the folder you work in and type:

```
/science-research <your scientific question>
```

The plugin asks three questions — what decision you will make, which population, how wide the
coverage — and the search query is built from your answers, so they cannot be skipped. The fourth
question asks whether to read your health notes: say no and the notes folder is never opened.

If it is not found, check the name with `claude plugin list`.

## Limits, cost, updates

**What it does not do.** It does not replace your doctor and does not diagnose: the report is a
review of the literature, and treatment decisions are not made here. It does not read the full text
of every paper it finds — full text is pulled only for the top open-access ones, the rest is worked
from abstracts, and the report says so. It does not promise completeness: the corpus runs into its
own ceiling and into the run's budget, and if part of what was found did not make it in, the report
states that in a line. The retraction check goes through Crossref — a retraction that never reached
Crossref stays invisible. And it does not decide for you: the note comes out flagged as not
reviewed by a human, and the review is yours.

**What you need.** The `jadlis-search` plugin with Brave and Firecrawl keys — installed first; Cochrane,
the guidelines and Epistemonikos run on them. On top of that you need the scientific source keys —
PubMed, Semantic Scholar, OpenAlex and contact emails for Crossref and Unpaywall: you enter them
once with `/jadlis-search:keys`, and the values go into the macOS Keychain. Without them some databases
drop to anonymous limits and answer intermittently. I do not retell other people's pricing: those
bills are theirs. The notes folder is set at install time (`VAULT_PATH`, `~/Jadlis` by default) —
the report lands in `Знания/Ресерчи`. With Obsidian closed, dedup and link insertion are skipped
and the file is still written.

Keys live in the macOS Keychain; on Linux the same `security`-based helper does not exist, so
Linux is untested.

**How tokens get spent.** A heavy run — dozens of subagents out of your own quota: the databases,
the citation chase, DOI checks in batches, synthesis, the critic and the edits. Several runs back
to back do not fit in one window, so plan a scientific review as its own task for a session, not as
a quick question on the side. What it costs in money I have not measured and will not name a figure.

**Verified where I work:** my Mac, my subscription, my keys. Verified on macOS only.

**Terms of use.** There is no licence: all rights reserved by the author. You may read it and use
it personally. Commercial use, republishing and inclusion in your own products — by arrangement
with me.

**Updating.** Auto-update is off on your side for a third-party marketplace: until you run the
first command, you keep the version you installed.

```
claude plugin marketplace update jadlis
claude plugin update jadlis-science-research@jadlis
claude plugin list
```

Reinstall, if something ended up broken:

```
claude plugin uninstall jadlis-science-research@jadlis --keep-data && claude plugin install jadlis-science-research@jadlis
```
