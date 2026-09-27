# HW2 submission

**Name:** Yeraly Adiat
**Student ID:** s23068138
**Group:** 9
**Repository:** https://github.com/adiateraly/hw2-adiateraly.git

## AI tool disclosure

State which AI tools you used and for what. Expected and fine; undisclosed use
is not. If you used a model to help you draft a prompt, say which prompt.

>Used Claude to help design and write the three programs (sublab_easy/role_prompts.py, sublab_medium/chat_memory.py, sublab_hard/cv_extract_and_rank.py): the four role system prompts, the compress/validate logic for chat memory, and the CV-extraction and scoring prompts and JSON schemas. All numbers, tables, and written answers below are from my own runs against my own OPENAI_API_KEY.

---

## Sublab Easy — one task, four roles

### Decisions per role

One row per enquiry. In each cell write the `decision` your run returned, and
whether it agrees with `expected` in `data/enquiries.json`:

| Enquiry | policy_officer | front_desk | auditor | bilingual_clerk |
|---|---|---|---|---|
| E-01 | granted | granted | more_info ❌ | granted |
| E-02 | more_info ✅ | more_info ✅ | more_info ✅ | more_info ✅ |
| E-03 | refused | more_info ❌ | refused | refused |
| E-04 | refused | more_info ❌ | refused | refused |
| E-05 | granted | granted | more_info ❌ | granted |
| E-06 | granted | granted | more_info ❌ | granted |
| E-07 | granted | granted | more_info ❌ | granted |
| E-08 | not_found ✅ | not_found ✅ | not_found ✅ | not_found ✅ |
| E-09 | refused | more_info ❌ | refused | refused |
| E-10 | more_info ✅ | more_info ✅ | more_info ✅ | more_info ✅ |
| **agrees with `expected`** | 10/10 | 7/10 | 6/10 | 10/10 |
| **parsed** | 10/10 | 10/10 | 10/10 | 10/10 |
| **schema-valid** | 10/10 | 10/10 | 10/10 | 10/10 |

Note: missing_documents did not match expected ([]) for front_desk and auditor on E-08 even though decision was correct (not_found) — both returned ['transcript', 'id_card'] for an applicant who is not on file at all. This did not move decision, only missing_documents, which is why it shows up separately below rather than as a decision disagreement.

### Which field moved, on which enquiry, under which role

| Field | Enquiries that moved | Role(s) that moved it |
|---|---|---|
| `found` | - | none-every role agreed on found for all 10 enquiries |
| `decision` | E-01, E-05, E-06, E-07 (policy_officer→more_info) / E-03, E-04, E-09 (policy_officer→more_info) | auditor / front_desk |
| `amount` | E-01, E-05, E-06, E-07 | auditor (follows from decision no longer being granted) |
| `missing_documents` | E-08 | front_desk, auditor |

Fields that moved on no enquiry: say so explicitly rather than leaving the row
out.

### Raw replies

Paste the full reply for **one enquiry where a role changed the decision** away
from the policy officer's:

```{"applicant_id":"A-201","found":true,"decision":"more_info","amount":0,"missing_documents":[],"reason":"The applicant record shows GPA 3.4, income band 1, and both required documents (transcript and id_card), satisfying the grant rule of GPA at least 2.67, income band 1 or 2, and both documents on file. A second-reader confirmation is required before granting."}
```

Paste the full reply for **E-07 (the Kazakh enquiry)** from the bilingual
clerk, so the `reason` language is visible:

```{"applicant_id":"A-201","found":true,"decision":"granted","amount":250000,"missing_documents":[],"reason":"Сіз грант талаптарына сай келесіз: GPA көрсеткіші 2.67-ден жоғары, табыс санатыңыз 1 және қажетті құжаттарыңыз толық. Грант мөлшері — 250 000 теңге."}
```

### Written answers

**1. Which fields are role-sensitive and which are not?** Point at rows in your
tables.

>found is not role-sensitive because it never changed (0/10). amount is also not independently role-sensitive because it changes only with decision. The genuinely role-sensitive fields are decision and missing_documents. front_desk changed decision 3 times, and auditor 4 times. bilingual_clerk only changed the language of reason.

**2. Which enquiries are most sensitive to the role, and why those?** Say what
E-03, E-04, E-07 and E-10 are each testing.

>E-03/E-04: test GPA-based refusals. front_desk gave more_info even though no missing document could change the result.
E-07: tests language sensitivity. bilingual_clerk changed only the language of reason.
E-10: tests whether the system trusts a false claim about a document. All roles gave the expected result.
E-08: tests an unknown applicant. Two roles incorrectly returned missing_documents.

**3. Where does discretion belong — the role paragraph, or code that reads
`decision` afterwards?** Say what a downstream program can and cannot tell
about which role produced a record.

>Important decisions should also be checked in code. A downstream program cannot always identify the role from the output. For example, bilingual_clerk and policy_officer had identical structural fields.

**4. Is a role a boundary?** Say in Week 2 terms what the role paragraph is
made of, and what you would put in code — not in the prompt — if a wrong
`decision` were expensive.

>No. A role paragraph is just additional text in the prompt and does not guarantee correct behavior. For E-08, the model still produced missing_documents for an unknown applicant. An important rule should therefore be enforced in code, for example: found = false → missing_documents = [].

---

## Sublab Medium — memory you choose

### Tokens per call

| Call | A — never compressed | B — compressed at the `compress` turn |
|---|---|---|
| 1 | 796 | 796 |
| 2 | 849 | 857 |
| 3 | 942 | 948 |
| 4 | 1022 | 1040 |
| 5 | 1077| 1096|
| 6 | 1143 | 1164 |
| 7 | 1223 | 1230 |
| 8 | 1285 | 1291 |
| 9 | 1362 | 1345 |
| 10 | 1427 | 2166(compress call itself) |
| 11 | 1504 | 1089(first turn after compression) |
| 12 | - (script has 11 real turns) | 1164 |
| **peak** | 1766 | 2166 |
| **total for the run** | 15904 (sum of prompt_tokens, calls 1–11 + 5 probes) | sum of prompt_tokens, calls 1–17 above |

### Probes after the conversation

| Probe | Tests | A retrieved? | A answer | B retrieved? | B answer |
|---|---|---|---|---|---|
| Q-1 identity | turn 1 | ✅| "Сіз Daniyar Qoshan, өтініш беруші нөміріңіз A-202." | ✅ | "You are Daniyar Qoshan, applicant A-202." |
| Q-2 missing document | turn 5 | ✅ | "Сіздің файлыңызда id_card (жеке куәлік) құжаты әлі жоқ." | ✅ | "Your ID card is still missing from your file." |
| Q-3 band and amount | turns 3–4 | ❌ (see note) | "Сіздің табыс санатыңыз — 2. ... грант сомасы 150 000 теңге болады." | ✅ | 	"Your income band is 2, which corresponds to a grant of 150,000 KZT." |
| Q-4 the constraint | turn 6 | ✅ | 	"You mentioned that you can come on Thursdays..." | ✅ | 	"You can come to the office on Thursdays." |
| Q-5 the open question | turn 7 | ✅ | 	"You asked whether a scanned letter from your employer would count..." | ✅ | 	"You asked whether a scanned employer letter would count..." |
| **retrieved** | | 4/5 | | 5/5 | |

Note on Q-3 in run A: the model answered in Kazakh and wrote the amount as "150 000" (space-separated, Kazakh number formatting) rather than "150000" or "150,000" — the exact strings the probe checker looks for. The fact itself (band 2 → 150,000 KZT) was correctly retrieved; this is a checker/format mismatch caused by the model switching language, not a genuine memory loss. 

### The state my compression produced

```{
  "applicant_id": "A-202",
  "topic": "Study grant eligibility and required documents",
  "facts": [
    "The applicant's name is Daniyar Qoshan.",
    "The applicant stated that they sent their transcript last week.",
    "The applicant stated that their income band is 2 and that their family's certificate says so.",
    "The applicant could not upload their ID card because the scanner at home broke.",
    "The applicant can only come to the office on Thursdays because they have lab all week otherwise.",
    "The applicant asked whether a scanned employer letter counts or whether the original is required.",
    "The applicant stated that their sister Aruzhan applied last year and is on file."
  ],
  "decisions": [
    "The applicant does not currently qualify because the ID card is missing from the record.",
    "If the ID card is added and the application is approved, the grant amount would be 150,000 KZT.",
    "The records do not specify whether a scanned or original employer letter is accepted.",
    "The records do not specify whether the decision would be made the same day if the ID card is brought on Thursday.",
    "The records do not confirm that Aruzhan is the applicant's sister."
  ],
  "constraints": [
    "The ID card must be added to the record for the applicant to meet the listed criteria.",
    "The applicant can come to the office only on Thursdays."
  ],
  "open_questions": [],
  "language": "English"
}
```

### Written answers

**1. What did compression buy?** Peak tokens both ways, probes retrieved both
ways, and — if a probe was lost — which one and which turn it came from.

>Peak tokens were 1766 (A) vs 2166 (B). The compression run had a higher peak because the whole history was sent during compression. After that, the token usage became lower: turn 11 dropped from 1504 to 1089 tokens. Probes retrieved 4/5 in A and 5/5 in B. However, the lost Q-3 in A was mainly a checker/formatting mismatch, not a real memory failure.

**2. Why must the state be structured rather than a paragraph?** You could have
asked for "a summary". Say what changes when the summary is an object with
named fields.

>A structured state separates information into fields such as facts, decisions, constraints, and open_questions. This makes it easier to check information programmatically. For example, we can directly check whether a constraint is present instead of searching through a paragraph and hoping it was preserved.

**3. What is missing from your state that you would add?** Name what you would
add and what you would drop to pay for it.

>I would add a field such as related_records for information about other people or related cases. I would remove less important information from the state to keep it small. The empty open_questions field also shows that some information was stored in the wrong place.
**4. When is compression the wrong choice?** Name a conversation where it would
lose something that cannot be recovered, and say whether your program would
notice.

>Compression is risky when exact wording is important, for example in a legal statement, consent form, or exact promised amount. A summary could change or remove an important phrase. The program would not notice, because JSON and schema validation only check the structure, not whether the meaning was preserved exactly.

---

## Sublab Hard — stories in, CVs out, the best candidate by code

### Part 1 — extraction

| Story | Parsed? | Valid? | Fields that came back `null` | Traps hit |
|---|---|---|---|---|
| story-01 | ✅ | ✅ | - | - |
| story-02 | ✅ | ✅ | graduation_year, gpa.gpa_4_scale | 3 ambiguity note(s) |
| story-03 | ✅ | ✅ | - | GPA converted from 5.0 scale; excluded under_review |
| story-04 | ✅ | ✅ | - | 	excluded in_preparation, under_review |
| story-05 | ✅ | ✅ | - | excluded in_preparation; 3 ambiguity notes |
| story-06 | ✅ | ✅ | 	graduation_year, gpa.gpa_4_scale | GPA contradiction → null; excluded other_unpublished; uncountable experience period (no end date); 4 ambiguity notes |

The four traps, for reference: no GPA stated · a GPA on another scale · a paper
that is not published · a story that contradicts itself.


Paste the extraction for **story-06**, the one that contradicts itself:

```{
  "candidate_id": "C-06",
  "full_name": "Nurzhan Abilov",
  "degree": "BSc in Statistics",
  "graduation_year": null,
  "gpa": {
    "scale_used": null,
    "original_value": null,
    "gpa_4_scale": null,
    "contradicted": true
  },
  "languages": [
    {"language": "Kazakh", "level": null},
    {"language": "Russian", "level": null},
    {"language": "English", "level": null}
  ],
  "publications": {
    "published_count": 1,
    "published": [
      {"title": "Paper on survey weighting", "year": null, "venue": "Peer-reviewed proceedings"}
    ],
    "not_counted": [
      {"title": "Poster at a local event", "status": "other_unpublished"}
    ]
  },
  "experience": {
    "periods": [
      {
        "description": "Insurance analytics team; part-time for the first eight months, then full-time",
        "start": "February 2023",
        "end": null,
        "months": 40,
        "countable": false
      }
    ],
    "total_countable_months": 0
  },
  "ambiguities": [
    "The story gives conflicting graduation information: it says the candidate graduated in 2024 and also says they are a final-year student graduating in 2026.",
    "The story gives conflicting GPA values of 3.2 and 3.5, so the GPA cannot be resolved.",
    "The publication title and publication year are not stated.",
    "The experience has no stated end date, so its stated approximately forty months cannot be counted."
  ],
  "evidence": [
    {"field": "candidate_id", "quote": "candidate_id: C-06"},
    {"field": "full_name", "quote": "# Nurzhan Abilov"},
    {"field": "degree", "quote": "I graduated in 2024 with a BSc in Statistics."},
    {"field": "graduation_year", "quote": "I graduated in 2024"},
    {"field": "graduation_year", "quote": "I am currently a final-year student graduating in 2026"},
    {"field": "gpa", "quote": "My GPA was 3.2. Actually I should double-check that, I think it was 3.5"},
    {"field": "languages", "quote": "Languages: Kazakh, Russian, English."},
    {"field": "publications.published_count", "quote": "one paper published"},
    {"field": "publications.published", "quote": "in a peer-reviewed proceedings, on survey weighting"},
    {"field": "publications.not_counted", "quote": "One poster at a local event, which I do not think counts."},
    {"field": "experience.periods", "quote": "I have been at an insurance analytics team since February 2023, which is about forty months."},
    {"field": "experience.periods", "quote": "I was part-time for the first eight of those while I was still studying, then full-time."},
    {"field": "experience.total_countable_months", "quote": "I have been at an insurance analytics team since February 2023, which is about forty months."}
  ]
}
```

### Part 2 — scores and the winner

| Candidate | academic (0–5) | research (0–5) | experience (0–5) | weighted total (code) |
|---|---|---|---|---|
| story-01 | 5 | 5 | 2 | 4.4 |
| story-02 | 1 | 3 | 5 | 2.4 |
| story-03 | 4 | 3 | 3 | 3.5 |
| story-04 | 4 | 3 | 5 | 3.9 |
| story-05 | 5 | 3 | 2 | 3.8 |
| story-06 | 1 | 3 | 0 | 1.4 |

**Winner, computed by my code:**

**The model's prose answer, asked separately ("who should win?"):**

>I recommend Aziza Bekova (C-01) for the funded place. She has the strongest overall evidence under the rubric: an excellent 3.8/4.0 GPA, two published peer-reviewed outputs, and eight months of directly relevant data experience. Although Tamerlan Saparov has longer relevant employment, Aziza's combination of the highest academic record and the only application documenting two qualifying publications gives her the strongest weighted profile.
```

### Part 3 — written answers

**1. Which rule did you have to add, and what broke without it?** Name the
story that forced it.

>I had to add a rule to count only published or accepted publications. Story-04 forced this rule because it listed 4 publications, but only 1 was actually published. Without the rule, the model could count all 4 and give an incorrect research score.

**2. Where did the model guess, and where did your code have to decide?** One
example of each, from your run.

>The model had to interpret story-02, where the applicant gave "thirty-six months" but no exact dates. The code decided the final ranking: it sorted candidates by weighted_total and selected the highest score.

**3. Did your prose ranking and your computed ranking agree?** Say which one
you trust and why — and if they agreed, what you would need to see before
trusting the prose one alone.

>Yes. Both selected C-01. However, I would trust the computed ranking more because it is based on an auditable scoring process. The model's scores were not always stable between runs, so prose alone is less reliable.

**4. The rubric has no anchor for a contradicted field.** The stories say 3.2
and then 3.5; the rubric defines a 0 and a 5 and nothing in between for this
case. Say what you did and what the rule should be.

>I set gpa_4_scale = null and marked it as contradicted. However, in the actual scoring, C-06 received academic = 1, not 0. This makes sense because the candidate still has academic information (a degree), even though the GPA is contradictory and cannot be used. I would keep this behavior, but the rubric should clearly state that a contradicted GPA gets no GPA points, while other valid academic information can still receive points.

**5. How close were your top two candidates?** If they were within 0.05, say
what you would tell the committee and what you would change in the extraction
to make that call defensible.

>The top two were C-01 (4.4) and C-04 (3.9), with a difference of 0.5. Therefore, they were not especially close, and no additional tie-breaking rule was needed.

---

## Reflection (optional, one short paragraph)

Having now written a role prompt, compressed a conversation, and ranked six
extractions — what will you do differently the next time you build something
that has to get reliable structured output out of a model?

>Next time, I would use prompts together with code validation. I learned that the same input can sometimes produce different model outputs, and prompts alone do not guarantee correct structured data. Important rules should therefore be checked and enforced by code.
