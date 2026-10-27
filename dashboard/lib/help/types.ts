export interface HelpSpotConfig {
  id: string;
  page: string;
  order: number;
  title: string;
  description: string;
  ref: React.RefObject<HTMLElement | null>;
}

export interface HelpState {
  helpMode: boolean;
  onboardingActive: boolean;
  currentStep: number;
  activeSpotId: string | null;
}

export interface HelpContextValue extends HelpState {
  toggleHelpMode: () => void;
  registerSpot: (config: HelpSpotConfig) => () => void;
  getSpotsForPage: (page: string) => HelpSpotConfig[];
  startOnboarding: (page: string) => void;
  nextStep: () => void;
  prevStep: () => void;
  skipOnboarding: () => void;
  dismissOnboarding: () => void;
  hasSeenPage: (page: string) => boolean;
}
