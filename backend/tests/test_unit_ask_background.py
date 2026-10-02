"""Background answers, the provider-parameter retry, and the lexical reranker's content-word scoring. No database."""

from __future__ import annotations

import json

import httpx
import pytest

import archive.ask.llm as llm_mod
from archive.ask.validate import parse_background
from archive.config import Settings
from archive.evaluation import evaluate_answer_behaviour
from archive.search.models import LexicalReranker


class TestParseBackground:
    def test_keeps_plain_sentences_up_to_three(self):
        raw = json.dumps({"in_scope": True, "sentences": ["One.", "Two.", "Three.", "Four."]})
        assert parse_background(raw).sentences == ["One.", "Two.", "Three."]

    def test_out_of_scope(self):
        res = parse_background('{"in_scope": false, "sentences": ["ignored"]}')
        assert not res.in_scope and res.sentences == []

    @pytest.mark.parametrize("quoted", ['He said "educate, agitate, organise".', "He wrote “annihilate caste”.",
                                        "He called it 'a state of mind' in a speech."])
    def test_drops_any_quotation(self, quoted):
        res = parse_background(json.dumps({"in_scope": True, "sentences": [quoted, "Plain fact."]}))
        assert res.sentences == ["Plain fact."] and res.dropped == 1

    def test_apostrophes_are_not_quotes(self):
        text = "Ambedkar's first wife was Ramabai; the couple's son was Yashwant."
        assert parse_background(json.dumps({"in_scope": True, "sentences": [text]})).sentences == [text]

    def test_accepts_sentence_objects_and_surrounding_text(self):
        raw = 'Here you go: {"in_scope": true, "sentences": [{"text": "A fact."}]}'
        assert parse_background(raw).sentences == ["A fact."]

    def test_not_json_raises(self):
        with pytest.raises(ValueError):
            parse_background("I cannot answer that.")


def _llm_with(handler) -> llm_mod.OpenAICompatibleLLM:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return llm_mod.OpenAICompatibleLLM(base_url="http://llm.test/v1", api_key="k", model="m", client=client)


REPLY = {"model": "m", "choices": [{"message": {"content": '{"sentences": []}'}}],
         "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


class TestProviderParameterRetry:
    def test_max_tokens_rejected_retries_with_max_completion_tokens(self):
        bodies = []

        def handler(req: httpx.Request) -> httpx.Response:
            body = json.loads(req.content)
            bodies.append(body)
            if "max_tokens" in body:
                return httpx.Response(400, json={"error": {"message": "Unsupported parameter: 'max_tokens'"}})
            return httpx.Response(200, json=REPLY)

        assert _llm_with(handler).complete("s", "u", 800).content == '{"sentences": []}'
        assert len(bodies) == 2 and bodies[1]["max_completion_tokens"] == 800 and "max_tokens" not in bodies[1]

    def test_response_format_rejected_retries_without_it(self):
        bodies = []

        def handler(req: httpx.Request) -> httpx.Response:
            body = json.loads(req.content)
            bodies.append(body)
            if "response_format" in body:
                return httpx.Response(400, json={"error": "response_format is not supported"})
            return httpx.Response(200, json=REPLY)

        _llm_with(handler).complete("s", "u", 100)
        assert len(bodies) == 2 and "response_format" not in bodies[1]

    def test_other_bad_request_is_not_retried(self):
        calls = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return httpx.Response(400, json={"error": "invalid model"})

        with pytest.raises(llm_mod.LLMUnavailable):
            _llm_with(handler).complete("s", "u", 100)
        assert len(calls) == 1

    def test_retry_happens_once(self):
        calls = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return httpx.Response(400, json={"error": "response_format and max_tokens and temperature rejected"})

        with pytest.raises(llm_mod.LLMUnavailable):
            _llm_with(handler).complete("s", "u", 100)
        assert len(calls) == 2


class TestLexicalReranker:
    def test_question_framing_words_do_not_count(self):
        rr = LexicalReranker()
        relevant, unrelated = rr.score("What was the Poona Pact?",
                                       ["The Poona Pact was signed in 1932.", "What was the weather in the city?"])
        assert relevant == 1.0 and unrelated == 0.0

    def test_all_filler_question_falls_back_to_every_word(self):
        assert LexicalReranker().score("what is this", ["what is this"]) == [1.0]


class TestSufficiencyThreshold:
    def test_lexical_threshold_applies_only_to_the_lexical_reranker(self):
        lexical = Settings(reranker_backend="lexical", sufficiency_threshold=0.2, lexical_sufficiency_threshold=0.4)
        cross = Settings(reranker_backend="fastembed", sufficiency_threshold=0.2, lexical_sufficiency_threshold=0.4)
        assert lexical.effective_sufficiency_threshold == 0.4 and cross.effective_sufficiency_threshold == 0.2

    def test_unset_lexical_threshold_keeps_the_default(self):
        s = Settings(reranker_backend="lexical", sufficiency_threshold=0.3, lexical_sufficiency_threshold=None)
        assert s.effective_sufficiency_threshold == 0.3


def test_background_and_off_topic_count_as_abstaining_from_an_archive_answer():
    rows = [{"expected": "not_in_archive", "outcome": "background"},
            {"expected": "not_in_archive", "outcome": "off_topic"},
            {"expected": "not_in_archive", "outcome": "answered"},
            {"expected": "answer", "outcome": "answered"}]
    res = evaluate_answer_behaviour(rows)
    assert res["correct_not_in_archive_rate"] == round(2 / 3, 4) and res["abstention_precision"] == 1.0
