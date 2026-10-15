"use client";

interface MusicKitInstance {
  authorize(): Promise<string>;
}

interface MusicKitGlobal {
  configure(options: {
    developerToken: string;
    app: { name: string; build: string };
  }): Promise<unknown>;
  getInstance(): MusicKitInstance;
}

declare global {
  interface Window {
    MusicKit?: MusicKitGlobal;
  }
}

const MUSIC_KIT_SCRIPT = "https://js-cdn.music.apple.com/musickit/v3/musickit.js";
let musicKitLoad: Promise<MusicKitGlobal> | null = null;

function loadMusicKit(): Promise<MusicKitGlobal> {
  if (window.MusicKit) return Promise.resolve(window.MusicKit);
  if (musicKitLoad) return musicKitLoad;

  const pending = new Promise<MusicKitGlobal>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = MUSIC_KIT_SCRIPT;
    script.async = true;
    const cleanup = () => document.removeEventListener("musickitloaded", onMusicKitLoaded);
    const onMusicKitLoaded = () => {
      if (window.MusicKit) {
        cleanup();
        resolve(window.MusicKit);
      }
    };
    script.onload = onMusicKitLoaded;
    script.onerror = () => {
      cleanup();
      reject(new Error("Could not load Apple Music authorization."));
    };
    document.addEventListener("musickitloaded", onMusicKitLoaded);
    document.head.appendChild(script);
  });
  musicKitLoad = pending.catch(error => {
    musicKitLoad = null;
    throw error;
  });
  return musicKitLoad;
}

export async function authorizeAppleMusic(developerToken: string): Promise<string> {
  const musicKit = await loadMusicKit();
  await musicKit.configure({
    developerToken,
    app: { name: "WrzDJ", build: "1.0.0" },
  });
  return musicKit.getInstance().authorize();
}
