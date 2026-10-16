> Independent review of the policies from run 1, committed in 916a877 (output/ at that commit). Written by a separate Claude session that read each call transcript and policy and classified every statement. The prompt changes it led to are described in the README.

# Fidelity review: drafted AI use policies vs. call transcripts

Scope: `output/<stem>/policy.json` checked against `calls/<stem>.md`, using the rules in `prompts/fill-policy.md` and the defaults in `template/policy-template.md`.

How statements were counted: each of owner, next_review, why and who_it_covers counts as one. Each tool line, the new_tools line, each allowed use, each needs-approval item (use plus approver), the protected_information line, each bullet in the remaining sections, and each open question also count as one. When a statement mixes a transcript fact with template boilerplate (for example "No protected information"), it gets the label of its main claim.

## Summary

| Policy | Statements | Supported | Default | Unsupported | Contradicts | Missed |
|---|---|---|---|---|---|---|
| Bright Futures After School | 31 | 23 | 6 | 1 | 1 | 4 |
| Cedar Valley Family Center | 35 | 28 | 6 | 1 | 0 | 3 |
| Eastside Community Health Clinic | 29 | 24 | 2 | 1 | 2 | 2 |
| Northgate Community Food Bank | 35 | 26 | 8 | 1 | 0 | 1 |
| **Total** | **130** | **101** | **22** | **4** | **3** | **10** |

Overall the policies are faithful. None of them invents a tool or a law. All four named people (Renee, Joy, Luis, Grace, Nadia, Dr. Okafor, Beth, Marcus, Ken) appear in their transcripts with the roles the policies give them. The real problems are (1) tools listed as approved when the call said they were not approved, (2) one open board decision handed to a single person, and (3) a few internal inconsistencies where a section contradicts the policy's own open questions or another section.

---

## Bright Futures After School

**CONTRADICTS (1)**
- needs_approval: `"Children using AI in our program" — approver "Renee"`.
  Transcript L58 (Renee): "Do we allow kids to use AI tools during program time, and do we follow each school's rule or make our own? I don't know yet. That one probably needs the board and the principals." The call left this open and assigned it to the board and principals. The policy makes Renee the approver and implies kids' AI use is allowed once she approves. It also conflicts with the policy's own first open question.

**UNSUPPORTED (1)**
- who_owns_this[1]: `"Renee shares it with staff and group leaders when they start. We review it yearly."` The call never said how staff learn the policy or that Renee would do onboarding. This gives a named person a duty she never took on. Rule 2 asks for general wording here, such as "your site director". This is a minor issue. The yearly review is a default.

**DEFAULT (6)**: next_review "In 12 months"; who_it_covers (contractors, board, any device); check[0] "You are responsible for anything you send"; check[2] "Have a fluent reader check translations". This last one is a reasonable cautious default, but note that L32 says nobody can currently check the Vietnamese, so as written the rule cannot be met yet. That gap is correctly raised in the open questions. Also decisions_about_people; if_something_goes_wrong[1] "never punished".

**SUPPORTED (23)**: owner Renee (L38 "Me, for now"); why (L52, L54); ChatGPT for activity ideas, newsletter and translation (L16); new_tools Renee + Joy + district (L38); all 4 allowed uses (L16, L52); student data needing Renee plus the district (L38); state grant reports (L34); the protected info list (L22, L24, L26; staff and volunteer details are a default add); all 3 off-limits items (L54, L30, L48); pickup-time check (L32); machine-translation label (L48); telling parents (L44); same-day site director to Renee (L40); Renee as owner and Joy for settings; all 4 open questions (L58, L32, L18).

**MISSED (4)**
1. Notes to parents about a child's behavior. Renee named these as high-harm "legal documents in a way" (L30), but the policy only covers incident reports. Behavior notes to parents need either approval or an off-limits line.
2. The district data-sharing agreement is not named, and neither is its core rule that "student records stay in the platform, and only staff who need them" (L22). Rule 1 asks for the organization's own contracts.
3. "Whatever's on their phone" (L16): phone and built-in AI apps used by group leaders are not addressed. Only ChatGPT is listed.
4. The state monitor asking for an AI policy (L54), a stated worry and a likely reader, does not appear in the why or the ownership section. This is minor.

---

## Cedar Valley Family Center

**UNSUPPORTED (1)**
- owner: `"Luis, operations manager"`, repeated in who_owns_this[0] `"Luis owns this policy."` The transcript names Luis as the approver of tools (L42 "Luis approves tools. He already does for software") and of incident reports (L44). Nobody names him as policy owner. The policy also asks in its open questions `"Is Luis the right policy owner?"`, so it states the owner as settled and questions it in the same document. Use "operations manager (to be confirmed)" or move the owner to the open questions. This is counted once.

**DEFAULT (6)**: next_review; who_it_covers; needs_approval `"AI help with county or grant reports" — "Your manager"`, where the harm is supported by L34 and the approver is a generic default; check[0] "A person reads all AI output"; if_something_goes_wrong[1] "not punished", which also answers the staff worry at L56; who_owns_this[2] "review it in 12 months".

**SUPPORTED (28)**: why (L56, L58); Copilot pilot uses (L16); ChatGPT teacher uses (L18). Approval of ChatGPT is inferred from current practice and the board's ChatGPT Team question, against L16 "Officially, nothing." This is acceptable under rule 7 but is a judgment call. Canva for comms (L20) is a weaker inference of the same kind. new_tools Luis, plus Grace for client data (L42); "what we check" is default wording. All 5 allowed uses (L16, L18). Email-reading plugin under Luis (L60). Client data needing Luis and Grace (L42). The protected info list (L26, L28, L30). Off-limits: no AI photos as families (L48) and public statements by people (L38). Report numbers check (L34). Emergency fund decisions (L34). Intake essay and placement (L36). Thank-you with no note (L48). Labeling materials (L50; extending labels to "AI-made images" is a small stretch from L48). Honesty with funders (L52). Luis and Grace same day, Grace decides on breach (L44). Board approves (L42). One hour of training (L64). All 4 open questions (L64, L58, L56; the 4th is self-generated).

**Internal tension (not a transcript conflict):** Copilot is approved for "thank-yous" with "No protected information", yet protected_information lists "donor names". A thank-you letter has a donor's name on it, so as written the main Copilot use is forbidden.

**MISSED (3)**
1. Luis already refused the ChatGPT browser plugin that reads email (L60 "I said no"). The policy moves it into needs-approval and drops the stated "no". It should be an off-limits item or at least say the answer so far is no.
2. Bloomerang's AI features that "we haven't turned on" (L20) are not named. The general new-features line covers them only implicitly.
3. Adult ed students' immigration status. L26 says "some are undocumented", but the student list in protected_information is only "names, scores, grades, attendance". Immigration status appears only under case files.

---

## Eastside Community Health Clinic

**CONTRADICTS (2)**
- tools[1]: `"OpenEvidence and UpToDate AI search" — "Clinical questions only; no patient information."`
- tools[2]: `"ChatGPT" — "General letters and handouts; no patient, donor or staff information, even names."`
  Transcript L16 (Beth, COO): "That's the only approved AI," referring to the scribe. The policy lists these two as approved tools. Its own open question 2 says `"Do we formally approve ChatGPT, OpenEvidence and UpToDate AI search? Beth called the scribe our only approved AI."` So it presents an open decision as settled, in a HIPAA covered entity. Rule 7 puts unapproved tools in needs-approval or open questions. The allowed uses that depend on these tools (clinical lookup; handouts and sliding fee letters) inherit the problem. They are counted as supported in substance (L18, L20, L44).

**UNSUPPORTED (1)**
- off_limits[1]: `"Don't use AI in secret. If you're unsure, ask your manager."` L52 reports that some staff use AI secretly, but nobody on the call set a rule. This is a new conduct rule, not a template default. It is low-risk, but it is invented.

**DEFAULT (2)**: who_it_covers (volunteers, contractors, board); if_something_goes_wrong[1] "not punished".

**SUPPORTED (24)**: owner "Not yet named; compliance committee reviews, board approves" (L36), an honest handling of a gap; next_review left to the board, with the 3-month pilot (L58); why (L50, L54, L28); scribe for 3 pilot providers with a BAA (L16); new_tools BAA, no exceptions (L36); 3 allowed uses (L18, L20, L44, L42); Nadia for PHI, Beth for other tools, Dr. Okafor for clinical uses (L36); the protected info list (L24); off-limits[0] covering ChatGPT and Google Translate (L32, L54); scribe review including the medication example (L28); clinician review of handouts (L44); decisions about care and sliding fee (L28, L30); scribe consent script (L42); chatbot disclosure (L44); Nadia and the breach clock (L38); ownership (L36); all 4 open questions (L58, L16, L32, L30, L46, L52).

**Internal tension:** needs_approval `"Any clinical use of AI" — Dr. Okafor` conflicts with allowed_uses[0], which lets staff look up clinical questions without asking. L36 says "Clinical uses also need Dr. Okafor", meaning new tools for clinical use.

**MISSED (2)**
1. "Problems go to Nadia" (L38) covers all problems. The policy routes only suspected PHI exposure to Nadia, so for other problems (a wrong handout, a bad translation, a billing error) nobody is named.
2. Microsoft 365 "with no Copilot" (L20) is not mentioned. Turning on Copilot or other built-in AI features is the most likely next exposure, and the policy does not name it.

---

## Northgate Community Food Bank

**UNSUPPORTED (1)**
- needs_approval: `"AI use with a corporate partner's logo or brand" — approver "Marcus"`. L42 establishes that a partner agreement has an AI clause about logo and brand. Nobody said who approves such uses: Marcus signs off on "SNAP or donor data" (L36) and Ken approves tools. The policy also says in its open questions `"What does the corporate partner's AI clause require?"`. Naming Marcus as approver adds a decision. "Your manager" or an open question would be faithful.

**DEFAULT (8)**: next_review; who_it_covers; needs_approval recall and allergen summaries with "Your manager" (harm from L30); check[0] "You own what you send"; decisions[0] "AI never decides who gets food..."; being_open[1] "we tell them honestly"; if_something_goes_wrong[1] "not punished"; who_owns_this[1] "Your manager shares it... every year".

**SUPPORTED (26)**: owner "To be confirmed by the board" (silent in the call, handled honestly); why (L50, L52, L42); Gemini in Gmail and Docs (L16, L56); Tasha's paid ChatGPT (L16); Claude for grant first drafts (L18); Ken approves tools (L36); 4 allowed uses (L16, L18, L50); SNAP and donor data needing Marcus (L36); the protected info list (L22, L24); 3 off-limits items (L52, L28, L42, L46); recall check (L30); report numbers from inventory (L32); certified SNAP staff (L28, L50); partner AI clauses (L42); manager and Ken same day (L38); executive committee approves (L36); all 4 open questions (L58, L16, L44, L42, L56).

**Internal tension:** needs_approval allows "Summarizing recall notices or allergen information" with a manager's approval. check[1] says to check details "against the original notice, never an AI summary". One section treats AI recall summaries as approvable and the other bans relying on them.

**MISSED (1)**
1. The state human services department agreement that covers SNAP applicant data (L22) is not named. Rule 1 asks for the organization's own contracts, and the policy names Salesforce but not this agreement.

---

## Patterns across all four

- **Unapproved tools in the tools list.** This happens clearly once (Eastside) and as a judgment call twice (Cedar's ChatGPT and Canva after "Officially, nothing"). The prompt's rule 7 lets the model list personal-account tools "if the call suggests it is allowed", and the model reads that too generously.
- **Sections that disagree with the policy's own open questions.** Bright Futures has Renee approving kids' AI use against its homework-hour question. Cedar names Luis as owner and asks whether Luis should be owner. Eastside lists tools as approved and asks whether to approve them. A mechanical check could catch this: no item in an open question should also appear as settled elsewhere.
- **Approvers filled in where the call named none.** Northgate's brand use goes to Marcus. Elsewhere the model correctly used "your manager".
- **Strong points.** No invented tools, laws or people. The protected-information lists are specific and complete. Red lines (abuse reporting, AI images of kids or hungry people, SNAP chatbot, public statements) are captured in every case.
