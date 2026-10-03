---
description: Check the change you are working on against the policies and the law
argument-hint: "[a file or area to look at]"
---

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

$ARGUMENTS
