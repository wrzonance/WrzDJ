export { artGradient } from '@/lib/art-gradient';

export function BannerBg({ url }: { url: string }) {
  return (
    <div className="join-banner-bg">
      <img src={url} alt="" />
    </div>
  );
}

export function StatPill({ label, value, accent, sub, border }: {
  label: string; value: string; accent: string; sub: string; border: string;
}) {
  return (
    <div style={{ padding: '5px 10px', borderRadius: 7, border: '1px solid ' + border, display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 42 }}>
      <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 15.2, fontWeight: 800, lineHeight: '1', color: accent }}>
        {value}
      </span>
      <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 9, color: sub, letterSpacing: 1.2, marginTop: 2.5 }}>
        {label}
      </span>
    </div>
  );
}
