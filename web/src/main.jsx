import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./theme.css";

createRoot(document.getElementById("root")).render(<App />);

// PWA: lets the app be installed to a phone's home screen (Android requires
// a service worker; iOS installs from the manifest + apple-touch meta alone).
if ("serviceWorker" in navigator && !location.hostname.includes("localhost")) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
