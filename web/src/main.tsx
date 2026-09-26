import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { startExhibit } from "./exhibit";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

void startExhibit();
