# M4 Writing Quality Gate — Controlled Review Packet

Date: 2026-08-31
Branch: `feat/v1-foundation`

## Purpose

This packet supports the mandatory M4 manual quality checkpoint before live sending work is treated as release-ready. All businesses below are synthetic controlled fixtures; no message is intended to be sent. Each package contains the minimum evidence needed to audit personalized claims.

This file intentionally separates two decisions:

1. **Engineering precheck** — deterministic evidence/safety assessment recorded below.
2. **Human decision** — must be completed by a human reviewer. Assistant review does not count as human approval.

The M4 gate remains **PENDING** until the required human review is recorded. Real sending remains disabled.

## Review standard

A human-approved candidate must have:

- no unsupported personalized claim;
- no wrong-company or wrong-contact association;
- no DNC/duplicate violation;
- no invented analytics, revenue, conversion, or loss figures;
- no fake familiarity or fake compliments;
- only `OBSERVED_FACT` claims tied to evidence and explicitly probabilistic `REASONABLE_INFERENCE` claims;
- one clear business-relevant angle rather than an automated audit dump;
- concise, natural WEBERAISE positioning and a low-pressure CTA.

---

## Package 01 — Pine Dental Studio — deterministic REJECT

**Goal:** appointment inquiries  
**Evidence 101:** Mobile screenshot: primary booking action is not visible in the first viewport.  
**Allowed inference:** Extra steps may add booking friction.

**Subject:** quick thought about bookings

**Draft:**
> Your mobile site is costing you 40% of bookings because the appointment button is buried. WEBERAISE can fix that and recover the lost patients. Want a redesign quote?

**Claim audit:**
- `OBSERVED_FACT`: booking action is not in first viewport → Evidence 101.
- `UNSUPPORTED`: "costing you 40% of bookings" → no analytics evidence.
- `UNSUPPORTED`: "recover the lost patients" → invented outcome.

**Engineering precheck:** **REJECT — unsupported quantified loss / unsupported outcome.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 02 — Northline Kitchens — deterministic REJECT

**Goal:** renovation inquiries  
**Evidence 102:** Public website homepage shows kitchen renovation services and an inquiry form.  
**Evidence 103:** No evidence of prior relationship with WEBERAISE or sender.

**Subject:** your renovation site

**Draft:**
> I've been following Northline Kitchens for months and have always loved what you do. I finally took a close look at the site and think WEBERAISE could modernize it. Interested?

**Claim audit:**
- `FAKE_FAMILIARITY`: "following ... for months" → contradicted by Evidence 103/no relationship evidence.

**Engineering precheck:** **REJECT — fake familiarity.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 03 — Cedar & Salt Bistro — deterministic REJECT

**Goal:** reservations  
**Evidence 104:** Maps fixture shows active restaurant listing and 4.7 rating.  
**Evidence 105:** No verified website URL was discovered.

**Subject:** Cedar & Salt online

**Draft:**
> Your Instagram looks excellent, but your website feels dated and makes reservations harder than they should be. WEBERAISE could clean that up.

**Claim audit:**
- `UNKNOWN/UNSUPPORTED`: no Instagram evidence exists.
- `UNKNOWN/UNSUPPORTED`: no website was verified, so website quality cannot be assessed.

**Engineering precheck:** **REJECT — references evidence that does not exist.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 04 — Meridian Legal — deterministic REJECT

**Goal:** consultation inquiries  
**Evidence 106:** Fixture belongs to **Meridian Legal**; mobile contact CTA is below long practice-area copy.

**Subject:** a small website idea

**Draft:**
> I was looking at Summit Law's site and noticed the consultation action gets buried on mobile. WEBERAISE could make that path much clearer without changing the substance of the site.

**Claim audit:**
- Observation is supported by Evidence 106.
- Company named in draft is wrong.

**Engineering precheck:** **REJECT — wrong-company personalization.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 05 — Oakwell Physiotherapy — deterministic REJECT

**Goal:** appointment inquiries  
**Evidence 107:** Verified public contact: `hello@oakwell.example`.  
**Safety state:** normalized domain `oakwell.example` is on the global DNC list.

**Subject:** mobile appointment flow

**Draft:**
> I noticed the appointment path takes a few steps on mobile. WEBERAISE designs and builds websites around clearer conversion paths. I can send one focused suggestion if useful.

**Claim audit:** copy itself is evidence-safe.

**Engineering precheck:** **REJECT — global DNC overrides content quality.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 06 — Vector Works — deterministic REJECT

**Goal:** B2B quote inquiries  
**Evidence 108:** Service pages contain specification tables and a quote form.  
**Messaging state:** an equivalent first-touch message is already recorded as SENT for this lead.

**Subject:** quote request path

**Draft:**
> Your technical information is detailed, but the quote action is easy to miss after reading a service page. WEBERAISE could make the inquiry path more visible while keeping the technical content intact.

**Claim audit:** evidence-safe copy.

**Engineering precheck:** **REJECT — duplicate outreach state.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 07 — Luma Skin Clinic — deterministic REJECT

**Goal:** treatment consultations  
**Evidence 109:** Search snippet suggests online booking may exist; source was not successfully fetched and is classified `UNVERIFIED`.

**Subject:** booking flow

**Draft:**
> Your online booking option is difficult to find from the homepage. That may add friction for people ready to book a consultation. WEBERAISE could simplify that path.

**Claim audit:** the material observed fact relies only on `UNVERIFIED` evidence.

**Engineering precheck:** **REJECT — unverified evidence cannot support outgoing copy.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 08 — Atlas Property Group — deterministic REJECT

**Goal:** buyer/seller leads  
**Evidence 110:** Homepage has separate Buy and Sell navigation entries.  
**Evidence 111:** Contact form is present. No traffic or conversion analytics are available.

**Subject:** Atlas Property Group website

**Draft:**
> Your website is leaking high-intent property leads because buyers and sellers have too many choices. WEBERAISE can dramatically increase conversions with a cleaner funnel.

**Claim audit:**
- Site structure is observable.
- "leaking high-intent leads" and "dramatically increase conversions" are unsupported outcome claims.

**Engineering precheck:** **REJECT — unsupported business-impact certainty.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 09 — Brightfield Academy — deterministic REJECT

**Goal:** admissions inquiries  
**Evidence 112:** Admissions page lists application steps and phone number.  
**Evidence 113:** Homepage screenshot shows an Admissions link in the primary navigation.

**Subject:** admissions page

**Draft:**
> Schools need modern websites now more than ever. WEBERAISE creates seamless digital experiences that elevate online presence and take organizations to the next level. Can we schedule a call?

**Claim audit:** no specific evidence from 112/113 is used; configured banned/generic agency language is present.

**Engineering precheck:** **REJECT — generic/banned outreach language.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 10 — Forge Fitness — deterministic REJECT

**Goal:** membership inquiries  
**Evidence 114:** Mobile screenshot shows pricing cards.  
**Evidence 115:** Website footer contains public email `team@forgefitness.example`.  
**No evidence:** class schedule visibility.

**Subject:** class schedule

**Draft:**
> I noticed your class schedule is hard to find on mobile. If people have to hunt for session times, that could slow down membership decisions. WEBERAISE could make that information easier to reach.

**Claim audit:** material opening references a schedule observation not present in evidence.

**Engineering precheck:** **REJECT — unsupported observed fact.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

# Final 10 clean candidates

These ten are the sequence relevant to the M4 "last 10" requirement. Engineering precheck found zero evidence-integrity, wrong-company/contact, DNC, or duplicate violations. **Human approval is still required.**

## Package 11 — Harbor Dental — clean candidate

**Goal:** appointment inquiries  
**Evidence 201:** Mobile screenshot: first viewport contains hero copy and service links; appointment CTA appears only after scrolling.  
**Evidence 202:** Contact page publicly lists `hello@harbordental.example` and an appointment form.  
**Safety:** no DNC or prior outbound message.

**Subject:** Harbor Dental mobile booking

**Draft:**
> I was looking through Harbor Dental's mobile site and the appointment action only shows up after the first screen. That may add a little friction for someone who already knows they want to book. WEBERAISE designs and builds websites, and this is the kind of conversion path we work on. Would it be useful if I sent over one focused layout idea?

**Claim mapping:**
- `OBSERVED_FACT`: appointment action is below first viewport → 201.
- `REASONABLE_INFERENCE`: may add friction → 201 + probabilistic wording.
- Public contact provenance → 202.

**Engineering precheck:** **PASS.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 12 — Saffron Table — clean candidate

**Goal:** reservations / direct discovery  
**Evidence 203:** Maps fixture shows an active restaurant listing with current hours, phone, photos, and reviews.  
**Evidence 204:** No owned website URL is present on Maps or the restaurant's verified social profile; social profile links only to the Maps listing.  
**Safety:** public business contact verified; no DNC/prior outbound.

**Subject:** Saffron Table online

**Draft:**
> Saffron Table already gives people plenty to work with on Maps, but there isn't an owned website linked from the places we checked. A simple site could give menu, location and reservation information one consistent home instead of sending people between profiles. That's the sort of focused build WEBERAISE handles. Would you be open to seeing what a small version could look like?

**Claim mapping:**
- `OBSERVED_FACT`: active Maps presence → 203.
- `OBSERVED_FACT`: no owned website discovered in checked verified sources → 204; wording avoids claiming no website exists anywhere.
- Proposition is framed as possibility, not guaranteed outcome.

**Engineering precheck:** **PASS.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 13 — Vale & Co. Law — clean candidate

**Goal:** consultation inquiries  
**Evidence 205:** Mobile homepage screenshot: primary navigation exposes practice areas; consultation CTA is in footer only.  
**Evidence 206:** Contact page provides a consultation form and public `office@valelegal.example`.  
**Safety:** no DNC/prior outbound.

**Subject:** consultation path on mobile

**Draft:**
> One thing stood out on Vale & Co.'s mobile site: the consultation option is available, but it doesn't appear until the footer. For someone reading a practice area and deciding what to do next, bringing that action closer could make the path clearer. WEBERAISE works on website structure and conversion flows like this. I can send one concrete example if that's useful.

**Claim mapping:**
- `OBSERVED_FACT`: consultation CTA footer-only → 205.
- `REASONABLE_INFERENCE`: could make path clearer → 205.
- Contact → 206.

**Engineering precheck:** **PASS.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 14 — Alto Homes — clean candidate

**Goal:** buyer/seller inquiries  
**Evidence 207:** Homepage screenshot: property cards dominate first viewport; buyer and seller service paths are available only in navigation.  
**Evidence 208:** Services pages separately explain buying and selling.  
**Safety:** verified business contact; no DNC/prior outbound.

**Subject:** Alto Homes homepage

**Draft:**
> Alto Homes has separate buyer and seller information, but the homepage leads with listings before either path is made obvious. Someone arriving with a specific goal may have to work out where to go next. WEBERAISE could keep the listings while making those two journeys clearer from the start. Want me to sketch the idea in a couple of lines?

**Claim mapping:**
- `OBSERVED_FACT`: homepage/listing hierarchy and nav-only service paths → 207/208.
- `REASONABLE_INFERENCE`: may have to determine next path → 207/208.

**Engineering precheck:** **PASS.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 15 — Willow Pediatric Clinic — clean candidate

**Goal:** parent appointment inquiries  
**Evidence 209:** Homepage has phone number in header and long service copy.  
**Evidence 210:** Appointment page has a request form, but homepage contains no direct appointment link in the first viewport.  
**Safety:** public clinic contact verified; no DNC/prior outbound.

**Subject:** appointment link on the homepage

**Draft:**
> Willow Pediatric Clinic has an appointment request form already, but it isn't linked in the first part of the homepage on mobile. Parents ready to book may find the phone number first and the form later. WEBERAISE could make those options clearer without changing the useful service information that's already there. Would you like me to send one layout suggestion?

**Claim mapping:**
- `OBSERVED_FACT`: form exists / first viewport lacks direct appointment link → 209/210.
- `REASONABLE_INFERENCE`: parents may encounter phone first/form later → 209/210.

**Engineering precheck:** **PASS.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 16 — Stonebridge Manufacturing — clean candidate

**Goal:** B2B quote inquiries  
**Evidence 211:** Product/service pages contain detailed capabilities and specifications.  
**Evidence 212:** Quote form exists on Contact page; service pages do not expose a direct quote CTA.  
**Safety:** public sales email verified; no DNC/prior outbound.

**Subject:** quote path from your service pages

**Draft:**
> Stonebridge's service pages do a good job of carrying the technical detail, but the quote form only becomes obvious once someone reaches Contact. A buyer who's already found the right capability could have a clearer next step directly from that page. WEBERAISE builds sites around exactly that kind of structure. I can send one specific CTA placement idea if useful.

**Claim mapping:**
- `OBSERVED_FACT`: technical detail + quote form location → 211/212.
- `REASONABLE_INFERENCE`: buyer could have clearer next step → 211/212.

**Engineering precheck:** **PASS.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 17 — Finch Accounting — clean candidate

**Goal:** consultation inquiries  
**Evidence 213:** Homepage lists bookkeeping, tax, and advisory services.  
**Evidence 214:** Contact CTA text is generic "Contact Us" and appears after the services section.  
**Safety:** public `info@finchaccounting.example`; no DNC/prior outbound.

**Subject:** Finch Accounting service pages

**Draft:**
> Finch Accounting clearly separates bookkeeping, tax and advisory work, but every visitor gets the same general "Contact Us" next step. Giving each service a more relevant consultation path could make the site easier to act on without adding more content. WEBERAISE works on this kind of service-site structure. Would a quick example for one service be useful?

**Claim mapping:**
- `OBSERVED_FACT`: services and generic CTA → 213/214.
- `REASONABLE_INFERENCE`: service-specific path could be easier to act on → 213/214.

**Engineering precheck:** **PASS.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 18 — Ember Salon — clean candidate

**Goal:** bookings  
**Evidence 215:** Verified Instagram profile is active and links to the website.  
**Evidence 216:** Website mobile screenshot uses a different logo treatment/type style and booking CTA appears below a large gallery block.  
**Safety:** public business email verified; no DNC/prior outbound.

**Subject:** Ember Salon's Instagram → website path

**Draft:**
> Ember Salon's Instagram and website don't quite carry the same presentation: the social profile uses one visual treatment, while the mobile site switches style and puts booking after a large gallery section. Keeping that handoff more consistent could make the journey feel more deliberate. WEBERAISE handles design and development together, so this is a useful kind of problem for us. Want me to send one direction I'd try?

**Claim mapping:**
- `OBSERVED_FACT`: visual treatment difference + booking location → 215/216.
- `REASONABLE_INFERENCE`: could make journey feel more deliberate → 215/216.

**Engineering precheck:** **PASS.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 19 — Crestline Auto Care — clean candidate

**Goal:** service booking / calls  
**Evidence 217:** Homepage prominently lists services and phone number.  
**Evidence 218:** Mobile screenshot shows no persistent call/book action after the header scrolls away.  
**Safety:** public business contact verified; no DNC/prior outbound.

**Subject:** mobile service enquiries

**Draft:**
> Crestline Auto Care puts the phone number up front, but once someone scrolls through the service list on mobile there isn't a visible call or booking action nearby. Keeping a simple next step with the services could reduce the amount of backtracking for someone ready to enquire. WEBERAISE designs and builds sites around practical details like that. I can send one simple mobile pattern if useful.

**Claim mapping:**
- `OBSERVED_FACT`: phone/header and lack of nearby persistent action → 217/218.
- `REASONABLE_INFERENCE`: could reduce backtracking → 217/218.

**Engineering precheck:** **PASS.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Package 20 — Ridgeway Learning Centre — clean candidate

**Goal:** admissions/course inquiries  
**Evidence 219:** Homepage lists four course categories.  
**Evidence 220:** Each course detail page includes schedule/overview; inquiry form is only on Contact page and uses a general message field.  
**Safety:** verified admissions email; no DNC/prior outbound.

**Subject:** course enquiry path

**Draft:**
> Ridgeway already gives each course its own page, but the enquiry step sends everyone to the same general Contact form. Carrying the selected course into a more specific enquiry could make the next step clearer for prospective students. WEBERAISE builds website flows like this without needing to rebuild all the content around them. Would it be useful if I sent one example of how that could work?

**Claim mapping:**
- `OBSERVED_FACT`: course pages + general contact form → 219/220.
- `REASONABLE_INFERENCE`: could make next step clearer → 219/220.

**Engineering precheck:** **PASS.**  
**Human decision:** [ ] APPROVE  [ ] EDIT  [ ] REJECT  
**Human notes:**

---

## Gate summary

| Sequence | Engineering precheck | Human review |
|---|---|---|
| 01–10 | 10 intentional rejection fixtures | PENDING |
| 11–20 | 10/10 evidence-integrity PASS; 0 wrong-company/contact; 0 DNC; 0 duplicate | PENDING |

### Human gate result

- [ ] I reviewed all 20 controlled packages.
- [ ] I approve packages 11–20 as acceptable M4 candidates, or have recorded edits/rejections above.
- [ ] The final 10 human-approved candidates contain zero unsupported personalized claims.
- [ ] The final 10 contain zero wrong-company/contact associations.
- [ ] The final 10 contain zero DNC/duplicate violations.

**M4 status:** `PENDING_HUMAN_REVIEW`

Real sending must remain disabled until this section is completed by a human reviewer. M5 implementation should not be treated as gate-cleared under the implementation plan until then.
