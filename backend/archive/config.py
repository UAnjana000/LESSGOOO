"""Environment-based configuration. Every setting can be overridden with an ARCHIVE_* variable."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARCHIVE_", env_file=".env", extra="ignore")

    environment: Literal["dev", "test", "demo", "production"] = "dev"
    database_url: str = "postgresql+psycopg://archive:archive@localhost:5432/archive"

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, v: object) -> str:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("postgres://"):
                return "postgresql+psycopg://" + v[len("postgres://") :]
            elif v.startswith("postgresql://") and not v.startswith("postgresql+"):
                return "postgresql+psycopg://" + v[len("postgresql://") :]
        return str(v)

    # Storage: preservation masters live on a separate volume from delivery copies and derivatives.
    preservation_root: Path = Path("./data/preservation")
    delivery_root: Path = Path("./data/delivery")
    derivative_root: Path = Path("./data/derivatives")
    quarantine_root: Path = Path("./data/quarantine")
    trace_root: Path = Path("./data/traces")
    backup_root: Path = Path("./data/backups")  # prototype: a second disk mounted here
    nightly_backup_enabled: bool = True
    nightly_backup_hour_utc: int = Field(default=20, ge=0, le=23)  # 20:00 UTC = 01:30 IST
    backup_keep: int = Field(default=14, ge=1)  # complete backups kept in backup_root after each backup job
    model_cache: Path = Path("./data/models")

    # Staff auth (prototype: passwords; PROD: SSO/MFA).
    jwt_secret: str = "dev-only-change-me"
    jwt_ttl_minutes: int = 480
    # Demo only: a "continue as judge" button signs in a read-only viewer without a password.
    judge_access: bool = False
    # Largest single file accepted by staff intake (bytes).
    intake_max_upload_bytes: int = Field(default=1024**3, ge=1024)
    # Demo only: the staff workspace opens without a login, signed in as the bootstrap administrator.
    open_staff_access: bool = False
    bootstrap_admin_email: str = "admin@archive.local"
    bootstrap_admin_password: str = ""
    # Local demo only: when set, bootstrap creates archivist/curator/translation-reviewer demo accounts.
    demo_staff_password: str = ""

    # Exhibit cache signing (ECDSA P-256 PEM). Generated into derivative_root when empty.
    exhibit_signing_key_path: Path | None = None
    exhibit_lease_hours: int = 72
    exhibit_cache_budget_bytes: int = 200 * 1024 * 1024
    qr_link_ttl_hours: int = 24
    public_base_url: str = "https://archive.local"

    # OCR
    tesseract_cmd: str = "tesseract"
    ocr_languages: str = "eng+hin+mar"
    # Page segmentation: "3" automatic layout, "6" one uniform block, "auto" = 6 unless the page has a column
    # gutter, then 3 (docs/OCR_ENGINE_EVAL.md).
    ocr_tesseract_psm: Literal["3", "6", "auto"] = "3"
    # Tesseract language string per page language. "Devanagari" (the script model) also reads Latin letters
    # and ASCII digits inside Hindi text; it needs Devanagari.traineddata in the tessdata directory.
    ocr_tesseract_lang_en: str = "eng"
    ocr_tesseract_lang_hi: str = "hin"
    ocr_tesseract_lang_mr: str = "mar"
    gate_config_path: Path = Path(__file__).parent / "ingest" / "gate_thresholds.json"

    # Sarvam (OCR fallback, translation, TTS, speech-to-text drafts are separate switches).
    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai"
    sarvam_ocr_enabled: bool = True
    sarvam_translate_enabled: bool = True
    sarvam_tts_enabled: bool = True
    sarvam_stt_enabled: bool = True
    sarvam_stt_max_seconds: int = Field(default=3 * 3600, ge=30)  # longest recording one job may send
    sarvam_max_retries: int = 3
    sarvam_poll_seconds: float = 3.0
    sarvam_poll_timeout_seconds: float = 180.0

    # LLM for answers / summary drafts. "none" means no answer model: Ask returns
    # the closest approved passages, clearly labelled, instead of a generated answer.
    llm_provider: Literal["none", "openai_compatible"] = "none"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    # Room for 4 cited sentences in JSON; a reasoning model also spends part of this before it writes.
    llm_max_output_tokens: int = 800
    # True when the answer model runs off the premises (hosted API): passages whose rights register entry
    # does not allow external processing are then never put in its prompt.
    llm_external: bool = True
    llm_input_cost_per_mtok: float = 0.0
    llm_output_cost_per_mtok: float = 0.0
    daily_cost_alert_usd: float = 5.0

    # Voice questions on Ask: the visitor's recording goes to {llm_base_url}/audio/transcriptions with
    # llm_api_key, and only the text comes back to the question box. The audio is never stored.
    ask_voice_enabled: bool = True
    ask_voice_model: str = "whisper-1"
    ask_voice_max_seconds: int = Field(default=120, ge=5)
    ask_voice_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)

    # Retrieval
    embedding_backend: Literal["fastembed", "hash"] = "fastembed"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384
    reranker_backend: Literal["fastembed", "lexical"] = "fastembed"
    reranker_model: str = "jinaai/jina-reranker-v2-base-multilingual"
    retrieval_candidate_k: int = 30
    # Ask only: how many fused candidates the cross-encoder scores, and how much of each it reads.
    # Re-check first-stage Recall@rerank_candidate_k on the reviewed question set (spec §10.1) before lowering it.
    rerank_candidate_k: int = 15
    rerank_max_chars: int = 900
    retrieval_top_k: int = 5
    passage_max_chars: int = 900
    sufficiency_threshold: float = 0.20
    sufficiency_threshold_version: str = "calibrated-v1"
    # The 0.20 above is calibrated for the cross-encoder. The lexical test double scores the share of the
    # question's content words a passage contains, so it needs its own bar; unset keeps sufficiency_threshold.
    lexical_sufficiency_threshold: float | None = None
    # When the archive cannot answer, the answer model may give up to 3 sentences of general background on
    # Dr. Ambedkar's life, works and constitutional ideas: labelled, uncited, never quoted, never cached.
    ask_background_enabled: bool = True
    session_turns: int = 3
    question_max_chars: int = 500
    prompt_version: str = "ask-v2"

    # Langfuse (redacted traces only). Absent keys -> local redacted JSONL sink.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""
    trace_question_mode: Literal["hash", "scrubbed"] = "scrubbed"

    # Workers
    worker_poll_seconds: float = 2.0
    withdrawal_grace_hours: int = 24
    old_version_grace_hours: int = 72

    log_level: str = "INFO"
    cors_origins: list[str] | str = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator("cors_origins", mode="after")
    @classmethod
    def _normalize_cors_origins(cls, v: object) -> list[str]:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                import json
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(x) for x in parsed]
                except Exception:
                    pass
            return [x.strip() for x in v.split(",") if x.strip()]
        if isinstance(v, (list, tuple, set)):
            return [str(x) for x in v]
        return ["http://localhost:5173"]

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key and self.langfuse_host)

    @property
    def sarvam_available(self) -> bool:
        return bool(self.sarvam_api_key)

    @property
    def llm_available(self) -> bool:
        return self.llm_provider != "none" and bool(self.llm_api_key and self.llm_model)

    @property
    def effective_sufficiency_threshold(self) -> float:
        if self.reranker_backend == "lexical" and self.lexical_sufficiency_threshold is not None:
            return self.lexical_sufficiency_threshold
        return self.sufficiency_threshold

    @property
    def ask_voice_available(self) -> bool:
        return self.ask_voice_enabled and self.llm_provider == "openai_compatible" and bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
