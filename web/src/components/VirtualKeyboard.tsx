import { useEffect, useState } from "react";
import { useSession } from "../state";

interface VirtualKeyboardProps {
  activeInput: HTMLInputElement | HTMLTextAreaElement | null;
  onClose: () => void;
}

const EN_ROWS = [
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "?"],
  ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
  ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
  ["z", "x", "c", "v", "b", "n", "m", ".", ","],
];

const DEVA_ROWS = [
  ["१", "२", "३", "४", "५", "६", "७", "८", "९", "०", "-", "."],
  ["अ", "आ", "इ", "ई", "उ", "ऊ", "ए", "ऐ", "ओ", "औ"],
  ["क", "ख", "ग", "घ", "च", "छ", "ज", "झ", "ट", "ठ"],
  ["ड", "ढ", "त", "थ", "द", "ध", "न", "प", "फ", "ब"],
  ["भ", "म", "य", "र", "ल", "व", "श", "ष", "स", "ह"],
  ["ा", "ि", "ी", "ु", "ू", "े", "ै", "ो", "ौ", "ं", "्"],
];

export function VirtualKeyboard({ activeInput, onClose }: VirtualKeyboardProps) {
  const { t, lang } = useSession();
  const [script, setScript] = useState<"en" | "deva">(lang === "en" ? "en" : "deva");
  const [shift, setShift] = useState(false);

  useEffect(() => {
    if (lang === "en") setScript("en");
    else setScript("deva");
  }, [lang]);

  if (!activeInput) return null;

  const insertChar = (char: string) => {
    const val = activeInput.value;
    const start = activeInput.selectionStart ?? val.length;
    const end = activeInput.selectionEnd ?? val.length;
    const finalChar = shift && script === "en" ? char.toUpperCase() : char;
    const nextVal = val.slice(0, start) + finalChar + val.slice(end);

    // Update value through prototype setter so React tracks state changes
    const proto = Object.getPrototypeOf(activeInput);
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (setter) {
      setter.call(activeInput, nextVal);
    } else {
      activeInput.value = nextVal;
    }

    activeInput.dispatchEvent(new Event("input", { bubbles: true }));
    activeInput.dispatchEvent(new Event("change", { bubbles: true }));

    const nextPos = start + finalChar.length;
    activeInput.setSelectionRange(nextPos, nextPos);
    activeInput.focus();
  };

  const handleBackspace = () => {
    const val = activeInput.value;
    const start = activeInput.selectionStart ?? val.length;
    const end = activeInput.selectionEnd ?? val.length;

    if (start === end && start > 0) {
      const nextVal = val.slice(0, start - 1) + val.slice(end);
      const proto = Object.getPrototypeOf(activeInput);
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      if (setter) {
        setter.call(activeInput, nextVal);
      } else {
        activeInput.value = nextVal;
      }
      activeInput.dispatchEvent(new Event("input", { bubbles: true }));
      activeInput.dispatchEvent(new Event("change", { bubbles: true }));
      activeInput.setSelectionRange(start - 1, start - 1);
    } else if (start !== end) {
      const nextVal = val.slice(0, start) + val.slice(end);
      const proto = Object.getPrototypeOf(activeInput);
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      if (setter) {
        setter.call(activeInput, nextVal);
      } else {
        activeInput.value = nextVal;
      }
      activeInput.dispatchEvent(new Event("input", { bubbles: true }));
      activeInput.dispatchEvent(new Event("change", { bubbles: true }));
      activeInput.setSelectionRange(start, start);
    }
    activeInput.focus();
  };

  const handleClear = () => {
    const proto = Object.getPrototypeOf(activeInput);
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (setter) {
      setter.call(activeInput, "");
    } else {
      activeInput.value = "";
    }
    activeInput.dispatchEvent(new Event("input", { bubbles: true }));
    activeInput.dispatchEvent(new Event("change", { bubbles: true }));
    activeInput.focus();
  };

  const handleEnter = () => {
    // If inside a form, trigger submit
    if (activeInput.form) {
      activeInput.form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    }
    onClose();
  };

  const currentRows = script === "en" ? EN_ROWS : DEVA_ROWS;

  return (
    <div
      className="virtual-touch-keyboard"
      role="region"
      aria-label={t("kioskTitle")}
      onPointerDown={(e) => {
        // Prevent clicking keyboard buttons from stealing focus away from input
        e.preventDefault();
      }}
    >
      <div className="vk-header-bar">
        <div className="vk-script-toggles">
          <button
            type="button"
            className={`btn small ${script === "en" ? "primary" : "secondary"}`}
            onClick={() => setScript("en")}
          >
            English (ABC)
          </button>
          <button
            type="button"
            className={`btn small ${script === "deva" ? "primary" : "secondary"}`}
            onClick={() => setScript("deva")}
          >
            देवनागरी (अ/क)
          </button>
        </div>

        <button
          type="button"
          className="btn quiet small vk-close-btn"
          onClick={onClose}
          aria-label={t("keyboardClose")}
        >
          ✕ {t("keyboardClose")}
        </button>
      </div>

      <div className="vk-rows-container">
        {currentRows.map((row, rIdx) => (
          <div key={rIdx} className="vk-row">
            {rIdx === 2 && script === "en" && (
              <button
                type="button"
                className={`vk-key vk-shift-key ${shift ? "active" : ""}`}
                onClick={() => setShift((s) => !s)}
                aria-pressed={shift}
              >
                ⇧
              </button>
            )}

            {row.map((char) => (
              <button
                key={char}
                type="button"
                className="vk-key"
                onClick={() => insertChar(char)}
              >
                {shift && script === "en" ? char.toUpperCase() : char}
              </button>
            ))}

            {rIdx === 3 && (
              <button
                type="button"
                className="vk-key vk-backspace-key"
                onClick={handleBackspace}
                aria-label={t("keyboardClear")}
              >
                ⌫
              </button>
            )}
          </div>
        ))}

        {/* Space, Clear, Enter Row */}
        <div className="vk-row vk-bottom-row">
          <button
            type="button"
            className="btn secondary vk-clear-btn"
            onClick={handleClear}
          >
            {t("keyboardClear")}
          </button>

          <button
            type="button"
            className="vk-key vk-space-key"
            onClick={() => insertChar(" ")}
          >
            {t("keyboardSpace")}
          </button>

          <button
            type="button"
            className="btn primary vk-enter-btn"
            onClick={handleEnter}
          >
            {t("keyboardEnter")} ↵
          </button>
        </div>
      </div>
    </div>
  );
}
