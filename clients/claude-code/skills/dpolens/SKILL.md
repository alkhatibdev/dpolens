---
name: dpolens
description: >-
  Search this organisation's privacy policies and the privacy law that applies to it, through
  DPOLens, and cite the clause. Use when writing or changing code that collects, stores, logs,
  shares or deletes personal data, when choosing a retention period, when adding a field or a
  column that holds personal data, when sending data to another service, and when asked what a
  policy or the law requires.
---

# DPOLens

Search DPOLens before writing or changing code that collects, stores, logs, shares or deletes
personal data, and before answering a question about what a policy or the law requires.

Personal data includes names, email addresses, phone numbers, postal addresses, identity
document numbers, payment details, location, device identifiers, IP addresses, and anything
else that can be linked back to a person.

Do not answer from memory. A remembered article number is not a citation, and the version in
force here may not be the version you were trained on.

Quote the clause you relied on and give its key, document and version, so the person reading
your code can check it.

## How to search

Call `search_policies` with the question in ordinary words, the way somebody would ask it.
What comes back is the clause itself, with a citation line, the document, the version and the
date that version took effect. Quote it rather than paraphrasing it.

`get_clause` reads one clause by its key, with the clauses around it, which is what you want
when a result points at another clause or when you need a whole article. `list_documents` and
`get_document` say what this instance can cite at all.

Questions that work well:

- how long can we keep a deleted user's account data
- do we need consent to log IP addresses for debugging
- what has to happen when somebody asks for a copy of their data

Search the organisation's own policies as well as the law. A policy can be stricter than the
law, and the stricter rule is the one the code has to meet. Say plainly when you found nothing
about part of a change: a gap in the policies is worth knowing and is not the same as
approval.

DPOLens returns what the documents say. It does not decide whether something is lawful, and a
question with real consequences belongs with the people responsible for it.

Every call is recorded on the instance: who asked, which clauses came back, and the question
with personal data taken out. Nothing is sent anywhere else.
