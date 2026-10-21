'use client';

import { QRCodeSVG } from 'qrcode.react';

export function KioskRequestAccess({
  requestsOpen,
  joinUrl,
}: {
  requestsOpen: boolean;
  joinUrl: string;
}) {
  if (!requestsOpen) {
    return <div className="kiosk-closed-banner">Requests Closed</div>;
  }

  return (
    <div className="kiosk-qr">
      <div className="kiosk-qr-bg">
        <QRCodeSVG value={joinUrl} size={140} />
      </div>
      <p className="kiosk-qr-label">Scan to request from phone</p>
    </div>
  );
}
