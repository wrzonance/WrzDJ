'use client';

import type { Event, ArchivedEvent, TidalStatus, BeatportStatus } from '@/lib/api/types';
import type { CollectionSettingsResponse } from '@/lib/api';
import type { KioskControls } from '../kiosk/kiosk-controls';
import { KioskControlsCard } from '../kiosk/KioskControlsCard';
import { PairedKiosksCard } from '../kiosk/PairedKiosksCard';
import { StreamOverlayCard } from '../kiosk/StreamOverlayCard';
import { BridgeStatusCard } from '../kiosk/BridgeStatusCard';
import { CloudProvidersCard } from '../providers/CloudProvidersCard';
import { EventCustomizationCard } from './EventCustomizationCard';
import { PreEventVotingCard } from '../voting/PreEventVotingCard';
import { HelpSpot } from '@/components/help/HelpSpot';

interface BridgeDetails {
  circuitBreakerState: string | null;
  bufferSize: number | null;
  pluginId: string | null;
  deckCount: number | null;
  uptimeSeconds: number | null;
}

interface CloudProviderControls {
  tidalStatus: TidalStatus | null;
  tidalSyncEnabled: boolean;
  togglingTidalSync: boolean;
  onToggleTidalSync: () => void;
  onConnectTidal: () => void;
  onDisconnectTidal: () => void;
  beatportStatus: BeatportStatus | null;
  beatportSyncEnabled: boolean;
  togglingBeatportSync: boolean;
  onToggleBeatportSync: () => void;
  onConnectBeatport: () => void;
  onDisconnectBeatport: () => void;
}

interface EventCustomization {
  uploadingBanner: boolean;
  onBannerSelect: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onDeleteBanner: () => void;
}

interface PreEventNavigation {
  onPreEventEnabled: (next: CollectionSettingsResponse) => void;
  onJumpToPreEventTab: () => void;
}

interface EventManagementTabProps {
  code: string;
  event: Event | ArchivedEvent;
  bridge: { connected: boolean; details?: BridgeDetails | null };
  kiosk: KioskControls;
  providers: CloudProviderControls;
  customization: EventCustomization;
  preEvent: PreEventNavigation;
}

export function EventManagementTab(props: EventManagementTabProps) {
  return (
    <>
      <HelpSpot spotId="event-kiosk" page="event-manage" order={1} title="Kiosk Controls" description="Toggle requests open/closed, show/hide now-playing, enable display-only mode.">
        <KioskControlsCard
          joinCode={props.event.join_code}
          controls={props.kiosk}
        />
      </HelpSpot>

      <PairedKiosksCard eventCode={props.code} />

      <HelpSpot spotId="event-customization" page="event-manage" order={2} title="Event Customization" description="Upload a banner image to brand your event's kiosk and join pages.">
        <EventCustomizationCard
          event={props.event}
          uploadingBanner={props.customization.uploadingBanner}
          onBannerSelect={props.customization.onBannerSelect}
          onDeleteBanner={props.customization.onDeleteBanner}
        />
      </HelpSpot>

      <PreEventVotingCard
        event={props.event}
        onEnabled={props.preEvent.onPreEventEnabled}
        onJumpToTab={props.preEvent.onJumpToPreEventTab}
      />

      <HelpSpot spotId="event-stream-overlay" page="event-manage" order={3} title="Stream Overlay" description="Copy the OBS browser source URL to show currently playing track on your stream.">
        <StreamOverlayCard joinCode={props.event.join_code} />
      </HelpSpot>

      <HelpSpot spotId="event-bridge" page="event-manage" order={4} title="Bridge Status" description="Shows Bridge App connection status with live diagnostics. When connected, use Ping to test responsiveness, Reset Decks to clear stale track state, Reconnect to re-establish equipment detection, or Restart for a full bridge reset.">
        <BridgeStatusCard
          eventCode={props.code}
          bridgeConnected={props.bridge.connected}
          bridgeDetails={props.bridge.details}
        />
      </HelpSpot>

      <HelpSpot spotId="event-cloud" page="event-manage" order={5} title="Cloud Providers" description="Connect Tidal and Beatport to sync accepted requests to your streaming playlists.">
        <CloudProvidersCard
          tidalStatus={props.providers.tidalStatus}
          tidalSyncEnabled={props.providers.tidalSyncEnabled}
          togglingTidalSync={props.providers.togglingTidalSync}
          onToggleTidalSync={props.providers.onToggleTidalSync}
          onConnectTidal={props.providers.onConnectTidal}
          onDisconnectTidal={props.providers.onDisconnectTidal}
          beatportStatus={props.providers.beatportStatus}
          beatportSyncEnabled={props.providers.beatportSyncEnabled}
          togglingBeatportSync={props.providers.togglingBeatportSync}
          onToggleBeatportSync={props.providers.onToggleBeatportSync}
          onConnectBeatport={props.providers.onConnectBeatport}
          onDisconnectBeatport={props.providers.onDisconnectBeatport}
        />
      </HelpSpot>
    </>
  );
}
