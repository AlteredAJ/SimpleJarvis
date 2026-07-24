---
name: ai-front-desk-business
description: Business model for AJ + Shourya's AI phone answering service for SMBs — architecture, pricing, Gastonia targets, hardware decision
---

# AI Front Desk — Business Model

**Partners:** AJ Japaukese + Shourya  
**Concept:** Install an AI that answers every call for a local small business. Smarter than preset-script bots. Knows the menu, allergens, wait times, and when to escalate to a human.  
**Edge:** Local, personal, show up in person. Cloud competitors can't do that.

---

## The Core Pitch (30 seconds)

> "Every time you're with a customer and can't pick up the phone — that's a caller who's about to call the next place. Our AI picks it up, answers their questions about the menu, quotes the wait, takes a reservation, and texts them a confirmation. It's not a script bot — it actually understands what they're asking. I can call the demo number right now and show you."

---

## Phase 0 — Build the Demo (Do This First)

**Create "Demo Diner"** — a fictional restaurant config that shows every capability:

| Demo moment | What it shows |
|---|---|
| "Hi, thanks for calling Demo Diner, how can I help?" | Custom greeting, sounds natural |
| "Do you have anything gluten-free?" | Menu intelligence + allergen awareness |
| "How long is the wait right now?" | Live wait time (you text it in before demo) |
| "Can I make a reservation for Saturday?" | Booking flow |
| "I want to speak to a manager about a complaint" | Escalation detection → "I'll flag this right away, can I get your name and number?" |

Bring this to every walk-in pitch. Call the number live. 90-second demo closes the conversation.

---

## Hardware: Mini PC Model

**Recommendation: Mini PC as the installed unit.**

Each client gets a small box (size of a large router) running the local AI model. You configure it, plug it into their router, and it handles calls.

**Why mini PC over pure cloud:**
- "Your AI runs on hardware we own and install" → strong privacy/data angle for restaurants (customer data, menu, etc.)
- No Claude API costs eating margin at scale
- Works even if internet drops for basic info (still needs internet for calls, but not for the brain)
- Good demo story: "Unlike Ring Central or that other bot service, your AI is a physical device we manage"

**Recommended hardware:**
| Device | Specs | Price | Best for |
|---|---|---|---|
| Beelink SER7 | Ryzen 7 7840HS, 32GB RAM | ~$400 | Llama 3.1 8B or Phi-4 14B (quantized), fast |
| Beelink Mini S12 Pro | Intel N100, 16GB RAM | ~$200 | Lighter models (Phi-3.5, Llama 3.2 3B), basic use |
| MINISFORUM UM890 Pro | Ryzen 9 8945HS, 32GB | ~$500 | Premium, can run 13B models comfortably |

**Hybrid stack (recommended):**
- **Brain:** Local LLM (Llama 3.1 8B or Phi-4) on mini PC — handles understanding, responses, logic
- **Voice in:** Deepgram STT (~$0.0043/min) — fast, accurate, cloud
- **Voice out:** ElevenLabs or PlayHT (~$0.15/1k chars) — natural TTS, cloud
- **Calls:** Twilio — routes the phone number, handles the call stream

This gives you: local intelligence (no API brain costs, private) + cloud-quality voice (sounds good).

**Cost per client per month (your cost):**
- Twilio number + usage: ~$20/mo
- Deepgram (moderate call volume): ~$10-15/mo
- ElevenLabs TTS: ~$10-15/mo
- **Total: ~$40-50/mo per client**

**Hardware cost strategy:**
- Option A: Include in setup fee ($500 setup = hardware + config) — you eat the cost, they lock in monthly
- Option B: Hardware lease ($50/mo for 12 months → your cost back + profit) — higher monthly, lower barrier
- Recommend Option A for first 3-5 clients to close deals fast

---

## Pricing: Flat Base + Add-On Packages

Shourya's instinct is right. Flat rate = predictable. Add-ons = upsell path.

### Base Package — $199/mo
- Mini PC installed and managed by us
- Answers calls 24/7 as your business (custom greeting, your business name)
- Business info: hours, location, directions, general FAQ
- Escalation: detects frustration/complaints → "Let me flag this for our team, can I get your name and number?"
- Owner gets SMS when a call escalates
- One Twilio number included

### Add-On Packages

| Package | Price | What it does |
|---|---|---|
| **Menu Intelligence** | +$49/mo | Full menu Q&A, ingredient descriptions, allergen flags per dish |
| **Bookings & Reservations** | +$49/mo | Takes reservations → Google Calendar / Square / OpenTable hook; SMS confirmation to caller |
| **Wait Time & Status** | +$49/mo | Owner texts current wait → AI quotes it live to every caller |
| **SMS Follow-Up** | +$49/mo | After-call text: confirmation, directions, daily special, or review ask |
| **Priority Support** | +$99/mo | Direct AJ/Shourya line, faster config changes, quarterly tune-up |

### Example Builds

| Client type | Packages | Monthly |
|---|---|---|
| Restaurant (basic) | Base + Menu | $248/mo |
| Restaurant (full) | Base + Menu + Bookings + Wait | $346/mo |
| Barbershop | Base + Bookings + SMS | $297/mo |
| Nail salon | Base + Bookings | $248/mo |
| Your cost (hardware done) | — | ~$45/mo |

**At 5 restaurant clients (full package): $1,730/mo recurring. Cost: ~$225/mo. Profit: ~$1,500/mo.**

Setup fee: **$500** (hardware + configuration + onboarding). First 2-3 clients: waive or discount to get testimonials.

---

## What Makes It Smarter Than the Dumb Ones

The current "call AI" market is decision trees with text-to-speech. They hit a wall the moment a caller goes off-script:

**Them:** "Press 1 for hours, press 2 for reservations..." → "I didn't understand that, let me transfer you." → rings forever.

**Yours:** A real LLM brain that:
- Understands natural language questions ("What's good for someone who doesn't eat pork?")
- Combines menu data + allergen data to give real answers
- Knows the wait time YOU just texted in
- Detects when someone's getting frustrated and escalates before it becomes a problem
- Never says "I don't understand" — asks a clarifying question instead

### Restaurant-Specific Intelligence

| Scenario | Dumb bot | Your AI |
|---|---|---|
| "Do you have gluten-free options?" | "I'm sorry, I can't help with that" | "Yes, we have three gluten-free dishes — the grilled salmon, the rice bowl, and our house salad. Want me to go over them?" |
| "How long is the wait?" | "Please call back during business hours" | "Right now we're running about 30 minutes on a walk-in. I can put your name down if you'd like." |
| "What's in the chicken pasta?" | silence / transfer | "That's our roasted chicken fettuccine — it has chicken breast, cream sauce, sun-dried tomatoes, and parmesan. It does contain gluten and dairy." |
| "I want to complain about last night" | "I'll transfer you" → rings, no one picks up | "I'm really sorry to hear that. Let me flag this for our manager — can I get your name and the best number to reach you? They'll call you within the hour." + SMS to owner |

### Escalation System

Triggers that route to human follow-up:
- Keywords: "manager," "complaint," "wrong order," "sick," "allergy reaction," "refund," "attorney"
- Sentiment: caller repeating themselves, raised frustration, multiple "no"s
- Unknown territory: question the AI genuinely can't answer after 2 attempts

Escalation flow:
1. AI: "I want to make sure someone gives you the attention you deserve. Can I get your name and number?"
2. Owner receives SMS: `[ESCALATION] Caller: John, 704-555-1234. Reason: Complaint about food from last night.`
3. Log kept in admin dashboard

---

## Gastonia Target List

### Restaurants — Highest Priority

| Business | Address | Why target them |
|---|---|---|
| **Mic's Kitchen** | 141 W Main Ave #101, Downtown Gastonia | Locally owned, comfort food, busy lunch crowd. Single owner can't answer every call. Strong community following. |
| **Webb's Custom Kitchen** | Downtown (old theatre building) | Upscale, reservation-driven. Higher ticket → more willing to pay. Perfect Bookings package sale. |
| **Kyle Fletcher's BBQ** | Gastonia area | Family-run BBQ. Call volume is huge for order/hours questions. Classic dumb-bot victim. |
| **Guacamaya's Restaurant Bar & Grill** | Gastonia | Local, likely underserved by current tech. Community spot with loyal customers. |
| **Gaston Pour House** | Gastonia | Bar + restaurant, event bookings are a killer use case. Wait-time feature = natural fit. |

### Barbershops & Salons — Strong Secondary Targets

Barbershops have extremely high missed-call rates (can't answer while cutting).

| Business | Address | Phone |
|---|---|---|
| **Cash's Barber Shop** | 1451c E Franklin Blvd | (704) 864-6966 |
| **Tim's Barber & Beauty Salon** | 150 E Main Ave (downtown) | (704) 833-0859 |
| **Gaston Barbers** | 3131 Union Rd, Ste 9 | (704) 864-4586 |
| **Latino's Barbershop and Salon** | 904 S New Hope Rd, Ste H | (704) 718-0733 |

---

## Cold Walk-In Script

You walk in during a slow moment. Ask for the owner or manager. Keep it under 2 minutes.

**Opening:**
> "Hey, quick question — when you're with a customer and your phone rings, what usually happens to that call?"

[Let them answer. Common answers: "We miss it," "They leave a voicemail," "My other employee grabs it if they're free"]

**Pivot:**
> "Every one of those missed calls is probably someone who called the next place on the list. We built an AI that picks up every call, 24/7 — answers questions about your menu, quotes the wait, takes reservations, and if it's something it can't handle, it texts you immediately so you can call back. It sounds like your business, not some robot. Can I show you right now? Takes about 90 seconds."

[Call the demo number. Walk them through it.]

**Close:**
> "Starter package is $199 a month — we install a little box, handle everything, and you never miss a call again. We're local, so if anything's ever off we can come by. First month's free — I just want you to see how it works before you decide anything."

---

## Build Order

1. `demo/` — Demo Diner config (YAML + seed data for menu, allergens, hours, wait time hook)
2. Call stack: Twilio webhook → STT (Deepgram) → LLM (local Llama or Phi-4) → TTS (ElevenLabs) → Twilio
3. Local LLM runner (Ollama on mini PC) + FastAPI server receiving webhooks
4. Business config loader: reads YAML, injects into system prompt as structured context
5. Escalation detector: keyword + sentiment → SMS to owner via Twilio
6. Wait time input: owner texts a number → updates live state the AI reads
7. Bookings tool: slots into Google Calendar via OAuth
8. Admin dashboard: simple web UI showing call log + escalations + bookings
9. Provisioning script: set up new client (new Twilio number + YAML config) in <15 min

---

## Stack Summary

| Layer | Tool | Notes |
|---|---|---|
| Phone | Twilio | One number per client, routes to our server |
| STT | Deepgram | Low latency, accurate |
| Brain | Llama 3.1 8B (via Ollama) | Runs on mini PC, no API costs |
| TTS | ElevenLabs | Natural-sounding voice, cloneable |
| Server | FastAPI (Python) | Webhook receiver + LLM orchestrator |
| Memory | SQLite | Per-call conversation history |
| Config | YAML per client | Menu, hours, allergens, staff names, rules |
| Escalation | Twilio SMS | Fires to owner's cell |
| Bookings | Google Calendar API | OAuth per client |
| Dashboard | Simple HTML + SQLite | Read-only call log for owner |
| Hardware | Beelink SER7 mini PC | Installed at client location |

---

*Wiki page. Cross-links: [[Freelance Web Design]], [[Local Brain]], [[AJ — Personal Context Profile]]*
