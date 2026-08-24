let deferredInstallPrompt = null;

export function canPromptInstall() {
  return !!deferredInstallPrompt;
}

export async function promptInstall() {
  if (!deferredInstallPrompt) throw new Error("Install prompt not ready");
  deferredInstallPrompt.prompt();
  const choice = await deferredInstallPrompt.userChoice;
  deferredInstallPrompt = null;
  return choice;
}

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredInstallPrompt = event;
    window.dispatchEvent(new Event("pwa-install-available"));
  });

  window.addEventListener("appinstalled", () => {
    deferredInstallPrompt = null;
  });
}
