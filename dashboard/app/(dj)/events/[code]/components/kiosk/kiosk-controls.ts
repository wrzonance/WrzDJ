export interface KioskControls {
  requestsOpen: boolean;
  togglingRequests: boolean;
  onToggleRequests: () => void;
  nowPlayingHidden: boolean;
  togglingNowPlaying: boolean;
  onToggleNowPlaying: () => void;
  autoHideInput: string;
  autoHideMinutes: number;
  savingAutoHide: boolean;
  onAutoHideInputChange: (value: string) => void;
  onSaveAutoHide: () => void;
  kioskDisplayOnly: boolean;
  togglingDisplayOnly: boolean;
  onToggleDisplayOnly: () => void;
  frictionlessJoin: boolean;
  togglingFrictionless: boolean;
  onToggleFrictionless: () => void;
}
