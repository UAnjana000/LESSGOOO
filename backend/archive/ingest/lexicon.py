"""Small frequency lexicons for the dictionary-word-ratio signal.

These are starter lists (version lexicon-v0) of very common function words. They make the signal
meaningful for garbage detection but are NOT a full dictionary; the institution should extend them
from approved archive text before calibrating the gate.
"""

from __future__ import annotations

from functools import lru_cache

LEXICON_VERSION = "lexicon-v0"

_EN = """
a about above after again against all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have
having he her here hers herself him himself his how i if in into is it its itself just me more most my
myself no nor not now of off on once only or other our ours ourselves out over own same she should so
some such than that the their theirs them themselves then there these they this those through to too
under until up very was we were what when where which while who whom why will with would you your
yours yourself people law laws state society social rights right constitution constitutional
government public political equality liberty fraternity justice caste education democracy power man
men women country nation history religion members member assembly article articles debate speech
must may shall one two three first new great life work time world order question principle
principles duty duties citizen citizens reading room rooms library libraries book books archive
record records village villages council committee freedom labour labor economic moral morality
"""

_HI = """
का के की है हैं में से को और पर यह वह था थे थी एक भी तो ही नहीं कि जो लिए कर किया करना होता होती होते
गया गई गए अपने अपनी अपना इस उस इन उन हम आप वे सब कुछ या अब तक साथ बाद पहले दिया दी लोग लोगों समाज
सामाजिक अधिकार संविधान सरकार राज्य समानता स्वतंत्रता बंधुता न्याय शिक्षा लोकतंत्र देश राष्ट्र इतिहास
धर्म सभा सदस्य अनुच्छेद भाषण कानून नागरिक पुस्तक पुस्तकालय अभिलेख गाँव परिषद समिति श्रम आर्थिक नैतिक
"""

_MR = """
आणि आहे आहेत होते होती होता या त्या हे ते ती तो एक नाही की जे जी जो साठी करून केले केली करणे असे अशी
आपल्या आपला आपली मध्ये वर पासून पर्यंत सर्व काही किंवा आता नंतर आधी लोक लोकांना समाज सामाजिक अधिकार
संविधान सरकार राज्य समता स्वातंत्र्य बंधुता न्याय शिक्षण लोकशाही देश राष्ट्र इतिहास धर्म सभा सदस्य
कलम भाषण कायदा नागरिक पुस्तक ग्रंथालय अभिलेख गाव परिषद समिती श्रम आर्थिक नैतिक वाचनालय
"""


@lru_cache
def lexicon_for(language: str) -> frozenset[str]:
    raw = {"en": _EN, "hi": _HI, "mr": _MR}.get(language, _EN)
    return frozenset(w.strip().lower() for w in raw.split() if w.strip())
