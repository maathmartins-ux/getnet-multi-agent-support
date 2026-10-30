"""Input/output guardrails (BR-002). Pure functions: no LLM, no I/O, fully unit-testable.

Input policy
- card numbers (13–19 digits, Luhn-valid)  -> masked, flag `pii_card`
- CPF (xxx.xxx.xxx-xx)                     -> masked, flag `pii_cpf`
- prompt injection patterns                 -> blocked, flag `prompt_injection`
- unsafe content                            -> blocked, flag `unsafe_content`
- oversized message                         -> blocked, flag `too_long`
Output policy
- any CPF/card that leaked into the answer  -> masked, flag `output_pii`
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
CARD_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")

INJECTION_PATTERNS = [
    r"ignore (all |the |any )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (all |the )?(previous|prior|above) (instructions|rules)",
    r"(reveal|show|print|repeat) (your|the) (system )?(prompt|instructions)",
    r"you are now (a|an|the) ",
    r"\bjailbreak\b",
    r"\bDAN mode\b",
    r"ignore (as |todas as )?(instru[cç][oõ]es|regras) (anteriores|acima)",
    r"desconsidere (as |todas as )?(instru[cç][oõ]es|regras)",
    r"(mostre|revele|imprima) (o |seu |sua )?(prompt|instru[cç][oõ]es) (do sistema|de sistema)",
]
UNSAFE_PATTERNS = [
    r"\b(bomb|bomba|explosiv\w*)\b",
    r"\bhow to (kill|murder|poison)\b",
    r"\bcomo (matar|envenenar)\b",
    r"\b(suicid\w*|self[- ]harm|me matar)\b",
    r"\b(clonar|clone|skimm\w*) (cart[aã]o|card)s?\b",
    r"\b(lavagem de dinheiro|money laundering)\b",
]
_INJECTION = [re.compile(p, re.I) for p in INJECTION_PATTERNS]
_UNSAFE = [re.compile(p, re.I) for p in UNSAFE_PATTERNS]

BLOCK_MESSAGES = {
    "pt": {
        "prompt_injection": "Não posso atender a esse pedido. Posso ajudar com dúvidas sobre produtos, serviços e sua conta Getnet.",
        "unsafe_content": "Não posso ajudar com esse tipo de solicitação. Se precisar de suporte sobre produtos ou sua conta Getnet, estou à disposição.",
        "too_long": "Sua mensagem é muito longa. Resuma o pedido em até 4000 caracteres, por favor.",
    },
    "en": {
        "prompt_injection": "I cannot comply with that request. I can help with questions about Getnet products, services and your account.",
        "unsafe_content": "I cannot help with that type of request. If you need support about Getnet products or your account, I am here.",
        "too_long": "Your message is too long. Please summarise it in up to 4000 characters.",
    },
}
PII_WARNING = {
    "pt": "Por segurança, nunca compartilhe número completo de cartão ou CPF neste canal; os dados foram ocultados.",
    "en": "For your safety, never share full card numbers or CPF in this channel; the data has been masked.",
}


def luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _mask_cards(text: str) -> tuple[str, bool]:
    found = False

    def repl(m: re.Match[str]) -> str:
        nonlocal found
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            found = True
            return f"[CARD ****{digits[-4:]}]"
        return m.group(0)

    return CARD_RE.sub(repl, text), found


def _mask_cpf(text: str) -> tuple[str, bool]:
    new = CPF_RE.sub("[CPF MASKED]", text)
    return new, new != text


@dataclass
class InputCheck:
    text: str  # sanitised text that downstream agents receive
    flags: list[str] = field(default_factory=list)
    blocked: bool = False
    masked: bool = False
    block_reason: str | None = None

    def block_message(self, language: str) -> str:
        return BLOCK_MESSAGES.get(language, BLOCK_MESSAGES["pt"])[self.block_reason or "unsafe_content"]


def check_input(text: str, *, max_chars: int = 4000) -> InputCheck:
    if len(text) > max_chars:
        return InputCheck(text=text[:max_chars], flags=["too_long"], blocked=True, block_reason="too_long")
    for pat in _INJECTION:
        if pat.search(text):
            return InputCheck(text=text, flags=["prompt_injection"], blocked=True, block_reason="prompt_injection")
    for pat in _UNSAFE:
        if pat.search(text):
            return InputCheck(text=text, flags=["unsafe_content"], blocked=True, block_reason="unsafe_content")
    flags: list[str] = []
    text, card = _mask_cards(text)
    if card:
        flags.append("pii_card")
    text, cpf = _mask_cpf(text)
    if cpf:
        flags.append("pii_cpf")
    return InputCheck(text=text, flags=flags, masked=bool(flags))


def check_output(text: str) -> tuple[str, list[str]]:
    flags: list[str] = []
    text, card = _mask_cards(text)
    text, cpf = _mask_cpf(text)
    if card or cpf:
        flags.append("output_pii")
    return text, flags
