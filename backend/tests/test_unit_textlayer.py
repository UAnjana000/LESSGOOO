"""Pure unit tests (no database, no PDF bytes): born-digital text-layer reliability check."""

from __future__ import annotations

from archive.ingest.quality import garbage_rate
from archive.ingest.textlayer import text_layer_reliable

# Legacy Kruti Dev-style font extracted as Latin mojibake (not real Hindi text).
MOJIBAKE = "lfpo us dgk fd lafo/kku lHkk dh cSBd esa ekuuh; lnL;ksa us izLrko ij fopkj fd;k vkSj mls ikl fd;k A"
DEVANAGARI = "सचिव ने कहा कि संविधान सभा की बैठक में माननीय सदस्यों ने प्रस्ताव पर विचार किया और उसे पास किया।"
ENGLISH = "The Secretary said that the Constituent Assembly considered the motion and adopted it."


class TestTextLayerReliability:
    def test_mojibake_passes_garbage_check_alone(self):
        assert garbage_rate(MOJIBAKE) < 0.1

    def test_mojibake_is_unreliable_for_hindi_and_marathi(self):
        assert not text_layer_reliable(MOJIBAKE, "hi")
        assert not text_layer_reliable(MOJIBAKE, "mr")

    def test_real_devanagari_is_reliable(self):
        assert text_layer_reliable(DEVANAGARI, "hi")
        assert text_layer_reliable(DEVANAGARI, "mr")

    def test_english_layer_unaffected(self):
        assert text_layer_reliable(ENGLISH, "en")
        assert not text_layer_reliable(ENGLISH, "hi")

    def test_short_text_still_unreliable(self):
        assert not text_layer_reliable("सभा", "hi")
