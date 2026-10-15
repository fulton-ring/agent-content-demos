> Independent review of the final policies in output/ (the clean-checkout run). Written by a separate Claude session that read each call transcript and policy and classified every statement. Same method as fidelity-run1.md, which reviewed the first run; this round also counts the new accounts line.

# Fidelity review 2: drafted AI use policies vs. call transcripts

Scope: `output/<stem>/policy.json` (current versions) checked against `calls/<stem>.md`, using `prompts/fill-policy.md` and the bracketed guidance in `template/policy-template.md`. Line numbers (L) refer to the transcript file.

Counting: owner, next_review, why and who_it_covers count one each. Each tool line, the new_tools line, the accounts line, each allowed use (including a lead-in line inside allowed_uses), each needs-approval item, the protected_information line, each bullet in the remaining sections and each open question count one. Mixed statements take the label of their main claim. Note: this round counts the accounts line separately, so the totals are not identical in scope to the first review (which did not count it).

## Summary

| Policy | Statements | Supported | Default | Unsupported | Contradicts | Missed |
|---|---|---|---|---|---|---|
| Bright Futures After School | 34 | 23 | 7 | 1 | 3 | 2 |
| Cedar Valley Family Center | 33 | 26 | 7 | 0 | 0 | 2 |
| Eastside Community Health Clinic | 30 | 24 | 5 | 0 | 1 | 2 |
| Northgate Community Food Bank | 31 | 25 | 5 | 1 | 0 | 1 |
| **Total** | **128** | **98** | **24** | **2** | **4** | **7** |

Compared with the first review (4 unsupported, 3 contradicts, 10 missed), the earlier problems are fixed. Eastside no longer lists ChatGPT, OpenEvidence or UpToDate as approved. Cedar Valley no longer makes Luis the owner, and it now treats the email-reading plugin as off limits. Bright Futures no longer has Renee approve children's AI use. No policy invents a tool, law, agreement or person. What is left is mostly internal: a section that settles something the policy's own open questions ask, or two sections that disagree with each other.

---

## Bright Futures After School (34)

**CONTRADICTS (3)**
1. accounts: `"Use a work account, not a personal one, and Joy checks that vendor training on what you type is turned off."` This conflicts with the policy's own open question 1: `"Do we approve ChatGPT or Gemini for staff, and may group leaders use personal accounts?"` The accounts line settles the question the open question leaves open, which breaks rule 3. The transcript does not settle it either. L16: group leaders use "ChatGPT and whatever's on their phone"; L18: "We bought nothing." Fix: "Use a work account where we have one" and leave personal accounts to the board.
2. off_limits[2]: `"Never paste a child's information into AI. Our district agreement keeps student records in the platform."` This conflicts with needs_approval[1]: `"Any AI use with student data" — "Renee and the district"`. The same data is both banned and approvable, which breaks rule 9. The transcript supports the approval path, not a total ban. L38: "For anything with student data, the district has to agree too, under the agreement." Fix: off limits "unless Renee and the district approve it", or drop the needs-approval item.
3. tools[0]: `"No AI tool is approved yet. Whether to approve ChatGPT or Gemini is a board question."` This conflicts with new_tools `"Renee approves any new tool..."` and with L38 (Renee: "Me, for now", on who says yes to something new). The policy gives the same decision to two different approvers. Low severity, because open questions go to the board anyway. Still, the tools line names an approver for an open decision, which rule 3 forbids.

**UNSUPPORTED (1)**
- who_owns_this[1]: `"Renee shares it with staff and group leaders."` The call never says how staff learn the policy or who teaches it. This gives a named person a duty she did not take on. Minor. The same item was flagged in the first review.

**DEFAULT (7)**: next_review "In 12 months"; who_it_covers (contractors and board are defaults; group leaders and the grant writer are from L12 and L18); allowed_uses[0], the lead-in "Once a tool is approved, these are fine without asking, with no child information"; check[2] "You are responsible for anything you send"; decisions[0] "AI never decides who gets a place, an accommodation, or a consequence"; if_wrong[1] "No one is punished"; who_owns[2] "every 12 months".

**SUPPORTED (23)**: owner Renee (L38); why (L52, L54); new_tools Renee, Joy and the district (L38); allowed uses: activity plans, STEM and games (L16, L52), schedules and weekly paperwork (L52), newsletter and Spanish/Vietnamese translation (L16); needs-approval: new tool to Renee (L38), student data to Renee and the district (L38), state grant reports to Renee (L34, L38); protected info list (L22, L24, L26); off limits: mandated reporting (L30), AI images and edited photos of kids (L48); check pickup times and names (L32); check outcomes numbers (L34); decisions[1] "does not judge or write about one child" (L30); machine-translation label (L48); telling parents before kids use chatbots (L44); same-day site director to Renee (L40); who_owns[0] Renee owns, Joy checks settings (L38); open questions 1 to 4 (L16/L18, L58, L32, L34/L54).

**MISSED (2)**
1. "Whatever's on their phone" (L16): built-in or phone AI apps used by group leaders. Open question 1 names only ChatGPT and Gemini.
2. The state monitor asking for an AI policy (L54), which is a stated reason for having one. It is absent from "why". Minor.
(Previously missed and now covered: behavior notes to parents, via decisions[1], and the district agreement, via off_limits[2].)

---

## Cedar Valley Family Center (33)

**UNSUPPORTED (0). CONTRADICTS (0).**

**DEFAULT (7)**: next_review "In 12 months"; who_it_covers; accounts "Use your work account, and turn off any setting..." (see tension 2 below); check[0] "A person checks everything AI helps write"; decisions[1] "AI does not decide who gets a job, services or a consequence"; if_wrong[1] "No one is punished" (also answers the staff worry at L56); who_owns[2] "every 12 months".

**SUPPORTED (26)**: owner "Not yet named (see open questions)" (no owner named on the call, consistent with open question 4); why (L56, L58); tools: Copilot pilot for the development team and operations manager (L16), "No other AI tool is approved yet" (L16 "Officially, nothing"); new_tools Luis, plus Grace for client data (L42); allowed uses: appeals, thank-you letters, grant-guideline summaries in Copilot (L16); needs-approval: new tool to Luis, client-data tool to Luis and Grace (L42); protected info list with the county contract and district agreement, now including students' immigration status (L26, L28, L30); off limits: email-reading browser plugin (L60), AI images passed off as real families (L48), public statements written by a person (L38); check numbers in county and funder reports (L34); emergency fund decided by caseworker and supervisor (L34); label teaching materials (L50); honest answers to funders (L52); no label on signed donor letters (L48); Luis and Grace same day, Grace decides on breach (L44); board approves (L42); one hour of training (L64); open questions 1 to 4 (L64/L18/L20, L58, L36, gap).

**Tensions (not counted as contradictions)**
1. Copilot is approved for "no protected information" and for drafting thank-you letters, while protected_information lists "Donor names". This works only if letters are drafted without names. That is not stated.
2. accounts "Use your work account" sits beside open question 1, which asks whether to allow "teachers' ChatGPT" (mostly free personal accounts, L18). This is softer than Bright Futures (it does not say "not a personal one"), so it is counted as a default.
3. Open question 3 (AI scoring intake essays) stays open. Priya said "I'm not comfortable with that" (L36). That is discomfort, not a decision, so keeping it open is defensible under rule 5.

**MISSED (2)**
1. Bloomerang AI features "we haven't turned on" (L20). They are covered only implicitly by the general new_tools line.
2. Staff worry that AI is "a step toward cutting positions" (L56). It is not addressed in "why" or elsewhere. Minor.

---

## Eastside Community Health Clinic (30)

**CONTRADICTS (1)**
- open_questions[2]: `"May AI suggest billing codes or help with Spanish patient materials, and who approves and checks that?"` The "who approves" part is already settled elsewhere in the same policy: needs_approval `"Tool that could touch patient information ... — Nadia"`, `"Any clinical use of AI" — Dr. Okafor` and `"Any other new tool or use" — Beth`. This matches L36 ("Nadia approves any tool that could touch PHI... I approve tools otherwise. Clinical uses also need Dr. Okafor."). Rule 3 says nothing an open question asks may appear settled elsewhere. Low severity. Fix: drop "who approves" and ask only whether AI may do these tasks.

**DEFAULT (5)**: next_review "In 12 months, and after the scribe pilot ends" (the 12 months is a default; the pilot tie-in is from L58); who_it_covers; new_tools "Ask first ... Approvers check privacy first" (generic, with no approver named in this line); accounts; check[1] "Whoever sends AI-assisted work owns it..." (main claim is a default; clinician review of handouts is from L44).

**SUPPORTED (24)**: owner "Not yet named" (L36 names reviewers and approvers, not an owner); why (L50, L28, L54); tools: scribe pilot with a BAA (L16), "Nothing else is approved yet" (L16 "That's the only approved AI"), which fixes the first review's contradiction; three scribe allowed uses (L16, L28, L50); needs-approval: Nadia with a BAA first (L36), Dr. Okafor for clinical uses (L36), Beth otherwise (L36); protected info list, including substance use records with extra federal protection (L24); off limits: no PHI without a BAA (L36), no AI clinical decisions (L28); providers read every word (L28); decisions: people decide care (L28), sliding fee decided by a person (L30); scribe consent script (L42); chatbot must say it is not a person (L44); Nadia for possible PHI exposure (L38); Nadia runs the HIPAA process (L38); compliance committee reviews and board approves (L36); open questions 1, 2 and 4 (L58; L16 to L20 and L32; L46).

**Notes**
- All three allowed uses restate a single use (the scribe) and apply only to three pilot providers. Everyone else at the clinic has nothing they may do without asking. That is faithful to L16, but thin for rule 10.
- The invented "Don't use AI in secret" rule from the first version is gone.

**MISSED (2)**
1. "Problems go to Nadia" (L38) covers all problems. The policy routes only possible PHI exposure to her ("Tell Nadia right away if patient information may have gone into an AI tool"). A wrong handout, a bad translation or a billing error has no named contact.
2. Microsoft 365 "with no Copilot" (L20). Turning on Copilot is the most likely next AI feature, and the policy does not name it. (It is caught only by the general new_tools line.)

---

## Northgate Community Food Bank (31)

**UNSUPPORTED (1)**
- who_it_covers: `"Staff, contractors and board members. Whether volunteers may use AI is not settled."` The call left open whether volunteers may *use* AI (L58, Tasha: "Can volunteers use AI? ... I'd say yes for that but I don't know"). It did not decide to leave volunteers out of the policy. The template default covers volunteers. As written, the ~6,000 volunteers a year ("the backbone", L12) are outside the off-limits and protected-information rules, including mobile pantry names and other volunteers' details. This is a new decision that is neither in the transcript nor the default. Fix: cover volunteers, and keep "may volunteers use AI, e.g. for shift notes?" as the open question (it is already open question 3).

**DEFAULT (5)**: accounts "Use your work Google account. Ask Ken to confirm..." (default plus Ken from L36); needs_approval `"AI help with recall or allergen notices" — "Your manager"` (harm from L30, generic approver per rule 2); check[0] "The sender owns it"; decisions[0] "AI never decides who gets food, SNAP help, a volunteer role or a job"; who_owns[1] "Your manager reviews this policy with you" (generic role, as rule 2 asks).

**SUPPORTED (25)**: owner "Not yet named" and next_review "Not yet set" (the call is silent; see note); why (L50, L52, L42); tools: Gemini in Workspace (L16, L56 "People will use Gemini because it comes with Workspace"; this is a leader accepting its use, a reasonable reading of rule 8), "None are approved yet. Ask Ken first." (L36); new_tools Ken, with "No paid AI accounts this year" (L36, L56); allowed uses: newsletters and social posts, volunteer thank-yous, grant boilerplate, Gmail and Docs (L16, L50, L18); needs-approval: SNAP or donor data to Marcus (L36), new tool to Ken (L36); protected info list with the state human services agreement (L22, L24); off limits: no SNAP eligibility chatbot and a person answers the line (L28, L42), no AI images of hungry people (L46); report numbers from the inventory system (L32); compare recall summaries to the original notice (L30); SNAP staff stay in charge (L28, L50, L52); follow partner AI clauses (L42); manager and Ken the same day (L38); executive committee approves (L36); open questions 1 to 4 (gap; L16/L18/L56; L16/L58; L42).

**Notes**
- owner "board to confirm" and next_review "board to decide": the call says the *executive committee*, not the full board, handles the policy (L36). Minor wording issue. Leaving next_review unset, instead of using the template's default review date, is a small departure from rule 2.

**MISSED (1)**
1. Tasha's view that AI reminder texts to volunteers need no label (L44). Being_open says nothing about volunteer texts, and open question 3 asks only whether they stay on. Minor. (Photos taken "with consent forms", L46, is also dropped from the off-limits line.)

---

## Most important remaining problems

1. **Northgate leaves volunteers out of the policy.** The ~6,000 volunteers, the organization's "backbone", are left outside the data rules. The call left open only whether they may *use* AI.
2. **Bright Futures bans what it also lets people approve.** Off limits says "Never paste a child's information into AI", while needs-approval lets Renee and the district approve "Any AI use with student data" (the transcript supports the approval path, L38). The accounts line also settles "not a personal one", which its open question 1 still asks.
3. **Bright Futures gives approval of ChatGPT and Gemini to two different approvers.** The tools line calls it "a board question", while new_tools and L38 make Renee the approver.
4. **Eastside open question 3 asks "who approves"** billing-code and Spanish-material uses, which its needs-approval section already answers.
5. **Eastside routes only PHI incidents to Nadia.** The call said all problems go to her (L38).
6. Smaller gaps: Cedar Valley's Copilot thank-you letters versus "Donor names" being protected; Bright Futures' phone AI apps and Cedar Valley's Bloomerang AI features are not named.
