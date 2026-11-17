"""Zero-latency local turn classifier (<1 ms, no network, no LLM).

v16 adds `turn_readiness()` — context setup vs complete question — used by the server's same-speaker turn
accumulation to decide between a fast trigger and a 1.8 s "they are still talking" hold.

Active listening policy:
  * The user's own microphone ("me") NEVER triggers an answer.
  * Any remote turn ("them") that ended with a pause and has MIN_WORDS (4) or more words triggers an answer —
    questions, statements, scenarios, opinions alike. The prompt tells the model to react appropriately
    when it is not a question.
  * Shorter remote turns still trigger when they look like a question or a request (so "Why?" or
    "Tell me more." are not lost); pure acknowledgements ("ok", "thanks", "mm-hmm") are ignored.
"""
from __future__ import annotations

import re

MIN_WORDS = 3   # v19: ANY remote utterance with 3+ words answers - no "?" needed, Spanish or English

_INTERROGATIVE_START = re.compile(
    r"^\s*(who|what|when|where|why|how|which|can|could|would|should|do|does|did|is|are|was|were|"
    r"have|has|had|will|tell|walk|explain|describe|give|share|talk|any|qué|que|quién|quien|cuál|cual|"
    r"cómo|como|cuándo|cuando|dónde|donde|por qué|porque|puedes|podrías|podrias|puede|podría|podria|"
    r"explica|explícame|cuéntame|cuentame|platícanos|platicanos|háblanos|hablanos|dime)\b",
    re.IGNORECASE,
)
_REQUEST = re.compile(
    r"\b(walk (us|me) through|tell (us|me)|explain|your (experience|take|view|thoughts|approach|opinion)|"
    r"how (did|do|would) you|what('s| is) your|can you|could you|would you|curious|thoughts on|how about|"
    r"what about|recommend|suggest|cuéntanos|cuentanos|cuál es tu|cual es tu|qué opinas|que opinas|"
    r"nos puedes|me puedes|podrías|podrias|qué recomiendas|que recomiendas|más detalle|mas detalle|more detail)\b",
    re.IGNORECASE,
)
# Isolated 1-2 word fillers / acknowledgements (the ONLY thing that never triggers).
_ACK_WORD = (r"(?:ok(?:ay)?|yes|yeah|yep|no|nope|sure|right|great|good|perfect|thanks?|thank you|got it|mm+-?hm+|uh-?huh|"
             r"alright|cool|nice|exactly|correct|fine|understood|"
             r"sí|si|vale|claro|perfecto|gracias|bien|listo|entendido|bueno|ajá|aja|okey|exacto|correcto|muy bien|"
             r"de acuerdo|va|sale|órale|orale|ándale|andale|mhm|eh|em|este|pues)")
_ACK_ONLY = re.compile(rf"^\s*{_ACK_WORD}(?:[,\s]+{_ACK_WORD})?[.!?…\s]*$", re.IGNORECASE)

# v19: conversational Mexican / LatAm Spanish interview prompts (no "?" and no question word at the start)
ES_FAST_TRIGGERS = ['qué', 'que ', 'cómo', 'como ', 'cuál', 'cual ', 'cuándo', 'cuando', 'dónde', 'donde', 'por qué',
                    'porque', 'quién', 'platícame', 'platicame', 'cuéntame', 'cuentame', 'háblame', 'hablame', 'dime',
                    'explícame', 'explicame', 'describe', 'menciona', 'comparte', 'tendrás', 'tienes experiencia',
                    'has trabajado', 'cómo manejas', 'qué harías', 'imaginemos', 'supongamos',
                    'me gustaría entender', 'me gustaria entender', 'me gustaría saber', 'quisiera saber', 'nos puedes',
                    'me puedes', 'podrías', 'podrias', 'platícanos', 'platicanos', 'cuéntanos', 'cuentanos', 'háblanos',
                    'hablanos', 'y en la parte de', 'en cuanto a', 'respecto a', 'hablando de']
_ES_FAST_RE = re.compile(r"(?<![\wáéíóúñ])(?:" + "|".join(re.escape(t.strip()) for t in sorted(set(ES_FAST_TRIGGERS), key=len, reverse=True)) + r")(?![\wáéíóúñ])", re.IGNORECASE)
_EN_FAST_RE = re.compile(r"\b(tell me|walk me|talk me|explain|describe|give me|share|how (did|do|would|have|will) you|"
                         r"what (would|did|do|will|about) you|what('s| is| was| are) your|why (did|do|would)|when (did|have) you|"
                         r"where (did|have) you|could you|can you|would you|have you|do you have|imagine|suppose|let's say|"
                         r"in your experience|your (experience|approach|view|take|opinion|thoughts))\b", re.IGNORECASE)


def has_fast_trigger(text: str) -> bool:
    """Spanish / English conversational prompt cue anywhere in the utterance -> answer at the fast debounce."""
    t = (text or "")
    return bool(_ES_FAST_RE.search(t) or _EN_FAST_RE.search(t))


# ---- v16: context-setup vs complete-question endpointing ------------------------------------------
# A remote segment that ends on one of these reads as "still setting up the question" -> hold ~1.8 s.
_SETUP_TAIL = re.compile(
    r"(?:\b(and|or|but|so|because|since|while|when|whenever|if|although|though|where|which|that|who|whom|whose|"
    r"with|without|for|to|of|from|in|on|at|by|into|about|between|than|then|as|like|plus|also|basically|"
    r"when we|in that role|in that case|at that point|at the time|the thing is|what I mean is|for example|"
    r"for instance|such as|I mean|you know|kind of|sort of|"
    r"y|o|pero|porque|ya que|mientras|cuando|si|aunque|donde|que|quien|con|sin|para|de|desde|en|sobre|entre|"
    r"entonces|o sea|es decir|por ejemplo|digamos|en ese rol|en ese caso|en ese momento|en esa época|lo que pasa es)"
    r"|[,;:\-–—(]|\.\.\.|…)\s*$",
    re.IGNORECASE,
)
# A direct prompt anywhere in the LAST sentence makes the turn a complete question (fast trigger).
_DIRECT_PROMPT = re.compile(
    r"\b(tell (me|us)( a bit| a little| more)? about|how (did|do|would|have|will) you|what (would|did|do|will) you|"
    r"walk (me|us) through|why (did|do|would|didn't|wouldn't) you|what('s| is| was| are) (your|the)|can you|could you|"
    r"would you|give (me|us) an example|describe|explain|in your (view|opinion|experience)|what do you think|"
    r"what are your thoughts|how about|what about|"
    r"cu[eé]nta(me|nos)|c[oó]mo (manejaste|lo manejaste|resolviste|lo resolviste|abordaste|lo hiciste|harías|lo harías)|"
    r"qu[eé] (har[ií]as|hiciste|opinas|piensas)|por qu[eé] (decidiste|elegiste|no)|pl[aá]t[ií]ca(me|nos)|"
    r"h[aá]bla(me|nos) de|dame un ejemplo|descr[ií]be(me|nos)?|expl[ií]ca(me|nos)?|cu[aá]l (es|fue|ser[ií]a) (tu|su)|"
    r"me puedes|nos puedes|podr[ií]as)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def last_sentence(text: str) -> str:
    parts = [p for p in _SENTENCE_SPLIT.split((text or "").strip()) if p.strip()]
    return parts[-1] if parts else (text or "").strip()


def ends_with_connector(text: str) -> bool:
    t = (text or "").rstrip()
    if not t:
        return False
    t = t.rstrip(".")  # Deepgram smart_format may add a period after a dangling "and."
    return bool(_SETUP_TAIL.search(t))


def turn_readiness(text: str) -> str:
    """'question' -> the accumulated remote turn clearly ends with a question or a direct prompt: answer now
    (fast trigger, the STT endpoint pause ~0.8-0.9 s already elapsed).
    'setup'    -> it ends on a statement / connector / incomplete clause: the speaker is probably still giving
    background; hold ~1.8 s for more before answering."""
    t = (text or "").strip()
    if not t:
        return "setup"
    if ends_with_connector(t):
        return "setup"
    tail = last_sentence(t)
    if tail.rstrip().endswith("?") or "¿" in tail:
        return "question"
    if _DIRECT_PROMPT.search(tail) or has_fast_trigger(tail):
        return "question"
    if _INTERROGATIVE_START.search(tail) and len(tail.split()) >= 3:
        return "question"
    return "setup"


def is_question(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if "?" in t or "¿" in t:
        return True
    return bool(_INTERROGATIVE_START.search(t) or _REQUEST.search(t) or has_fast_trigger(t))


def needs_answer(text: str, channel: str = "them") -> bool:
    """True when a finished remote turn should trigger generation. Never for the user's own mic."""
    if channel != "them":
        return False
    t = (text or "").strip()
    if not t or _ACK_ONLY.match(t):
        return False
    if len(t.split()) >= MIN_WORDS:
        return True
    return is_question(t)


def skip_reason(text: str, channel: str = "them") -> str | None:
    """Why a finished utterance would NOT trigger (for the HUD / log); None when it triggers."""
    if channel != "them":
        return "mic channel never triggers (switch to 📱 Llamada externa to answer what the mic hears)"
    t = (text or "").strip()
    if not t:
        return "empty"
    if _ACK_ONLY.match(t):
        return f"acknowledgement only ({t[:20]!r})"
    if len(t.split()) < MIN_WORDS and not is_question(t):
        return f"too short ({len(t.split())} words, need {MIN_WORDS}+ or a question)"
    return None


def trigger_class(text: str) -> str:
    """v19 universal auto-trigger classes for a finished remote utterance (3+ words always answer):
      'fast'  -> ends with ? / ¿…? or contains a Spanish/English conversational prompt cue: answer at the fast debounce (650 ms)
      'plain' -> any other 3+-word statement: answer at the normal debounce (800 ms); if they keep talking the
                 card is replaced in place (v16), so waiting longer never helps."""
    t = (text or "").strip()
    if not t:
        return "plain"
    tail = last_sentence(t)
    if tail.rstrip().endswith("?") or "¿" in tail or has_fast_trigger(tail) or has_fast_trigger(t):
        return "fast"
    return "plain"
