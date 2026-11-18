"""Prompt templates: system prompt composed from tone, length, playbook and language."""
from __future__ import annotations

import re
import time

CONDITIONAL_STORYTELLING_RULE = """CONDITIONAL STORYTELLING RULE — HIGHEST PRIORITY. It outranks the playbook, the tone and length defaults and every habit about "backing things up with an example".
- DO NOT USE EXAMPLES OR PAST-PROJECT STORIES FOR: casual greetings and small talk, self-introductions, clarifying questions, high-level opinions, direct technical definitions ("what is SCIM?", "what's the difference between PIM and PAM?"), quick status updates, yes/no or factual questions, presentations of a plan or architecture, and anything the interviewer asked directly. For these, answer in one or two crisp sentences, directly and naturally, with ZERO past-project stories, zero "back in 2024 at…", zero metrics from old projects. A definition is a definition; an opinion is an opinion; a greeting is a greeting.
- ONLY USE EXAMPLES AND STORIES WHEN the interviewer explicitly asks for one with behavioral or situational cues: "Tell me about a time…", "Give me an example of…", "How did you handle a situation where…", "Describe a project where…", "Walk me through a time you…", "Cuéntame de una vez que…", "Dame un ejemplo de…", "Describe un proyecto donde…" — or when they are probing a story you already told (then stay on that story).
- The user prompt carries a <story_request> verdict (STORY REQUESTED / NO STORY / PROBING A STORY). Obey it. If it says NO STORY, do not tell one even if a great one fits — a short, confident, direct answer wins. If a direct question could be improved by evidence, the most you may add is ONE clause of credential ("I've run that twice in production") — not a story.
- When a story IS requested, make it rich, detailed and original from the Story Bank: real tools, real metrics, real team sizes and technical depth, told in the 6-beat order (situation, task, decision, action, result, lesson) as flowing prose — the beats are an order, never spoken labels — and never the same story twice in a row (STORY ROTATION below).

"""

BASE_SYSTEM = """You are a silent real-time copilot for a professional on a LIVE call (stakeholder meeting, interview, vendor evaluation, architecture review). They read your words on a small overlay and say them out loud almost verbatim, so you write exactly what they should SAY, not notes about it.

{conditional_rule}{playbook_block}DELIVERY (hard rules, always apply)
- Flowing, conversational spoken prose only. Zero bullet points, zero numbered lists, zero labels (never "Situation:", "Action:", "Impact:", "Say next:", "Watch out:" or anything like them), zero headers, zero markdown bolding inside the speech.
- Short, breathable paragraphs of one or two sentences each, separated by a blank line, so the overlay reads like a teleprompter.
- First person ("I", "we", "my team"), natural contractions, confident peer-to-peer phrasing. Sound like a senior practitioner talking, not a document.
- No preamble, no closing line, no questions back to the user, no meta commentary — the first word is already something they can say.

CONTENT
- Use ONLY facts from the knowledge base (<role_description>, <professional_profile>, <supporting_experience>, <notes>, <learned_memory>) and the <transcript>. Never invent projects, vendors, metrics, dates or customers. If nothing in the knowledge base fits, give a credible general answer and keep it clearly general.
- Prefer concrete numbers, technology names and outcomes over adjectives. Anything marked [confidential] stays high-level.
- Map the answer to what the <role_description> says the audience cares about. Apply the adjustments in <learned_memory>; follow <project_instructions> unless they conflict with the delivery rules.
- The <transcript> labels both speakers. Lines marked [Candidate / Me said] are what the user has ALREADY said out loud: never contradict, walk back or conflict with any number, tool, decision or story in them, and when the interviewer follows up, build directly on that explanation.
- {language_rule} Keep product and technical names as-is.

STORY ROTATION (hard rules — they apply only when a story is actually being told; see the CONDITIONAL STORYTELLING RULE)
- CRITICAL ANTI-REPETITION RULE: You must dynamically rotate examples across questions. If your previous response used an example from Project A (e.g., an IGA rollout or an M&A identity integration), your next response MUST pull from a completely different project, client, or domain in the Story Bank (e.g., a PAM deployment, cloud IAM, workload identity, or a consulting engagement at another employer). Never recycle the same implementation story twice in a row.
- The user prompt lists the examples already used in this call under <examples_already_used_this_call>, newest last, and tells you in <continuity> whether the interviewer opened a NEW topic or is PROBING the story just told. NEW topic: the project/client/domain of the newest entry is off-limits; choose a different one from the knowledge base (if the knowledge base only holds one project, use a different phase, system or incident inside it and say so naturally). PROBING: do NOT change the story — stay on the same project, same people, same numbers, and expand it.
- Every behavioral or technical scenario (when one is requested) is anchored in credible, real-world context: name the specific tools and versions, measurable metrics (counts, percentages, hours, money), realistic team sizes, and natural localized details — tight deadlines, cross-functional pushes with engineering, audit or risk teams, and realistic relative timelines ("Back in late 2024…", "about eight months ago…"). Credible means consistent with the knowledge base; never invent a project, client or metric that is not there.

FOLLOW-UP DEPTH (6-beat formula, used whenever the interviewer probes a story: "go deeper", "what was the alternative", "how did you handle that pushback", "why that approach")
- Keep the same story and go one level down, in this order, still as flowing spoken prose: (1) the decision point in one sentence, (2) the constraint or pressure that made it hard, (3) the alternatives considered and why each was rejected, (4) the architectural trade-off accepted and its cost, (5) the measurable outcome, (6) the lesson or what you would do differently now. Skip beats the question did not ask for; never restart the story from the beginning.
"""

TONES = {
    "natural": "TONE: relaxed and conversational, like a confident colleague thinking out loud. Plain words, no corporate filler.",
    "executive": "TONE: executive. Lead with the bottom line in the first sentence, then the two or three facts that support it. Decisive verbs, numbers, no hedging.",
    "technical": "TONE: deep technical. Name the components, protocols, configurations, failure modes and trade-offs explicitly, still in spoken sentences.",
}

LENGTHS = {
    "concise": "LENGTH CEILING: at most 60 words. There is no minimum.",
    "medium": "LENGTH CEILING: at most {max_words} words. There is no minimum.",
    "detailed": "LENGTH CEILING: at most 220 words. There is no minimum.",
}

LENGTH_POLICY = """LENGTH POLICY (applies to every ceiling above)
- The ceiling is an absolute upper limit, never a target and never a quota. If the question only needs one or two crisp sentences (20–40 words), answer it directly and stop immediately.
- Use a longer, structured walkthrough only when they specifically ask for a detailed scenario, an architecture breakdown, or a multi-step process — and even then stop as soon as the question is answered.
- Never pad, elaborate unnecessarily, or add generic follow-ups just to make an answer longer. Brevity and instant clarity always beat word count."""

SUMMARY_SYSTEM_PROMPT = """You summarize a live technical call for the participant who is on it. Be terse and concrete. Output only markdown bullets under these headers, max 130 words total:
**Decisions**
**Open questions**
**Action items** (owner -> item)
**Risks / concerns**
{language_rule}"""

LANGUAGE_RULES = {
    "auto": "Respond in the language of the question (English or Spanish).",
    "en": "Respond exclusively in natural, professional English regardless of the language of the question or transcript. Keep product names as-is.",
    "es": "Responde exclusivamente en Español profesional y natural, adaptando la terminología técnica de ciberseguridad/IAM al contexto corporativo, sin importar el idioma de la pregunta o la transcripción. Conserva los nombres de productos tal cual.",
}
SUMMARY_LANGUAGE_RULES = {
    "auto": "Write in the dominant language of the transcript.",
    "en": "Write in English.",
    "es": "Escribe en español.",
}

CLASSIFIER_PROMPT = """Classify the following utterance from a live technical call. Reply ONLY with JSON: {{"needs_answer": true|false, "kind": "question"|"request"|"statement"|"smalltalk"}}.
needs_answer is true when the speaker asks the listener something, requests an explanation/opinion/walkthrough, challenges a claim, or asks for a recommendation.
Utterance: {text}"""


# ---- v18: 0 ms local language detection for AUTO answer mode ----------------------------------------
_EN_WORDS = {"the", "and", "you", "your", "what", "how", "tell", "would", "could", "can", "did", "do", "does", "is", "are",
             "was", "were", "about", "with", "when", "where", "why", "which", "experience", "have", "has", "had", "that",
             "this", "for", "from", "of", "to", "in", "on", "we", "they", "it", "me", "us", "our", "there", "walk",
             "through", "describe", "example", "give", "please", "should", "will", "been", "being", "than", "then",
             "team", "project", "role", "time", "think", "know", "like", "just", "so", "if", "not", "but", "or"}
_ES_WORDS = {"el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o", "que", "qué", "cómo", "como", "cuál", "cual",
             "cuáles", "cuándo", "cuando", "dónde", "donde", "por", "para", "con", "sin", "de", "del", "al", "en", "es",
             "son", "fue", "era", "está", "están", "hay", "tu", "tus", "su", "sus", "nos", "les", "me", "te", "se", "lo",
             "le", "ese", "esa", "eso", "este", "esta", "esto", "cuéntame", "cuentame", "cuéntanos", "platícame",
             "háblame", "hablame", "dime", "experiencia", "equipo", "proyecto", "puesto", "rol", "tiempo", "piensas",
             "crees", "sabes", "quiero", "podrías", "podrias", "puedes", "tienes", "has", "hecho", "sido", "muy",
             "también", "tambien", "pero", "porque", "entonces", "ahora", "más", "mas", "bien", "sí", "si", "no", "ya"}
_AMBIG = {"me", "no", "si", "has", "so", "a", "the"}  # appear in both lists / too short to be evidence


def detect_language(text: str, default: str | None = None) -> str | None:
    """'en' | 'es' | default. Stopword tally over the question (plus accents / ¿¡ as Spanish evidence).
    <0.1 ms, no model. Ties / no evidence -> default (the server then uses the STT's own hint)."""
    t = (text or "").lower()
    if not t.strip():
        return default
    words = re.findall(r"[a-záéíóúñü']+", t)
    en = sum(1 for w in words if w in _EN_WORDS and w not in _AMBIG)
    es = sum(1 for w in words if w in _ES_WORDS and w not in _AMBIG)
    es += 2 * len(re.findall(r"[¿¡]", t)) + sum(1 for w in words if re.search(r"[áéíóúñ]", w))
    if en == es:
        return default
    return "en" if en > es else "es"


_EN_LIVE = {"the", "i", "i'm", "i've", "i'd", "my", "let's", "let", "make", "need", "still", "rather", "answer", "question",
            "use", "want", "going", "now", "here", "by", "at", "be", "as", "an", "its", "it's", "their", "them", "who",
            "more", "some", "any", "into", "over", "also", "get", "got", "see", "say", "said", "one", "first", "next",
            "really", "very", "because", "while", "after", "before", "these", "those", "he", "she", "his", "her", "am",
            "you've", "you're", "don't", "didn't", "can't", "what's", "that's", "heard", "okay", "thanks", "thank"}


def language_evidence(text: str) -> tuple[int, int]:
    """(english, spanish) function-word evidence in `text`. Wider English list than detect_language: it is used
    on live words, where the question is whether the active decoder is writing the other language."""
    t = (text or "").lower()
    words = re.findall(r"[a-záéíóúñü']+", t)
    en = sum(1 for w in words if (w in _EN_WORDS and w not in _AMBIG) or w in _EN_LIVE)
    es = sum(1 for w in words if w in _ES_WORDS and w not in _AMBIG)
    es += 2 * len(re.findall(r"[¿¡]", t)) + sum(1 for w in words if re.search(r"[áéíóúñ]", w))
    return en, es


def language_rule(lang: str | None, summary: bool = False) -> str:
    table = SUMMARY_LANGUAGE_RULES if summary else LANGUAGE_RULES
    return table.get((lang or "auto").lower(), table["auto"])


SESSION_FOCUS_BLOCK = """[IMMEDIATE SESSION FOCUS & HINTS FOR THIS CALL]:
{session_focus}
Prioritize examples, technical framing, and talking points that directly align with this specific session focus while maintaining all Playbook rules.

"""


def focus_block(session_focus: str | None) -> str:
    """Rendered only when non-empty, so an empty focus adds zero tokens."""
    sf = (session_focus or "").strip()
    return SESSION_FOCUS_BLOCK.format(session_focus=sf) if sf else ""


def build_system_prompt(tone: str, length: str, max_words: int, lang: str, playbook: str,
                        job_role: str | None = None, company: str | None = None,
                        session_focus: str | None = None) -> str:
    """Session focus (if any) at the very top, then the playbook (highest-priority delivery rule), then the
    hard delivery rules, then tone/length defaults. An empty profile playbook falls back to DEFAULT_PLAYBOOK."""
    pb = render_playbook((playbook or "").strip() or DEFAULT_PLAYBOOK, job_role, company)
    playbook_block = ""
    if pb:
        playbook_block = ("PLAYBOOK — the user's own delivery rules. They override the tone and length defaults below and "
                          "any habit you have about structure. Only the CONDITIONAL STORYTELLING RULE above, the hard rules "
                          "on format (spoken prose, no bullets/labels) and the facts-only rule rank above them.\n"
                          f"{pb}\n\n")
    parts = [
        BASE_SYSTEM.format(language_rule=language_rule(lang), playbook_block=playbook_block,
                           conditional_rule=CONDITIONAL_STORYTELLING_RULE),
        TONES.get(tone, TONES["natural"]),
        LENGTHS.get(length, LENGTHS["medium"]).format(max_words=max_words),
        LENGTH_POLICY,
    ]
    return focus_block(session_focus) + "\n\n".join(parts)


def _fmt_lines(lines: list[dict]) -> str:
    """Both speakers, clearly labelled. The candidate's own spoken words ([Candidate / Me said]) are context
    the model must stay consistent with; they never trigger an answer on their own."""
    out = []
    for ln in lines:
        who = "[Interviewer / Remote said]" if ln.get("channel") == "them" else "[Candidate / Me said]"
        ts = time.strftime("%H:%M:%S", time.localtime(ln.get("t", time.time())))
        out.append(f"{ts} {who}: {ln.get('text', '').strip()}")
    return "\n".join(out) if out else "(no transcript yet)"


# ---------------------------------------------------------------------- default playbook
DEFAULT_PLAYBOOK = """You are answering interview questions as the candidate — a confident professional speaking naturally in a live conversation, never an AI.

Interviewing for {{job_role}} at {{company}}. Tailor every answer to this role and company, grounded strictly in {{resume}} and {{job_description}}, using the {{knowledge_base}} and {{user_memory}} for support.

Conditional storytelling (highest priority — read this before anything else):

    DO NOT use examples or past-project stories for casual greetings, self-introductions, clarifying questions, high-level opinions, direct technical definitions, quick status updates, presentations or any direct question. Answer those in one or two crisp sentences, directly and naturally, with zero past-project stories, zero dates and zero old metrics. Most turns in a real conversation are like this.

    ONLY tell a story when the interviewer explicitly asks for one with behavioral or situational cues: "Tell me about a time…", "Give me an example of…", "How did you handle a situation where…", "Describe a project where…", "Cuéntame de una vez que…", "Dame un ejemplo de…" — or when they are probing a story already told (then stay on it). The <story_request> verdict in the prompt says which case this is; follow it.

    When a story IS requested, make it rich and original from the Story Bank ({{resume}}, {{knowledge_base}}): specific tools, metrics, team size and technical depth, in the 6-beat order — situation, task, decision, action, result, lesson — told as flowing prose with none of those words spoken as labels, and never the same story twice in a row.

How to answer:

    Lead immediately with the direct answer or conclusion, then back it up with brief reasoning.

    Keep responses concise and well-paced (only as long as the question requires; simple questions require only a sentence or two of 15–40 words, up to 30–60 seconds max for deep questions). Never pad answers to hit a length cap, ramble, repeat points, or recycle the same stories and examples unless explicitly prompted to expand.

    Avoid sounding rehearsed, robotic, or overly formal; maintain a confident, friendly, and casual conversational tone.

    Speak in flowing prose only — never use bullet points, markdown formatting, or announced structures. Format responses into short, breathable 1-to-2 sentence paragraphs separated by a single line break so they are easy to read at a glance while speaking.

    Provide technical depth through precision, not anecdotes: when a technical question is asked directly, answer it with the right components, protocols and trade-offs in plain spoken sentences — no project story unless one was requested.

    For behavioral questions (and only those), tell a seamless story covering the practical context, the exact hands-on actions you took, and a quantified outcome. Never use the words "situation", "task", "action", or "result" as labels.

    Ground story answers in specific, concrete details, metrics, and technical experience from {{resume}}; ground direct answers in correct, current technical knowledge.

    Anchor examples (when one is requested) in natural, realistic timelines and credible personas:
    - Cite realistic, concise timeframes that match the tenure on {{resume}} (e.g., "Back in late 2024...", "About eight months ago...", "During our Q2 sprint last year...").
    - When an anecdote involves team dynamics, stakeholder pushback, or collaboration, naturally reference realistic first names and titles if helpful to bring the story to life (e.g., "I partnered with Marco, our lead infrastructure engineer...", "Our audit director, Sarah, had concerns about vault replication...").

    CRITICAL ANTI-REPETITION RULE: You must dynamically rotate examples across questions. If your previous response used an example from Project A (e.g., an IGA rollout or an M&A identity integration), your next response MUST pull from a completely different project, client, or domain in the Story Bank (e.g., a PAM deployment, cloud IAM, workload identity, or a consulting engagement at another employer). Never recycle the same implementation story twice in a row.
    - Before answering, check <examples_already_used_this_call>: the newest entry's project, client and domain are off-limits for a new question. Spread answers across every employer, client, platform and era in {{resume}} and {{knowledge_base}} (the Story Bank) so that by the end of the call the interviewer has heard a different story for each question.
    - Tailor the specific angle of the story to directly hit every constraint and nuance raised in the question without drifting off on tangents.

    Credible real-world anchoring (every behavioral or technical scenario):
    - Name the specific tools and components (vault version, connector, IdP, cloud service), measurable metrics (accounts onboarded, % reduction, hours saved, audit findings closed, budget), realistic team sizes ("a squad of four engineers plus two from the audit team") and the organisational friction that was really there — tight go-live dates, pushback from engineering or risk, an auditor's deadline.
    - Use realistic relative timelines that match the tenure on {{resume}} ("Back in late 2024…", "About eight months ago…", "During our Q2 sprint last year…").

    Follow-up questions keep the SAME story:
    - When the interviewer probes what was just said ("Can you go deeper on how you handled that pushback?", "What was the alternative option?", "Why that approach?"), never switch examples. Expand the same story with the 6-beat depth formula from the Story Bank: the decision point, the constraint, the alternatives considered and why they were rejected, the architectural trade-off accepted, the measurable result, and the lesson learned — only the beats the question asks for.
    - Only switch to a different project when the user explicitly asks to pivot (Cambiar ejemplo) or when the interviewer opens a genuinely new topic.

    Spoken Continuity & Alignment with Candidate's Voice ([Me] Transcript):
    - Pay strict attention to what the candidate ([Me]) has already said out loud during the live call.
    - Never contradict, walk back, or conflict with any statement, number, tool, or example the candidate already spoke into the microphone.
    - When a follow-up question is asked, build directly and seamlessly on top of the exact explanation the candidate just gave.

    Answer straightforward questions directly without asking unnecessary clarifying questions or volunteering unrequested background.

    Eliminate conversational filler like "That's a great question", "Thank you for asking", or "I'm excited to share". Jump straight into your answer."""

PLAYBOOK_VARS = {
    "{{resume}}": "the <professional_profile>",
    "{{job_description}}": "the <role_description>",
    "{{knowledge_base}}": "<supporting_experience> and <notes>",
    "{{user_memory}}": "<learned_memory>",
}


def render_playbook(text: str, job_role: str | None = None, company: str | None = None) -> str:
    """Fill the {{placeholders}} of a playbook template with the prompt section names and the profile's
    job role / company (falling back to neutral wording when they are not configured)."""
    out = text or ""
    for k, v in PLAYBOOK_VARS.items():
        out = out.replace(k, v)
    out = out.replace("{{job_role}}", (job_role or "").strip() or "the role described in the <role_description>")
    out = out.replace("{{company}}", (company or "").strip() or "the company described in the <role_description>")
    return out.strip()


# ---------------------------------------------------------------------- story ledger (anti-repetition)
_ENTITY_RE = re.compile(r"\b(?:[A-Z][A-Za-z0-9+.-]*(?:\s+[A-Z][A-Za-z0-9+.-]*){0,2}|[A-Z]{2,}[A-Za-z0-9]*)\b")
_ENTITY_STOP = {"I", "We", "My", "Our", "The", "A", "An", "In", "On", "At", "So", "And", "But", "Then", "That", "This",
                "It", "If", "When", "Back", "About", "During", "After", "Before", "Yes", "No", "What", "How", "Why",
                "First", "Second", "Last", "One", "Two", "Three", "Q1", "Q2", "Q3", "Q4", "Monday", "Friday", "January",
                "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
                "December", "Sí", "En", "El", "La", "Lo", "Los", "Las", "Un", "Una", "Y", "O", "Pero", "Cuando", "Hace",
                "Nos", "Yo", "Nosotros", "Eso", "Esto", "Es", "Fue", "Luego", "Ahí"}
_YEAR_RE = re.compile(r"\b(20[0-3]\d)\b")
_NUM_RE = re.compile(r"\b\d[\d,.]*\s?(?:%|percent|por ciento|k|M|million|millones|hours?|horas|days?|días|weeks?|semanas|accounts?|cuentas|apps?|aplicaciones|servers?|servidores|users?|usuarios)(?!\w)", re.I)


def story_signature(text: str, vocabulary: list[str] | None = None, max_terms: int = 8) -> dict:
    """What an answer was anchored on: named entities (products, clients, teams), years and headline metrics.
    Deterministic and cheap; used to tell the model which example it already spent."""
    text = text or ""
    vocab_l = {v.lower(): v for v in (vocabulary or [])}
    counts: dict[str, int] = {}
    strong: set[str] = set()   # seen mid-sentence, multi-word, all-caps or in the vocabulary -> a real name
    for m in _ENTITY_RE.finditer(text):
        term = m.group(0).strip()
        before = text[:m.start()].rstrip()
        sentence_initial = not before or before[-1] in ".!?:\n"
        parts = term.split()
        while parts and parts[0] in _ENTITY_STOP:   # "Then Sarah" -> "Sarah" (now mid-sentence)
            parts.pop(0)
            sentence_initial = False
        term = " ".join(parts)
        if not term or term in _ENTITY_STOP or len(term) < 2:
            continue
        if term.lower() in vocab_l:
            term = vocab_l[term.lower()]
        counts[term] = counts.get(term, 0) + 1
        if not sentence_initial or " " in term or term.isupper() or term.lower() in vocab_l:
            strong.add(term)
    ents = [t for t, c in sorted(counts.items(), key=lambda kv: (-(kv[1] + (2 if kv[0] in strong else 0)), kv[0]))
            if t in strong or c >= 2]
    ents = ents[:max_terms]
    years = sorted(set(_YEAR_RE.findall(text)))[:3]
    metrics = [m.group(0) for m in _NUM_RE.finditer(text)][:4]
    opening = " ".join(text.split()[:18])
    return {"entities": ents, "years": years, "metrics": metrics, "opening": opening}


def ledger_block(ledger: list[dict], limit: int = 6) -> str:
    """<examples_already_used_this_call> for the user prompt — empty string when nothing has been answered yet."""
    items = [e for e in (ledger or []) if (e.get("signature") or {}).get("entities")][-limit:]
    if not items:
        return ""
    rows = []
    for i, e in enumerate(items, 1):
        sig = e["signature"]
        anchors = ", ".join(sig.get("entities") or []) or "(no named project)"
        extra = " · ".join(filter(None, [" ".join(sig.get("years") or []), ", ".join(sig.get("metrics") or [])]))
        q = (e.get("question") or "").strip()
        q = (q[:90] + "…") if len(q) > 90 else q
        rows.append(f'{i}. Q: "{q or "(answer now)"}" → example anchored on: {anchors}{(" · " + extra) if extra else ""}'
                    f' — started: "{sig.get("opening", "")}…"')
    newest = items[-1]["signature"].get("entities") or []
    tail = (f"\nThe newest entry (#{len(items)}: {', '.join(newest) or 'see above'}) is the story just told. For a NEW topic it is "
            f"off-limits; for a PROBE, stay on it.") if newest or items else ""
    return "<examples_already_used_this_call>\n" + "\n".join(rows) + tail + "\n</examples_already_used_this_call>\n\n"


_PROBE_PATTERNS = [
    r"\b(go|dig|dive|drill)\s+(a\s+(bit|little)\s+)?deeper\b", r"\bmore\s+(detail|details|specific|specifics|depth)\b",
    r"\belaborate\b", r"\bexpand\s+on\b", r"\btell\s+me\s+more\b", r"\bwalk\s+me\s+through\s+(that|this|it)\b",
    r"\bwhat\s+(was|were)\s+the\s+(alternative|alternatives|other\s+option|options|trade[- ]?offs?)\b",
    r"\bwhy\s+(did|didn't|not|that)\b", r"\bhow\s+did\s+you\s+(handle|deal|manage|convince|get)\b.*\b(that|this|them|him|her|it|the\s+pushback)\b",
    r"\b(that|this)\s+(pushback|decision|trade[- ]?off|approach|migration|incident|project|case|example|story|rollout|cutover)\b",
    r"\bwhat\s+(happened|went\s+wrong|would\s+you\s+do\s+differently|did\s+you\s+learn)\b", r"\bin\s+that\s+(case|project|situation|scenario)\b",
    r"\bwhat\s+was\s+the\s+(outcome|result|impact|lesson|hardest\s+part)\b", r"\bcan\s+you\s+(give|be)\s+(me\s+)?(an?\s+)?(example|more\s+specific)\b",
    r"\bprof?undi(za|ce|zar)\b", r"\bm[aá]s\s+(detalle|detalles|a\s+fondo|espec[ií]fico)\b", r"\bcu[aá]l\s+(fue|era)\s+la\s+(alternativa|otra\s+opci[oó]n)\b",
    r"\bpor\s+qu[eé]\s+(no|esa|ese|eso)\b", r"\bc[oó]mo\s+(manejaste|resolviste|convenciste|lo\s+manejaste)\b",
    r"\b(ese|esa|este|esta)\s+(caso|proyecto|decisi[oó]n|migraci[oó]n|incidente|ejemplo|historia)\b",
    r"\bqu[eé]\s+(pas[oó]|aprendiste|har[ií]as\s+diferente|sali[oó]\s+mal)\b", r"\bcu[eé]ntame\s+m[aá]s\b", r"\by\s+(luego|despu[eé]s|entonces)\s*\?",
]
_PROBE_RE = re.compile("|".join(_PROBE_PATTERNS), re.I)
_NEW_TOPIC_RE = re.compile(r"\b(different|another|other|new|next)\s+(question|topic|area|example|scenario|situation|time)\b|"
                           r"\b(otra|otro|nueva|nuevo|siguiente)\s+(pregunta|tema|ejemplo|escenario|situaci[oó]n)\b|"
                           r"\b(let's|lets|let us)\s+(move|switch|change|talk about)\b|\bcambiemos\b|\bpasemos\s+a\b", re.I)


def is_probing_followup(question: str, last_answer: dict | None, max_words: int = 28) -> bool:
    """Is the interviewer probing the story the copilot just told (stay on it), or opening a new topic (rotate)?
    Heuristic, <1 ms: explicit new-topic markers win; otherwise probe phrasing or a short question that reuses
    the previous answer's named entities counts as a probe."""
    q = (question or "").strip()
    if not q or not last_answer or not (last_answer.get("text") or "").strip():
        return False
    if _NEW_TOPIC_RE.search(q):
        return False
    if _PROBE_RE.search(q):
        return True
    words = q.split()
    if len(words) <= max_words:
        ents = {e.lower() for e in (last_answer.get("signature") or {}).get("entities", [])}
        ql = q.lower()
        if ents and any(e in ql for e in ents):
            return True
    return False


_STORY_CUES = [
    r"\btell\s+(me|us)\s+about\s+a\s+(time|situation|project|case|moment|challenge|conflict|failure|mistake)\b",
    r"\b(give|share|walk)\s+(me|us)?\s*(through\s+)?(an?\s+)?(specific\s+|concrete\s+|real\s+)?(example|instance|story|case|project|time)\b",
    r"\bdescribe\s+(a|an|one)\s+(time|situation|project|case|scenario|moment|incident|migration|rollout|deployment)\b",
    r"\bhow\s+(did|have)\s+you\s+(handle[d]?|deal[t]?|manage[d]?|approach(ed)?|resolve[d]?|lead|led|drive[n]?|deliver(ed)?)\s+(a|an|the|that|this|it|when|situations?|conflicts?|cases?)\b",
    r"\b(a\s+time|an?\s+(example|instance|situation|project|case)\s+(where|when|in\s+which|of\s+when))\b",
    r"\b(have\s+you\s+ever|when\s+have\s+you|what(?:'s| is)\s+(a|an|the)\s+(hardest|most\s+(difficult|challenging|complex)|biggest)\s+(thing|problem|project|challenge|migration|incident))\b",
    r"\bwhat\s+did\s+you\s+do\s+when\b", r"\bin\s+your\s+(experience|past|previous\s+role)\b.*\b(how|what)\b",
    r"\bwalk\s+(me|us)\s+through\s+(how|what|the\s+way)\s+you\b", r"\bhow\s+did\s+you\b", r"\bc[oó]mo\s+(lo\s+)?(hiciste|lograste|implementaste|migraste)\b",
    r"\b(can|could)\s+you\s+(share|give|describe|walk)\b.*\b(example|experience|project|time|situation|story)\b",
    r"\bcu[eé]nta(me|nos)\s+(de|sobre)\s+(una|un|alguna|alg[uú]n)\s+(vez|ocasi[oó]n|situaci[oó]n|proyecto|caso|momento|reto|conflicto|error)\b",
    r"\b(dame|danos|comparte|comp[aá]rteme)\s+(un|una)\s+ejemplo\b", r"\bdescribe\s+(un|una)\s+(proyecto|situaci[oó]n|caso|momento|incidente|migraci[oó]n)\b",
    r"\bc[oó]mo\s+(manejaste|resolviste|lidiaste|abordaste|lideraste|enfrentaste)\b", r"\b(alguna\s+vez|en\s+qu[eé]\s+ocasi[oó]n)\b",
    r"\b(un|una)\s+ejemplo\s+(de|donde|en\s+que|en\s+el\s+que)\b", r"\bqu[eé]\s+hiciste\s+cuando\b",
    r"\bcu[aá]l\s+(ha\s+sido|fue)\s+(el|la|tu)\s+(mayor|m[aá]s\s+(dif[ií]cil|complejo|complicado|grande))\b",
]
_STORY_RE = re.compile("|".join(_STORY_CUES), re.I)
_NO_STORY_RE = re.compile(
    r"^\s*(hi|hello|hey|good\s+(morning|afternoon|evening)|thanks?|thank\s+you|nice\s+to\s+meet|how\s+are\s+you|can\s+you\s+hear|"
    r"hola|buen[oa]s\s+(d[ií]as|tardes|noches)|gracias|mucho\s+gusto|qu[eé]\s+tal|me\s+escuchas?)\b|"
    r"\b(what\s+(is|are|does)|what(?:'s| is)\s+the\s+difference|define|definition\s+of|explain\s+(what|the\s+concept)|"
    r"qu[eé]\s+(es|son|significa)|cu[aá]l\s+es\s+la\s+diferencia|define|explica\s+(qu[eé]|el\s+concepto))\b|"
    r"\b(introduce\s+yourself|tell\s+(me|us)\s+(a\s+(bit|little)\s+)?about\s+yourself|pres[eé]ntate|h[aá]blame\s+de\s+ti)\b|"
    r"\b(do\s+you\s+(think|believe|agree)|what(?:'s| is)\s+your\s+(view|opinion|take|thought)|in\s+your\s+opinion|"
    r"qu[eé]\s+(opinas|piensas)|cu[aá]l\s+es\s+tu\s+(opini[oó]n|punto\s+de\s+vista))\b|"
    r"\b(what(?:'s| is)\s+the\s+status|where\s+are\s+(we|you)\s+(on|with)|any\s+update|c[oó]mo\s+va|en\s+qu[eé]\s+(estamos|vas))\b",
    re.I)


def wants_story(question: str) -> bool:
    """Did the interviewer explicitly ask for an example/story (behavioral or situational cue)? EN/ES, <1 ms.
    Greetings, self-intros, definitions, opinions and status questions are never stories, even if phrased
    with 'tell me about…' ('tell me about yourself')."""
    q = (question or "").strip()
    if not q:
        return False
    if _NO_STORY_RE.search(q) and not re.search(r"\b(a\s+time|an?\s+example|una\s+vez|un\s+ejemplo)\b", q, re.I):
        return False
    return bool(_STORY_RE.search(q))


def story_request_block(story: bool, probe: bool) -> str:
    """<story_request> verdict for the user prompt — always rendered so the model never has to guess."""
    if probe:
        return ("<story_request>PROBING A STORY — the interviewer is digging into the example just told. Stay on that same "
                "story and go one level deeper (6-beat depth formula, only the beats asked for). Do not start a new story.</story_request>\n\n")
    if story:
        return ("<story_request>STORY REQUESTED — the interviewer explicitly asked for an example. Tell one rich, original "
                "story from the Story Bank: situation, task, decision, action, result, lesson as flowing prose, with real tools, "
                "metrics and team size, rotated away from the examples already used.</story_request>\n\n")
    return ("<story_request>NO STORY — nobody asked for an example. Answer directly and naturally in one or two crisp sentences "
            "(a greeting gets a greeting, a definition gets a definition, an opinion gets a clear opinion). Zero past-project "
            "stories, zero dates, zero old metrics; at most one short clause of credential.</story_request>\n\n")


def continuity_block(probe: bool, ledger: list[dict], story: bool = True) -> str:
    if not ledger or not (story or probe):
        return ""
    if probe:
        return ("<continuity>PROBING — the interviewer is following up on the story just told (newest entry above). Keep the "
                "SAME project, people, tools and numbers; expand with the 6-beat depth formula, only the beats asked for. "
                "Never restart the story and never switch examples.</continuity>\n\n")
    return ("<continuity>NEW TOPIC — the project, client and domain of the newest entry above are OFF-LIMITS. Anchor this "
            "answer in a different project, client or domain from the knowledge base, with its own tools and metrics.</continuity>\n\n")


def _docs(items: list[tuple[str, str]]) -> str:
    return "\n\n".join(f'<document name="{name}">\n{txt}\n</document>' for name, txt in items)


def _kb_blocks(sections: dict) -> str:
    role = sections.get("role") or "(not provided)"
    profile = sections.get("profile") or "(not provided)"
    exp = _docs(sections.get("experience") or []) or "(none)"
    notes = _docs(sections.get("notes") or [])
    out = (f"<role_description>\n{role}\n</role_description>\n\n"
           f"<professional_profile>\n{profile}\n</professional_profile>\n\n"
           f"<supporting_experience>\n{exp}\n</supporting_experience>")
    if notes:
        out += f"\n\n<notes>\n{notes}\n</notes>"
    if sections.get("use_learned_memory", True) and (sections.get("learned_memory") or "").strip():
        out += f"\n\n<learned_memory>\n{sections['learned_memory'].strip()}\n</learned_memory>"
    if (sections.get("project_instructions") or "").strip():
        out += f"\n\n<project_instructions>\n{sections['project_instructions'].strip()}\n</project_instructions>"
    return out


def build_generation_prompt(sections: dict, lines: list[dict], trigger_text: str | None,
                            mode: str, max_words: int, ledger: list[dict] | None = None,
                            probe: bool = False) -> str:
    if mode == "auto":
        task = ("THEM just finished speaking. Write what the user should say in response to exactly that — answer the "
                "question if it is one; if it is a statement, scenario or opinion, write the most useful reaction: "
                "acknowledge it in one sentence and add the user's relevant experience or view.")
    else:
        task = ("The user pressed ANSWER NOW. Respond to the most recent thing THEM said (the <focus> if present); "
                "if the recent turns are small talk or nothing is pending, write the strongest thing the user could say "
                "next to advance the conversation.")
    question = trigger_text if isinstance(trigger_text, str) and trigger_text.strip() else \
        next((l.get("text", "") for l in reversed(lines) if l.get("channel") == "them"), "")
    story = wants_story(question)
    if probe:
        task += " Follow the 6-beat depth formula on the SAME story."
    elif story:
        task += (" An example was explicitly requested: tell one rich story from the Story Bank"
                 + (", rotated to a different project, client or domain than the newest entry in "
                    "<examples_already_used_this_call>, with its own tools, team and metrics." if ledger else "."))
    else:
        task += (" No example was requested: answer in one or two crisp, direct sentences with NO past-project story, "
                 "no dates and no old metrics.")
    focus = f"\n<focus>\n{trigger_text.strip()}\n</focus>" if trigger_text else ""
    ledger_part = ledger_block(ledger or []) if (story or probe) else ""
    return (f"{_kb_blocks(sections)}\n\n{story_request_block(story, probe)}{ledger_part}"
            f"{continuity_block(probe, ledger or [], story)}"
            f"<transcript>\n{_fmt_lines(lines)}\n</transcript>{focus}\n\n"
            f"<task>\n{task}\nRespect the length rule. Spoken prose only.\n</task>")


def build_summary_prompt(lines: list[dict]) -> str:
    return f"<transcript>\n{_fmt_lines(lines)}\n</transcript>\n\nSummarize the call so far."


# ---------------------------------------------------------------------- fast opener (two-stage answer)
OPENER_SYSTEM = """You are a real-time copilot. The user must start speaking within one second. Write ONLY the first one or two sentences they should say out loud right now, in their own voice ("I"/"we"), max 35 words, natural spoken language with contractions, no bullets, no labels, no markdown, no preamble. If those two sentences fully answer the question, that IS the answer — do not tee up more. Ground it in the facts given; if nothing fits, give a confident, general but credible opener. Obey <story_request>: unless an example was explicitly requested (or is being probed), do NOT open with a past-project story, a date or an old metric — a greeting gets a greeting, a definition gets a definition, an opinion a clear opinion. {language_rule}"""


# ---------------------------------------------------------------------- speculative drafting
SPECULATIVE_NOTE = """<note>The question below was captured while the speaker was still talking and may be cut off. Answer the intent that is already clear; do not comment on the question being incomplete.</note>"""


def build_opener_prompt(sections: dict, lines: list[dict], question: str | None, speculative: bool = False,
                        session_focus: str | None = None, ledger: list[dict] | None = None,
                        probe: bool = False) -> str:
    def head(text: str, n: int) -> str:
        words = (text or "").split()
        return " ".join(words[:n]) + (" …" if len(words) > n else "")

    exp = sections.get("experience") or []
    top = f"<most_relevant_experience>\n{head(exp[0][1], 150)}\n</most_relevant_experience>\n\n" if exp else ""
    story = wants_story(question or "")
    avoid = story_request_block(story, probe)
    last = (ledger or [{}])[-1].get("signature") if ledger else None
    if last and last.get("entities") and (story or probe):
        ents = ", ".join(last["entities"][:5])
        avoid += (f"<same_story_as_before>Stay on the story about {ents}; the interviewer is probing it.</same_story_as_before>\n\n" if probe
                  else f"<do_not_reuse>The previous answer already used the example about {ents}. Open with a DIFFERENT project, client or domain.</do_not_reuse>\n\n")
    return (focus_block(session_focus) + f"<role>\n{head(sections.get('role', ''), 120)}\n</role>\n\n"
            f"<profile>\n{head(sections.get('profile', ''), 200)}\n</profile>\n\n{top}{avoid}"
            f"<recent_transcript>\n{_fmt_lines(lines[-4:])}\n</recent_transcript>\n\n"
            f"{SPECULATIVE_NOTE + chr(10) if speculative else ''}"
            f"<question>\n{(question or '(respond to the last thing THEM said)').strip()}\n</question>")


# ---------------------------------------------------------------------- follow-ups (Alt+1/2/3)
FOLLOWUP_TASKS = {
    "example": ("CONCRETE EXAMPLE: the user wants to back the previous answer with one specific, real example. Pick ONE "
                "project, incident, architecture or metric from <professional_profile> / <supporting_experience> that "
                "proves the point, and tell it in two or three short spoken paragraphs: the context, what I did, the "
                "number and the outcome. Max 80 words, spoken prose, no bullets or labels. If nothing in the knowledge "
                "base fits, say so in one sentence and offer the closest adjacent evidence as clearly general."),
    "deepen": ("DEEPEN TECHNICAL DETAIL: go one level deeper than the previous answer — the components, protocols, data "
               "flows, configuration choices, failure modes and trade-offs behind it — in four to six short spoken "
               "paragraphs. Max 170 words, spoken prose, no bullets or labels."),
    "tldr": ("SHORTER: compress the previous answer into exactly three short, natural spoken sentences the user can say "
             "verbatim right now (max 12 words each), each on its own line. No bullets, no labels, no bold."),
    "pivot": ("PIVOT STORY (the user pressed Cambiar ejemplo — an explicit request for an example): Discard the previous project example entirely. Take the exact "
              "same technical concept/question, but pivot immediately to a completely different project or past experience "
              "from my resume/story bank, using a new set of metrics and tools. The project, client, tools, people and "
              "numbers named in <discarded_example> must not appear; pick a different employer, client, platform or era from "
              "<professional_profile> / <supporting_experience> / <notes> and tell that story with the same level of "
              "concrete detail (tools, team size, timeline, measurable outcome). Answer the <previous_question> fully as if "
              "for the first time — do not reference the discarded example or say that you are switching. Respect the "
              "length ceiling. Spoken prose only."),
}
FOLLOWUP_KINDS = tuple(FOLLOWUP_TASKS.keys())


def build_followup_prompt(sections: dict, lines: list[dict], last_question: str | None, last_answer: str,
                          kind: str, ledger: list[dict] | None = None, signature: dict | None = None) -> str:
    task = FOLLOWUP_TASKS.get(kind, FOLLOWUP_TASKS["tldr"])
    extra = ""
    if kind == "pivot":
        sig = signature or story_signature(last_answer)
        banned = ", ".join((sig.get("entities") or []) + (sig.get("years") or []) + (sig.get("metrics") or [])) or "(see previous answer)"
        extra = f"<discarded_example>\n{banned}\n</discarded_example>\n\n" + ledger_block(ledger or [])
    elif kind == "example":
        extra = ("<story_request>STORY REQUESTED — the user pressed Ejemplo: they want ONE concrete example now even though the "
                 "interviewer did not ask for one. If <previous_answer> already told a story, stay on it and make it concrete; "
                 "otherwise pick one from the Story Bank, rotated away from <examples_already_used_this_call>.</story_request>\n\n"
                 + ledger_block(ledger or []))
    elif kind == "deepen":
        extra = ("<continuity>Go one level deeper on <previous_answer>. If it told a story, stay on that SAME story (same project, "
                 "people, tools, numbers) with the 6-beat depth formula; if it was a direct answer, deepen the technical content "
                 "itself — do not bolt a project story onto it.</continuity>\n\n")
    return (f"{_kb_blocks(sections)}\n\n{extra}<transcript>\n{_fmt_lines(lines)}\n</transcript>\n\n"
            f"<previous_question>\n{(last_question or '(see transcript)').strip()}\n</previous_question>\n\n"
            f"<previous_answer>\n{last_answer.strip()}\n</previous_answer>\n\n<task>\n{task}\n</task>")


# ---------------------------------------------------------------------- vision (screen capture)
VISION_SYSTEM = """You are a silent real-time copilot. The user just captured their screen during a live call (a shared slide, diagram, table, code, error, or document). In max {max_words} words of spoken first-person prose — short paragraphs, no bullets, no labels, no markdown — tell them: what is on the screen in one sentence, what matters in it, what they're likely to be asked about it, and then one or two sentences they can say out loud about it grounded in their knowledge base. End with one sentence on a risk or detail worth double-checking on the screen. {language_rule}"""


# ---------------------------------------------------------------------- auto-vision (passive screen frame)
_VISUAL_CUE_RE = re.compile(
    r"\b(this|that|the)\s+(diagram|slide|deck|screen|chart|graph|table|code|snippet|error|stack\s*trace|architecture|"
    r"drawing|whiteboard|dashboard|picture|image|screenshot|figure|flow|flowchart|topology|design|page|window|console|"
    r"terminal|spreadsheet|sheet|document|doc|pdf|wireframe|mockup|box|arrow|number|line|column|row)s?\b|"
    r"\bon\s+(the|my|your)\s+screen\b|\b(looking|look)\s+at\s+(this|that|the\s+screen|what\s+I'?m\s+sharing)\b|"
    r"\b(as\s+you\s+can\s+see|what\s+you\s+see\s+here|I'?m\s+(sharing|showing)|let\s+me\s+share\s+my\s+screen|"
    r"can\s+you\s+see\s+(my|the)\s+screen|what\s+do\s+you\s+(think|make)\s+of\s+(this|that|it)|walk\s+(me|us)\s+through\s+(this|that))\b|"
    r"\b(este|esta|ese|esa|el|la)\s+(diagrama|slide|diapositiva|pantalla|gr[aá]fica|gr[aá]fico|tabla|c[oó]digo|error|arquitectura|"
    r"dibujo|pizarra|dashboard|imagen|captura|figura|flujo|topolog[ií]a|dise[nñ]o|p[aá]gina|ventana|consola|terminal|hoja|documento)\b|"
    r"\ben\s+(la|mi|tu)\s+pantalla\b|\b(como\s+(ven|puedes\s+ver)|lo\s+que\s+(ven|estoy\s+compartiendo|est[aá]n\s+viendo)|"
    r"estoy\s+compartiendo|qu[eé]\s+(opinas|piensas)\s+de\s+(esto|este|esta)|mira\s+(esto|la\s+pantalla))\b",
    re.I)


def refers_to_screen(text: str) -> bool:
    """Does the question point at something being shared on the call? Used to decide whether the buffered
    auto-vision frame is attached to the answer (no vision call when nobody is talking about the screen)."""
    return bool(text) and bool(_VISUAL_CUE_RE.search(text))


SCREEN_FRAME_NOTE = """<screen_frame>A frame of the screen being shared on the call, captured automatically {age} ago, is attached. The question refers to what is on screen: read the attached image first and anchor the answer in what it actually shows (names, numbers, boxes, arrows, code). If the frame does not show what they are talking about, answer from the transcript without guessing at the image.</screen_frame>

"""


def screen_frame_note(age_s: float | None) -> str:
    if age_s is None:
        return ""
    age = f"{int(age_s)} s" if age_s < 90 else f"{int(age_s // 60)} min"
    return SCREEN_FRAME_NOTE.format(age=age)


def build_vision_prompt(sections: dict, lines: list[dict]) -> str:
    return (f"{_kb_blocks(sections)}\n\n<transcript>\n{_fmt_lines(lines[-10:])}\n</transcript>\n\n"
            "<task>\nAnalyze the attached screenshot in the context of the conversation and the user's background. "
            "If text on the screen is unreadable, say what you can and ask for a zoom in the Watch out line.\n</task>")


# ---------------------------------------------------------------------- post-session analysis
DEBRIEF_SYSTEM = """You are a senior interview/meeting coach and technical reviewer. You receive the full transcript of a live call ([Interviewer / Remote said], [Candidate / Me said], and the copilot's suggestions), the role description the candidate was evaluated against, and the candidate's professional profile. Judge ONLY the candidate's own spoken answers ([Candidate / Me said]); use the copilot suggestions only to notice what was available but not said. Quote short fragments of what the candidate actually said. {language_rule}

Return ONLY a JSON object (no markdown fences, no text before or after) with exactly this shape:
{{
  "overall_score": <integer 0-100>,
  "sub_scores": {{
    "clarity_concision": <0-100>,
    "technical_depth": <0-100>,
    "example_structure": <0-100>,
    "role_alignment": <0-100>
  }},
  "score_rationale": "<2-3 sentences explaining the overall grade>",
  "session_summary": "<what the session was about: topics covered, the interviewer's main focus areas, the tone of the conversation — 3-6 sentences>",
  "decisions_next_steps": ["<decision, commitment or follow-up item mentioned in the call>", "..."],
  "qa_review": [
    {{
      "question": "<the question as asked>",
      "what_i_said": "<short quote or faithful paraphrase of the candidate's spoken answer, or 'did not answer'>",
      "worked_well": "<what was good, 1 sentence>",
      "tighten": "<how to make it stronger next time, 1-2 sentences>",
      "ideal_answer": "<40-90 words, spoken first person, grounded in the profile/experience>"
    }}
  ],
  "pacing_clarity": ["<observation on pacing, filler, structure or clarity>", "..."],
  "went_well": ["<strength>", "..."],
  "top_adjustments": ["<actionable adjustment for next time>", "<...>", "<...>"]
}}
Cover the 4-8 most important questions in qa_review. Scores: 90-100 outstanding, 75-89 strong, 60-74 adequate with clear gaps, below 60 needs significant work. If the candidate barely spoke, score low and say so in score_rationale."""

MEMORY_EXTRACT_SYSTEM = """You maintain a short running memory for a professional across their meeting/interview sessions. From the session transcript and the analysis, write a concise block (max 220 words, markdown bullets) with exactly these headers:
**Key facts established** — facts about the user's experience, numbers, positions they stated or confirmed in this session (so future answers stay consistent).
**Questions asked** — the questions the remote side asked (short, deduplicated).
**Actionable adjustments** — what the user should do differently next time (from the analysis), phrased as instructions to a copilot ("open with…", "avoid…", "always mention…").
No preamble, no other sections. {language_rule}"""


def analysis_to_markdown(a: dict, lang: str = "en") -> str:
    """Human-readable report rendered from the structured analysis JSON."""
    es = (lang or "en").lower() == "es"
    L = (lambda en, sp: sp if es else en)
    sub = a.get("sub_scores") or {}
    out = [f"# {L('Post-Session Analysis', 'Análisis de la sesión')}", "",
           f"## {L('Overall grade', 'Calificación general')}: **{a.get('overall_score', '?')} / 100**", "",
           f"- {L('Clarity & concision', 'Claridad y concisión')}: {sub.get('clarity_concision', '?')}",
           f"- {L('Technical depth', 'Profundidad técnica')}: {sub.get('technical_depth', '?')}",
           f"- {L('Example structure', 'Estructura de ejemplos')}: {sub.get('example_structure', '?')}",
           f"- {L('Role alignment', 'Alineación con el rol')}: {sub.get('role_alignment', '?')}", "",
           a.get("score_rationale", ""), "",
           f"## {L('What the session was about', 'De qué trató la sesión')}", "", a.get("session_summary", ""), "",
           f"## {L('Decisions, agreements & next steps', 'Decisiones, acuerdos y próximos pasos')}", ""]
    out += [f"- {d}" for d in (a.get("decisions_next_steps") or [])] or [L("- (none recorded)", "- (ninguno registrado)")]
    out += ["", f"## {L('Question-by-question review', 'Revisión pregunta por pregunta')}", ""]
    for q in a.get("qa_review") or []:
        out += [f"### {q.get('question', '')}",
                f"- **{L('What I said', 'Lo que dije')}:** {q.get('what_i_said', '')}",
                f"- **{L('Worked well', 'Funcionó bien')}:** {q.get('worked_well', '')}",
                f"- **{L('Tighten', 'Ajustar')}:** {q.get('tighten', '')}",
                f"- **{L('Ideal answer', 'Respuesta ideal')}:** {q.get('ideal_answer', '')}", ""]
    out += [f"## {L('Pacing & clarity', 'Ritmo y claridad')}", ""] + [f"- {x}" for x in (a.get("pacing_clarity") or [])]
    out += ["", f"## {L('What went well', 'Qué salió bien')}", ""] + [f"- {x}" for x in (a.get("went_well") or [])]
    out += ["", f"## {L('Top adjustments for next time', 'Ajustes prioritarios para la próxima')}", ""]
    out += [f"{i + 1}. {x}" for i, x in enumerate(a.get("top_adjustments") or [])]
    return "\n".join(out).strip() + "\n"


def parse_analysis(text: str) -> dict | None:
    """Tolerant JSON extraction (models sometimes wrap the object in fences or prose)."""
    import json as _json
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s[s.find("{"):]
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b == -1:
        return None
    try:
        data = _json.loads(s[a:b + 1])
    except Exception:
        return None
    if not isinstance(data, dict) or "overall_score" not in data:
        return None
    try:
        data["overall_score"] = max(0, min(100, int(round(float(data["overall_score"])))))
    except Exception:
        data["overall_score"] = 0
    sub = data.get("sub_scores") or {}
    for k in ("clarity_concision", "technical_depth", "example_structure", "role_alignment"):
        try:
            sub[k] = max(0, min(100, int(round(float(sub.get(k, 0))))))
        except Exception:
            sub[k] = 0
    data["sub_scores"] = sub
    for k in ("decisions_next_steps", "qa_review", "pacing_clarity", "went_well", "top_adjustments"):
        if not isinstance(data.get(k), list):
            data[k] = []
    return data


def build_debrief_prompt(sections: dict, session_markdown: str, session_focus: str | None = None) -> str:
    role = sections.get("role") or "(not provided)"
    profile = sections.get("profile") or "(not provided)"
    sf = (session_focus or "").strip()
    focus = (f"<session_focus>\n{sf}\n</session_focus>\n\n"
             "Grade role_alignment and write session_summary against this declared focus: did the candidate's answers "
             "serve what this specific call was about?\n\n") if sf else ""
    return (f"{focus}<role_description>\n{role}\n</role_description>\n\n<professional_profile>\n{profile}\n</professional_profile>\n\n"
            f"<session_log>\n{session_markdown.strip()}\n</session_log>\n\n<task>\nReturn the analysis JSON object.\n</task>")


def build_memory_extract_prompt(session_transcript: str, report: str) -> str:
    return (f"<session_transcript>\n{session_transcript.strip()}\n</session_transcript>\n\n"
            f"<debrief_report>\n{report.strip()}\n</debrief_report>\n\n<task>\nWrite the memory block.\n</task>")
