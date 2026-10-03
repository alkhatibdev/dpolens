"""What DPOLens tells an assistant, in one place.

The same guidance has to reach an assistant three ways: sent on connect by this
server, carried by the Claude Code plugin, and written in the Cursor rules file,
which is read without connecting to anything. They are three files because each
one is read differently, and the sentences below are what they have to agree on.
"""

from __future__ import annotations

TRIGGER = (
    "Search DPOLens before writing or changing code that collects, stores, logs, shares or "
    "deletes personal data, and before answering a question about what a policy or the law "
    "requires."
)

PERSONAL_DATA = (
    "Personal data includes names, email addresses, phone numbers, postal addresses, identity "
    "document numbers, payment details, location, device identifiers, IP addresses, and "
    "anything else that can be linked back to a person."
)

NO_MEMORY = (
    "Do not answer from memory. A remembered article number is not a citation, and the version "
    "in force here may not be the version you were trained on."
)

CITE = (
    "Quote the clause you relied on and give its key, document and version, so the person "
    "reading your code can check it."
)

NOT_LEGAL_ADVICE = (
    "DPOLens returns what the documents say. It does not decide whether something is lawful, "
    "and a question with real consequences belongs with the people responsible for it."
)

SENTENCES = (TRIGGER, PERSONAL_DATA, NO_MEMORY, CITE, NOT_LEGAL_ADVICE)
"""The guidance every surface carries. A test checks that each one does."""

EXAMPLES = (
    "how long can we keep a deleted user's account data",
    "do we need consent to log IP addresses for debugging",
    "what has to happen when somebody asks for a copy of their data",
)

LOGGED = (
    "Every call is recorded on the instance: who asked, which clauses came back, and the "
    "question with personal data taken out. Nothing is sent anywhere else."
)

INSTRUCTIONS = f"""
DPOLens answers questions about this organisation's privacy policies and the privacy law
that applies to it. It returns the clause itself, word for word, with the key, document
and version to cite it by.

{TRIGGER}

{PERSONAL_DATA}

{NO_MEMORY}

{CITE}

Questions that work well:

  {EXAMPLES[0]}
  {EXAMPLES[1]}
  {EXAMPLES[2]}

Start with search_policies. Use get_clause when a result points at another clause, or when
you need the whole of an article rather than the part that matched. list_documents and
get_document say what this instance can cite at all.

{NOT_LEGAL_ADVICE}

{LOGGED}
""".strip()

POLICY_CHECK = """
Review the change I am working on against this organisation's privacy policies and the law,
using DPOLens.

1. Look at what has changed. `git diff` if there is no clearer place to start.
2. List every place the change touches personal data: a new field or column, something
   written to a log, data sent to another service, a retention or deletion rule, a consent
   or lawful basis question, access control over personal data.
3. For each one, search DPOLens for what applies. Search the organisation's own policies as
   well as the law: a policy can be stricter than the law, and the stricter rule is the one
   to follow.
4. Report what you found, in this shape:
     - what the code does
     - what the clause requires, quoted
     - the key, document and version, so I can check it
     - whether the code meets it, and what to change if it does not
5. Say plainly which parts of the change you found nothing about. A gap in the policies is
   worth knowing and is not the same as approval.

If nothing in the change touches personal data, say so and stop. Do not invent a finding.
""".strip()

POLICY_TOUR = """
Show me what this DPOLens instance can do, in about two minutes.

1. Call list_documents and tell me what is loaded: each document, its version and the date
   that version took effect, and whether it is a law or this organisation's own policy.
2. Run one search against a law that is loaded, such as asking how long personal data may be
   kept. Quote the clause that comes back and give its key, document and version.
3. Run one search against this organisation's own policies, if any are loaded, and show the
   same thing. Say so plainly if none are loaded yet.
4. Take one key from a result and call get_clause on it, to show the clause in its context
   with the clauses it points at.
5. Finish with what you would check with DPOLens while writing code, in two or three lines.

Keep it short, and quote the documents rather than describing them.
""".strip()
