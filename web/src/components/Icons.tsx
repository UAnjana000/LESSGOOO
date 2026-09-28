const base = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" } as const;

export const IconHome = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...base}>
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5 9.5V21h14V9.5" />
    <path d="M10 21v-6h4v6" />
  </svg>
);
export const IconSearch = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...base}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m16 16 5 5" />
  </svg>
);
export const IconAsk = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...base}>
    <path d="M4 5h16v11H9l-5 4z" />
    <path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.4" />
    <path d="M12 14.6v.1" />
  </svg>
);
export const IconTimeline = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...base}>
    <path d="M3 12h18" />
    <circle cx="7" cy="12" r="2" />
    <circle cx="17" cy="12" r="2" />
    <path d="M7 5v3M17 16v3M12 7v10" />
  </svg>
);
export const IconStories = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...base}>
    <path d="M4 5.5C6.5 4 9.5 4 12 5.5 14.5 4 17.5 4 20 5.5V19c-2.5-1.5-5.5-1.5-8 0-2.5-1.5-5.5-1.5-8 0z" />
    <path d="M12 5.5V19" />
  </svg>
);
export const IconMap = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...base}>
    <circle cx="6" cy="6" r="2.5" />
    <circle cx="18" cy="8" r="2.5" />
    <circle cx="10" cy="18" r="2.5" />
    <path d="m8.2 7 7.4.8M7 8.3l2.2 7.4M16.5 10l-4.8 6.3" />
  </svg>
);
export const IconConstitution = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...base}>
    <path d="M3 9 12 4l9 5" />
    <path d="M4 9h16M3 20h18" />
    <path d="M6.5 9v11M10.5 9v11M13.5 9v11M17.5 9v11" />
  </svg>
);
export const IconList = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...base}>
    <path d="M6 3h12v18l-6-4-6 4z" />
  </svg>
);
export const IconChevronLeft = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" width="22" height="22" {...base} strokeWidth={2.4}>
    <path d="m15 5-7 7 7 7" />
  </svg>
);
export const IconChevronRight = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" width="22" height="22" {...base} strokeWidth={2.4}>
    <path d="m9 5 7 7-7 7" />
  </svg>
);
export const IconPlay = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" width="18" height="18" {...base}>
    <path d="M7 4.5v15l12-7.5z" />
  </svg>
);

export const IconSettings = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...base}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
);
