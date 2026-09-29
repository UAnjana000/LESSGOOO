"""Input checks and answer policy (spec 5.7 step 1 and 'Policy rules for answers'). No LLM involved."""

from __future__ import annotations

import re
from dataclasses import dataclass

INJECTION_PATTERNS = [
    r"ignore (all |any )?(the )?(previous|prior|above) (instructions|rules|prompts?)",
    r"disregard (the )?(system|previous|above)",
    r"(reveal|show|print|repeat) (me )?(your|the) (system )?(prompt|instructions)",
    r"you are now\b", r"\bact as\b", r"\bjailbreak\b", r"developer mode", r"\bDAN\b",
    r"pretend (to be|you are)", r"new instructions?:", r"</?system>",
    r"पिछले निर्देश(ों)? को (अनदेखा|नज़रअंदाज़)", r"मागील सूचना दुर्लक्ष",
]
ABUSE_TERMS = [
    "fuck", "shit", "bastard", "bitch", "chutiya", "madarchod", "behenchod", "randi", "harami",
    "चूतिया", "मादरचोद", "भेनचोद", "हरामी",
]
OPINION_PATTERNS = [
    r"what would (dr\.?\s*)?(b\.?\s*r\.?\s*)?(babasaheb\s+)?ambedkar (think|say|feel|do)",
    r"would (dr\.?\s*)?(babasaheb\s+)?ambedkar (support|oppose|vote|endorse|like|approve)",
    r"(ambedkar|babasaheb).{0,40}(opinion|view|think).{0,40}(today|current|modern|present|now)",
    r"(अंबेडकर|आंबेडकर|बाबासाहेब).{0,40}(आज|वर्तमान|मौजूदा|सध्या).{0,40}(सोच|मत|समर्थन|पाठिंबा)",
    r"(अंबेडकर|आंबेडकर|बाबासाहेब).{0,30}(किसका|कोणाला|किसे) (समर्थन|पाठिंबा)",
]
CURRENT_POLITICS = [
    "bjp", "congress party", "inc ", "aap", "bsp", "shiv sena", "ncp", "rss", "modi", "rahul gandhi",
    "kejriwal", "mayawati", "amit shah", "election 20", "current government", "today's government",
    "भाजपा", "कांग्रेस", "मोदी", "शिवसेना", "आप पार्टी",
]


@dataclass
class PolicyResult:
    allowed: bool
    outcome: str  # ok | rejected_input | refused
    reason: str | None = None


def check_input(question: str, max_chars: int) -> PolicyResult:
    q = question.strip()
    if not q:
        return PolicyResult(False, "rejected_input", "empty")
    if len(q) > max_chars:
        return PolicyResult(False, "rejected_input", "too_long")
    low = q.lower()
    if any(re.search(p, low, flags=re.IGNORECASE) for p in INJECTION_PATTERNS):
        return PolicyResult(False, "rejected_input", "prompt_injection")
    if any(re.search(rf"(?<!\w){re.escape(t)}(?!\w)", low) for t in ABUSE_TERMS):
        return PolicyResult(False, "rejected_input", "abuse")
    return PolicyResult(True, "ok")


def is_opinion_bait(question: str) -> bool:
    low = question.lower()
    if any(re.search(p, low, flags=re.IGNORECASE) for p in OPINION_PATTERNS):
        return True
    mentions_him = any(n in low for n in ("ambedkar", "babasaheb", "अंबेडकर", "आंबेडकर", "बाबासाहेब"))
    wants_view = any(w in low for w in ("think", "support", "opinion", "vote", "view of", "सोच", "समर्थन",
                                        "पाठिंबा", "मत "))
    return mentions_him and wants_view and any(p in low for p in CURRENT_POLITICS)


MESSAGES = {
    "refused": {
        "en": "The archive cannot say what Dr. Ambedkar would think about present-day parties, people or events. "
              "Here is related material from the archive that you can read for yourself.",
        "hi": "संग्रह यह नहीं बता सकता कि डॉ. आंबेडकर आज के दलों, व्यक्तियों या घटनाओं के बारे में क्या सोचते। "
              "आप स्वयं पढ़ सकें, इसके लिए संग्रह की संबंधित सामग्री यहाँ है।",
        "mr": "आजच्या पक्ष, व्यक्ती किंवा घटनांबद्दल डॉ. आंबेडकरांनी काय विचार केला असता हे संग्रह सांगू शकत नाही. "
              "तुम्ही स्वतः वाचू शकाल असे संबंधित साहित्य येथे आहे.",
    },
    "insufficient": {
        "en": "The archive does not contain enough to answer this. These are the closest items to browse.",
        "hi": "इस प्रश्न का उत्तर देने के लिए संग्रह में पर्याप्त सामग्री नहीं है। ये सबसे निकट की सामग्री हैं।",
        "mr": "या प्रश्नाचे उत्तर देण्यासाठी संग्रहात पुरेसे साहित्य नाही. ही सर्वात जवळची सामग्री आहे.",
    },
    "rejected_input": {
        "en": "This question cannot be answered here. Please ask about material in the archive.",
        "hi": "इस प्रश्न का उत्तर यहाँ नहीं दिया जा सकता। कृपया संग्रह की सामग्री के बारे में पूछें।",
        "mr": "या प्रश्नाचे उत्तर येथे देता येत नाही. कृपया संग्रहातील साहित्याबद्दल विचारा.",
    },
    "too_long": {
        "en": "This question is too long. Please shorten it to {max_chars} characters or fewer and ask again.",
        "hi": "यह प्रश्न बहुत लंबा है। कृपया इसे {max_chars} अक्षरों या उससे कम में छोटा करके फिर से पूछें।",
        "mr": "हा प्रश्न खूप मोठा आहे. कृपया तो {max_chars} अक्षरांपर्यंत लहान करून पुन्हा विचारा.",
    },
    "local_only": {
        "en": "The rights terms of these passages do not allow sending them to the answer model, so no answer was "
              "written. You can read the closest approved passages here.",
        "hi": "इन अंशों की अधिकार-शर्तें इन्हें उत्तर मॉडल को भेजने की अनुमति नहीं देतीं, इसलिए उत्तर नहीं लिखा गया। "
              "आप सबसे निकट के स्वीकृत अंश यहाँ पढ़ सकते हैं।",
        "mr": "या उताऱ्यांच्या हक्क-अटी त्यांना उत्तर मॉडेलकडे पाठवण्याची परवानगी देत नाहीत, म्हणून उत्तर लिहिले "
              "गेले नाही. सर्वात जवळचे मंजूर उतारे तुम्ही येथे वाचू शकता.",
    },
    "extractive": {
        "en": "No answer model is connected on this server, so no answer was written. "
              "These approved passages match your question most closely.",
        "hi": "इस सर्वर पर उत्तर मॉडल जुड़ा नहीं है, इसलिए उत्तर नहीं लिखा गया। ये स्वीकृत अंश आपके प्रश्न से सबसे अधिक मेल खाते हैं।",
        "mr": "या सर्व्हरवर उत्तर मॉडेल जोडलेले नाही, म्हणून उत्तर लिहिले गेले नाही. हे मंजूर उतारे तुमच्या प्रश्नाशी सर्वाधिक जुळतात.",
    },
}

ANSWER_LABEL = {
    "en": "AI-generated answer from archive sources",
    "hi": "संग्रह स्रोतों से AI द्वारा बनाया गया उत्तर",
    "mr": "संग्रह स्रोतांवरून AI ने तयार केलेले उत्तर",
}
