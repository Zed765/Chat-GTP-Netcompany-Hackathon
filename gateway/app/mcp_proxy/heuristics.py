"""Layer 1 of injection detection: weighted signals found with patterns, in English and Greek.

Each signal answers one question about a text: who is addressed, what is demanded, where
data is sent, whether secrecy or prior approval is claimed, whether a role or the system is
impersonated. Most are weak evidence alone: a manual tells its reader to "send the form to"
an address, a memo says "from now on you must" use the portal. Content is flagged when the
signals add up, for example a note to the assistant that demands client records, or a
request for secrecy inside a hidden element.

Patterns run on a folded copy of the text (lower case, no accents, invisible characters
removed), so the Greek ones are written without accents and with "σ" for a final "ς".

The text is untrusted, so matching takes time linear in its length. Markup and encoded runs
are found with RE2. The signal patterns need Unicode word boundaries and lookaheads, which
RE2 does not have, so they use `re` with every repetition bounded: a match attempt can look
at a few hundred characters at most, wherever it starts.
"""

import base64
import binascii
import re
import unicodedata
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import cast

import re2

FLAG_THRESHOLD = 0.6
EVIDENCE_CHARS = 400

# Zero-width spaces and joiners, the soft hyphen, the byte order mark and bidi controls.
_ZERO_WIDTH = frozenset(
    map(
        chr,
        (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E),
    )
)
# Unicode tag characters mirror ASCII invisibly and are used to smuggle text past a reader.
_TAG_BLOCK = range(0xE0020, 0xE007F)

MAX_REPEAT = 64


def bounded(pattern: str) -> str:
    """The pattern with each `+` and `*` turned into a repetition of at most `MAX_REPEAT`.

    Patterns below are written with `+` and `*` because that reads well; this is what keeps
    any one of them from scanning ahead without limit.
    """
    out: list[str] = []
    in_class = False
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            out.append(pattern[index : index + 2])
            index += 2
            continue
        if in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif char in "+*":
            char = f"{{{int(char == '+')},{MAX_REPEAT}}}"
        out.append(char)
        index += 1
    return "".join(out)


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(bounded(pattern), re.MULTILINE)


_ADDRESS = r"(?:<[a-z_]+_\d+>|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|https?://\S+)"
_SENTENCE_START = r"(?:^|[^\w\s]\s*)"
# Any character of the same sentence: a full stop inside an address or a number does not end it.
_SAME_SENTENCE = r"(?:[^.]|\.(?=\w))"

_EN_OVERRIDE_VERB = (
    r"(?:ignore|disregard|forget|override|bypass|do\s+not\s+follow|don'?t\s+follow"
    r"|stop\s+following|pay\s+no\s+attention\s+to)"
)
_EN_OVERRIDE_FILLER = (
    r"(?:all|any|every|each|of|the|your|my|our|these|those|previous|prior|above|earlier"
    r"|preceding|initial|original|old|existing|current|system|safety|other|and)"
)
_EN_OVERRIDE_NOUN = (
    r"(?:instructions?|prompts?|rules|directives|guidelines|guardrails|commands|restrictions)"
)
_EL_OVERRIDE_VERB = (
    r"(?:αγνοησ(?:ε|τε|ετε)|παραβλεψ(?:ε|τε|ετε)|ξεχασ(?:ε|τε)|ξεχνα|παρακαμψ(?:ε|τε)"
    r"|μην?\s+(?:ακολουθ(?:εισ|ησεισ|ειτε|ησετε)|λαβ(?:εισ|ετε)\s+υποψη|τηρ(?:εισ|ησεισ)))"
)
_EL_OVERRIDE_FILLER = (
    r"(?:ολεσ|ολουσ|τισ|τουσ|των|προηγουμενεσ|προηγουμενουσ|προηγουμενων|παραπανω|αρχικεσ"
    r"|παλιεσ|παλαιοτερεσ|προγενεστερεσ|υπολοιπεσ|αλλεσ|και)"
)
_EL_OVERRIDE_NOUN = (
    r"(?:οδηγιεσ|οδηγιων|εντολεσ|εντολων|κανονεσ|κανονων|υποδειξεισ|προτροπεσ|περιορισμουσ)"
)
_OVERRIDE = _compile(
    rf"{_EN_OVERRIDE_VERB}\s+(?:{_EN_OVERRIDE_FILLER}\s+){{0,4}}{_EN_OVERRIDE_NOUN}"
    rf"|(?:ignore|disregard|forget)\s+(?:everything|anything|all)\s+"
    rf"(?:above|before|previously|you\s+(?:were|have\s+been)\s+told)"
    rf"|{_EL_OVERRIDE_VERB}\s+(?:{_EL_OVERRIDE_FILLER}\s+){{0,4}}{_EL_OVERRIDE_NOUN}"
    rf"(?:\s+(?:σου|σασ|του\s+συστηματοσ|ασφαλειασ))?"
    # "Forget what you have been told": aimed at the model, unlike "forget what I said".
    r"|(?:ξεχασε|αγνοησε|παραβλεψε)\s+(?:ο,?τι|οσα|ολα\s+οσα)\s+σου\s+"
    r"(?:εχουν\s+πει|ειπαν|εχει\s+ειπωθει|εχουν\s+ζητησει)"
)
# What separates "ignore your instructions" (aimed at the model) from "ignore the previous
# instructions" (which a memo also says to its readers).
_OVERRIDE_AIMED_AT_MODEL = re.compile(
    r"\b(?:all|any|every|everything|anything|your|above|system|safety"
    r"|ολεσ|ολουσ|σου|σασ|παραπανω|συστηματοσ|ασφαλειασ)\b"
)

# Unambiguous names for an AI assistant. "Agent" and "model" alone also label people and
# products, so they count only inside "note to the model:" and the like.
_EN_AI = (
    r"(?:(?:ai|digital|virtual)\s+(?:assistant|agent|model|chatbot)|chatbot|copilot"
    r"|language\s+model|llm"
    # "Assistant manager" and "assistant to the director" are people.
    r"|assistant(?!\s+(?:manager|director|professor|editor|coach|secretary|accountant|to\s+the)))"
)
_EN_SEND = (
    r"(?:send|forward|email|e-mail|mail|post|upload|transmit|deliver|export|copy|submit|leak"
    r"|exfiltrate|confirm|report)"
)
# Verb stems: whatever follows in the pattern takes up the ending.
_EL_SEND = r"(?:στειλ|αποστειλ|προωθησ|κοινοποιησ|ανεβασ|εξαγαγ|εξαγ|μεταφερ)"
_EN_QUIETLY = r"(?:silently|quietly|secretly|covertly|discreetly)"
_EL_QUIETLY = r"(?:αθορυβα|κρυφα|σιωπηλα|μυστικα|διακριτικα)"
_EN_SENSITIVE = (
    r"(?:(?:clients?|customers?|users?|employees?|patients?|accounts?)(?:'s|s')?\s+"
    r"(?:records?|data|details|list|names?|information|files?|contacts?|phone|addresses|iban)"
    r"|contact\s+details|\biban\b|tax\s+(?:number|id)|\bafm\b|passwords?|credentials"
    r"|api\s+keys?|secret\s+keys?|access\s+tokens?|credit\s+card|(?:conversation|chat)\s+history"
    r"|(?:hidden|secret|internal|confidential|private)\s+"
    r"(?:configuration|settings|notes?|data|files?|records?|information))"
)
_EL_SENSITIVE = (
    r"(?:εγγραφ\w+\s+(?:των\s+)?πελατ\w+|στοιχεια\s+επικοινωνιασ"
    r"|(?:στοιχεια|δεδομενα|λιστα|ονομα\w*|τηλεφων\w+)\s+(?:και\s+\w+\s+\w+\s+)?"
    r"(?:ολων\s+)?(?:των?\s+|του\s+|τησ\s+)?πελατ\w+"
    r"|\biban\b|\bαφμ\b|κωδικ\w+\s+προσβασησ|κλειδια\s+api|μυστικ\w+\s+κλειδι\w+"
    r"|ιστορικο\s+(?:τησ\s+)?συνομιλιασ|(?:κρυφ\w+|εμπιστευτικ\w+|εσωτερικ\w+|απορρητ\w+)\s+"
    r"(?:ρυθμισεισ|σημειωσεισ|δεδομενα|αρχεια|στοιχεια|πληροφοριεσ))"
)


def _signal(
    technique: str, weight: float, *alternatives: str
) -> tuple[str, float, re.Pattern[str]]:
    return technique, weight, _compile("|".join(alternatives))


_PATTERNS = (
    # Who is addressed: the assistant by name, in a labelled note, or as "the assistant must".
    _signal(
        "addressed_to_assistant",
        0.35,
        rf"{_SENTENCE_START}(?:(?:dear|attention|hey|hello|hi)\s+)?{_EN_AI}\b[^.\n:,]{{0,40}}[:,]",
        rf"{_SENTENCE_START}(?:(?:important|urgent|special)\s+)?"
        r"(?:note|message|notice|instructions?)\s+(?:to|for)\s+(?:the\s+)?"
        rf"(?:{_EN_AI}|agent|model|ai|bot)\b[^.\n:,]{{0,40}}[:,]",
        r"(?:if|when|since)\s+you\s+are\s+an?\s+(?:ai|llm|assistant|language\s+model|agent)\b",
        rf"{_SENTENCE_START}(?:(?:αγαπητε|προσοχη)\s+)?(?:(?:ψηφιακε|εικονικε)\s+)?"
        r"βοηθ(?:ε|ο|οσ)\b[^.\n:,]{0,40}[:,]",
        rf"{_SENTENCE_START}(?:(?:σημαντικη|επειγουσα)\s+)?"
        r"(?:σημειωση|μηνυμα|οδηγια|οδηγιεσ|εντολη|ειδοποιηση)\s+(?:για|προσ)\s+(?:τον|το)\s+"
        r"(?:(?:ψηφιακο|εικονικο)\s+)?(?:βοηθο|μοντελο|πρακτορα)\b[^.\n:,]{0,40}[:,]",
        r"αν\s+εισαι\s+(?:βοηθοσ|μοντελο|τεχνητη\s+νοημοσυνη|πρακτορασ)",
    ),
    # "The assistant must ..." is also said of people, so it weighs less.
    _signal(
        "addressed_to_assistant",
        0.25,
        rf"\bthe\s+{_EN_AI}\s+(?:must|should|shall|has\s+to|needs?\s+to|is\s+required\s+to)\b",
        r"\b(?:ο\s+βοηθοσ|το\s+μοντελο)\s+(?:οφειλει|πρεπει|υποχρεουται|καλειται)\s+να\b",
    ),
    # A line that poses as the system: "SYSTEM: maintenance mode is active".
    _signal(
        "system_spoof",
        0.25,
        rf"{_SENTENCE_START}(?:system|συστημα|μηνυμα\s+συστηματοσ)\s*:",
    ),
    _signal(
        "role_markup",
        0.5,
        r"<\|(?:im_start|im_end|system|user|assistant|endoftext)\|>|\[/?inst\]|<<sys>>",
        r"</?system>|^\s*#{1,3}\s*system(?:\s+(?:prompt|message))?\s*(?::\s*)?$",
        r"^\s*system\s+(?:message|prompt|override|notice)\s*:|begin\s+system\s+prompt",
    ),
    # A change of task or role: "new instructions from ...:", "you are now", "stop summarising".
    _signal(
        "new_instructions",
        0.25,
        r"new\s+(?:instructions?|task|rules|orders)(?:\s*[:.-]|\b[^.:\n]{1,40}:)",
        r"your\s+(?:new|real|actual|true)\s+(?:task|goal|job|role|mission|instructions?|objective)",
        r"from\s+now\s+on,?\s+you|you\s+are\s+now\b|pretend\s+(?:to\s+be|you\s+are)",
        r"act\s+as\s+(?:if|an?\b|the)",
        r"stop\s+(?:summari[sz]ing|translating|answering|what\s+you\s+are\s+doing)",
        r"νεεσ\s+οδηγιεσ|νεα\s+(?:εντολη|οδηγια)|εισαι\s+πλεον|προσποιησου",
        r"συμπεριφερσου\s+(?:ωσ|σαν)|σταματα\s+(?:την\s+περιληψη|ο,?τι\s+κανεισ)",
        r"(?:ο\s+(?:νεοσ|πραγματικοσ)|η\s+(?:νεα|πραγματικη))\s+σου\s+"
        r"(?:ρολοσ|στοχοσ|αποστολη|εργασια|εντολη)",
        r"απο\s+(?:εδω\s+και\s+περα|τωρα\s+και\s+στο\s+εξησ),?\s+(?:θα\s+)?"
        r"(?:εισαι|πρεπει|\w{3,30}(?:εισ|ασ|σαι)\b)",
    ),
    # A role without limits: "developer mode", "with no restrictions".
    _signal(
        "unrestricted_role",
        0.25,
        r"(?:developer|jailbreak|dan|god|unrestricted)\s+mode",
        r"(?:with\s+no|without(?:\s+any)?|free\s+(?:of|from)(?:\s+all)?|no\s+longer\s+bound\s+by)"
        r"\s+(?:restrictions?|limits|limitations|filters?|guardrails|rules|censorship)",
        r"χωρισ\s+(?:κανεναν?\s+|καμια\s+)?(?:περιορισμ\w+|φιλτρ\w+|κανον\w+|λογοκρισια)",
        r"λειτουργια\s+προγραμματιστη",
    ),
    # Where data is sent: an address to send to, or a recipient named for a tool.
    _signal(
        "exfiltration",
        0.25,
        rf"\b{_EN_SEND}\b[^.]{{0,120}}?\b(?:to|at)\s+{_ADDRESS}",
        rf"\brecipient\b[^.\n]{{0,20}}?{_ADDRESS}",
        rf"\b{_EL_SEND}[^.]{{0,120}}?\b(?:στο|στη|στην|στον|προσ)\s+(?:το\s+|τη\s+|την\s+|τον\s+)?"
        rf"(?:email\s+|e-mail\s+|διευθυνση\s+)?{_ADDRESS}",
        rf"\bπαραληπτ[^.\n]{{0,30}}?{_ADDRESS}",
    ),
    # A link left open for data to be appended: "...?data= followed by the client's name".
    _signal("data_carrying_link", 0.45, r"https?://\S{1,200}?[?&][\w.-]{1,40}=(?=[\s<\"']|$)"),
    # What is demanded of client records, credentials, hidden settings or the conversation:
    # to hand them over, or to change them.
    _signal(
        "sensitive_data_demand",
        0.3,
        r"\b(?:reveal|show|print|display|list|export|dump|send|forward|email|include|attach|put"
        r"|copy|append|output|disclose|give|provide|share|leak|collect|find|retrieve|fetch"
        r"|look\s+up|update|change|modify|replace|overwrite|delete)(?:s|ing)?\b"
        rf"[^.]{{0,80}}?\b{_EN_SENSITIVE}",
        rf"followed\s+by[^.]{{0,60}}?\b{_EN_SENSITIVE}",
        r"\b(?:εμφανισ|τυπωσ|τυπων|δειξ|αποκαλυψ|στειλ|αποστειλ|προωθησ|εξαγαγ|εξαγ|συμπεριλαβ"
        r"|επισυναψ|αντιγραψ|δωσ|βαλ|κοινοποιησ|βρεσ|βρειτε|αναζητησ|ανακτησ"
        r"|ενημερωσ|αλλαξ|τροποποιησ|αντικαταστησ|διαγραψ)"
        rf"[^.]{{0,80}}?\b{_EL_SENSITIVE}",
        rf"ακολουθουμεν\w+\s+απο[^.]{{0,60}}?\b{_EL_SENSITIVE}",
    ),
    # A claim that someone with authority already agreed.
    _signal(
        "authority_claim",
        0.25,
        r"the\s+user\s+has\s+(?:already\s+)?(?:pre-?approved|approved|authori[sz]ed|consented\s+to"
        r"|agreed\s+to|allowed)|\bpre-?approved\b",
        r"you\s+(?:are|have\s+been)\s+(?:authori[sz]ed|permitted|cleared|allowed)\s+to",
        r"(?:from|by\s+order\s+of|on\s+behalf\s+of)\s+your\s+"
        r"(?:administrator|admin|developer|operator|owner|creator|supervisor)",
        r"no\s+(?:confirmation|approval|permission)\s+is\s+(?:needed|required)",
        r"ο\s+χρηστησ\s+εχει\s+(?:ηδη\s+)?(?:προ)?εγκρινει|εχει\s+προεγκριθει",
        r"εχεισ\s+(?:την\s+)?(?:αδεια|εξουσιοδοτηση|εγκριση)|απο\s+τον\s+διαχειριστη\s+σου",
        r"δεν\s+(?:απαιτειται|χρειαζεται)\s+(?:επιβεβαιωση|εγκριση)",
    ),
    # A tool named for the reader to call: "call the send_email tool", "using the mail tool".
    _signal(
        "tool_invocation",
        0.25,
        r"\b(?:call|use|invoke|run|execute|trigger)\s+(?:the\s+|your\s+)?[\w.-]+(?:\s+[\w.-]+)?"
        r"\s+(?:tool|function|plugin)\b",
        r"\b(?:using|via|with)\s+(?:the\s+|your\s+)?[\w.-]+\s+(?:tool|function|plugin)\b",
        r"(?:καλεσε|χρησιμοποιησε|εκτελεσε|τρεξε|ενεργοποιησε)\s+το\s+εργαλειο",
        r"\b(?:με|μεσω)\s+(?:το|του)\s+εργαλει\w+",
    ),
    # Secrecy: keep it from the user, or do it quietly.
    _signal(
        "secrecy",
        0.4,
        r"(?:do\s+not|don'?t|never|without)\s+(?:tell|inform|mention|notify|alert|reveal"
        r"|disclos|show|ask|report)(?:e|ing)?\s+(?:this\s+|it\s+|any\s+of\s+this\s+|anything\s+)?"
        r"(?:step\s+)?(?:to\s+|about\s+this\s+to\s+)?(?:the\s+)?(?:user|human|operator|anyone)",
        r"keep\s+(?:this|it)\s+(?:secret|hidden|quiet)\s+from",
        rf"\b{_EN_SEND}\b{_SAME_SENTENCE}{{0,120}}?\b{_EN_QUIETLY}\b",
        rf"\b{_EN_QUIETLY}\s+{_EN_SEND}\b",
        r"(?:μην?|χωρισ\s+να)\s+(?:το\s+)?(?:πεισ|αναφερεισ|ενημερωσεισ|αποκαλυψεισ|δειξεισ"
        r"|ρωτησεισ|ειδοποιησεισ|ζητησεισ)\s+(?:αυτο\s+)?(?:το\s+βημα\s+)?(?:τιποτα\s+)?"
        r"(?:σ?τον\s+χρηστη|απο\s+τον\s+χρηστη|επιβεβαιωση|εγκριση)",
        rf"\b{_EL_SEND}\w{{0,12}}\s+{_EL_QUIETLY}\b|\b{_EL_QUIETLY}\s+{_EL_SEND}",
    ),
    _signal(
        "prompt_leak",
        0.5,
        r"(?:reveal|print|show|repeat|output|display|share|leak|send|email|write\s+out"
        r"|tell\s+me|give\s+me)\s+(?:me\s+)?(?:all\s+)?(?:of\s+)?"
        r"(?:your\s+(?:full\s+|entire\s+|complete\s+|exact\s+|original\s+|initial\s+|hidden\s+)*"
        r"(?:system\s+prompt|system\s+message|instructions|prompt|configuration|guidelines)"
        r"|the\s+(?:full\s+|entire\s+|hidden\s+)*system\s+(?:prompt|message))",
        r"what\s+(?:are|were)\s+your\s+(?:instructions|system\s+prompt|rules)",
        r"(?:αποκαλυψε|εμφανισε|δειξε|επαναλαβε|γραψε|στειλε|πεσ\s+μου|δωσε\s+μου)\s+"
        r"(?:μου\s+)?(?:ολεσ\s+)?(?:τισ|το)\s+(?:πληρεσ\s+|αρχικ(?:εσ|ο)\s+|κρυφ(?:εσ|ο)\s+)*"
        r"(?:οδηγιεσ\s+(?:σου|του\s+συστηματοσ)|(?:μηνυμα|prompt)\s+(?:του\s+)?συστηματοσ"
        r"|system\s+prompt)",
    ),
)
# What people ask of each other every day: send this there, list those records, use that
# tool. These count once something else steers the reader, never on their own.
_ORDINARY_REQUESTS = frozenset({"exfiltration", "sensitive_data_demand", "tool_invocation"})
_BELOW_THRESHOLD = FLAG_THRESHOLD - 0.05

_HIDDEN_STYLE = (
    r"display\s*:\s*none|visibility\s*:\s*hidden|color\s*:\s*(?:#fff(?:fff)?\b|white)"
    r"|(?:font-size|opacity)\s*:\s*0(?:\.0+)?(?:px|pt|em|rem|%)?\s*[;\"'}]"
)


def _linear(pattern: str) -> re.Pattern[str]:
    """Compiled by RE2, which never backtracks. It is used like an `re` pattern."""
    return cast("re.Pattern[str]", re2.compile(pattern))  # type: ignore[no-untyped-call]


_COMMENT = _linear(r"(?s)<!--.*?-->")
_HIDDEN_OPENING = _linear(rf"<([a-z][a-z0-9]*)\b[^<>]*(?:{_HIDDEN_STYLE}|\shidden\b)[^<>]*>")
_CLOSING = _linear(r"</([a-z][a-z0-9]*)\s*>")
_BASE64_RUN = _linear(r"[A-Za-z0-9+/]{32,}={0,2}")
_MIN_PRINTABLE = 0.9


@dataclass(frozen=True)
class Signal:
    technique: str
    weight: float
    start: int
    end: int


@dataclass(frozen=True)
class Scan:
    score: float
    signals: tuple[Signal, ...]

    @property
    def flagged(self) -> bool:
        return self.score >= FLAG_THRESHOLD

    @property
    def technique(self) -> str | None:
        ranked = sorted({(-s.weight, s.technique) for s in self.signals})
        return ", ".join(dict.fromkeys(name for _, name in ranked)) or None

    def evidence(self, text: str) -> str | None:
        """The span to show in the trace: the hidden element if there is one, else the signals."""
        if not self.signals:
            return None
        hidden = next((s for s in self.signals if s.technique == "hidden_text"), None)
        start = hidden.start if hidden else min(s.start for s in self.signals)
        end = hidden.end if hidden else max(s.end for s in self.signals)
        return text[start : min(end, start + EVIDENCE_CHARS)].strip()


def fold(text: str) -> tuple[str, list[int]]:
    """The folded text, and for each of its characters the index it came from."""
    chars: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        if char in _ZERO_WIDTH:
            continue
        if ord(char) in _TAG_BLOCK:
            char = chr(ord(char) - 0xE0000)
        for part in unicodedata.normalize("NFKD", char.casefold()):
            if not unicodedata.combining(part):
                chars.append("σ" if part == "ς" else part)
                origin.append(index)
    return "".join(chars), origin


def _instruction_signals(folded: str) -> list[Signal]:
    """Signals in folded text, with spans in folded coordinates."""
    signals = [
        Signal(technique, weight, match.start(), match.end())
        for technique, weight, pattern in _PATTERNS
        for match in pattern.finditer(folded)
    ]
    for match in _OVERRIDE.finditer(folded):
        phrase = match.group()
        aimed = bool(_OVERRIDE_AIMED_AT_MODEL.search(phrase)) or (
            phrase.isascii() and " the " not in phrase
        )
        signals.append(
            Signal("instruction_override", 0.7 if aimed else 0.4, match.start(), match.end())
        )
    return signals


def _hidden_spans(folded: str) -> list[tuple[int, int]]:
    """Comments, and elements styled so that a reader does not see them."""
    spans: list[tuple[int, int]] = [match.span() for match in _COMMENT.finditer(folded)]
    closings: dict[str, list[int]] = {}
    for match in _CLOSING.finditer(folded):
        closings.setdefault(match.group(1), []).append(match.end())
    for match in _HIDDEN_OPENING.finditer(folded):
        ends = closings.get(match.group(1), [])
        nearest = bisect_right(ends, match.end())
        if nearest < len(ends):
            spans.append((match.start(), ends[nearest]))
    return spans


def _hidden_with(steering: list[Signal], spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The hidden spans that hold at least one of the signals from start to end."""
    by_start = sorted(steering, key=lambda signal: signal.start)
    starts = [signal.start for signal in by_start]
    # earliest_end[i] is the earliest end among the signals that start at or after starts[i].
    earliest_end = [signal.end for signal in by_start]
    for index in range(len(earliest_end) - 2, -1, -1):
        earliest_end[index] = min(earliest_end[index], earliest_end[index + 1])
    holding = []
    for start, end in spans:
        first = bisect_left(starts, start)
        if first < len(starts) and earliest_end[first] <= end:
            holding.append((start, end))
    return holding


def _decoded_text(run: str) -> str | None:
    try:
        decoded = base64.b64decode(run + "=" * (-len(run) % 4), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    printable = sum(char.isprintable() or char.isspace() for char in decoded)
    return decoded if decoded and printable / len(decoded) >= _MIN_PRINTABLE else None


def _encoded_signals(text: str) -> list[Signal]:
    """Instructions hidden in base64: the blob's span carries what its decoded text contains."""
    signals: list[Signal] = []
    for match in _BASE64_RUN.finditer(text):
        decoded = _decoded_text(match.group().rstrip("="))
        inner = _instruction_signals(fold(decoded)[0]) if decoded else []
        if inner:
            signals.append(Signal("encoded_payload", 0.4, match.start(), match.end()))
            signals.extend(Signal(s.technique, s.weight, match.start(), match.end()) for s in inner)
    return signals


def _invisible_signal(text: str) -> Signal | None:
    """Zero-width characters inside a word, or any tag character."""
    for index, char in enumerate(text):
        smuggled = ord(char) in _TAG_BLOCK
        splits_word = (
            char in _ZERO_WIDTH
            and 0 < index < len(text) - 1
            and text[index - 1].isalpha()
            and text[index + 1].isalpha()
        )
        if smuggled or splits_word:
            return Signal("invisible_characters", 0.3, index, index + 1)
    return None


def scan(text: str) -> Scan:
    folded, origin = fold(text)
    origin.append(len(text))

    def located(signal: Signal) -> Signal:
        return Signal(signal.technique, signal.weight, origin[signal.start], origin[signal.end])

    instructions = _instruction_signals(folded)
    signals = [located(signal) for signal in instructions]
    steering = [s for s in instructions if s.technique not in _ORDINARY_REQUESTS]
    for start, end in _hidden_with(steering, _hidden_spans(folded)):
        signals.append(located(Signal("hidden_text", 0.4, start, end)))
    signals.extend(_encoded_signals(text))
    invisible = _invisible_signal(text)
    if invisible and signals:
        signals.append(invisible)

    strongest: dict[str, float] = {}
    for signal in signals:
        strongest[signal.technique] = max(strongest.get(signal.technique, 0.0), signal.weight)
    score = min(1.0, round(sum(strongest.values()), 2))
    if strongest.keys() <= _ORDINARY_REQUESTS:
        score = min(score, _BELOW_THRESHOLD)
    return Scan(score=score, signals=tuple(signals))
