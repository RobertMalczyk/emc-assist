/* Vite entry — imports the prototype's JSX modules in the original
   <script> order (icons -> data -> components -> diagram -> spectrum ->
   tweaks-panel -> screens -> app). Each file does its own `window.X = X`
   exports at the bottom (the prototype's cross-file mechanism); later
   files read those via bare-identifier fallthrough to globalThis. The
   mount call lives at the end of app.jsx. */

import "./styles.css";

import "./icons.jsx";
import "./data.jsx";
import "./api.jsx";
import "./components.jsx";
import "./diagram.jsx";
import "./spectrum.jsx";
import "./tweaks-panel.jsx";

import "./screens/projects.jsx";
import "./screens/import.jsx";
import "./screens/parasitics.jsx";
import "./screens/testbench.jsx";
import "./screens/run.jsx";
import "./screens/results.jsx";
import "./screens/findings.jsx";
import "./screens/report.jsx";
import "./screens/settings.jsx";
import "./screens/preview-lab.jsx";
import "./screens/preview-training.jsx";

import "./app.jsx";
