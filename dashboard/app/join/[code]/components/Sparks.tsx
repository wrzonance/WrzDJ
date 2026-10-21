'use client';

import { useEffect, useState } from 'react';

interface Props {
  accent: string;
  accent2: string;
  fire: boolean;
  onDone?: () => void;
}

const SPARK_COUNT = 14;

export default function Sparks({ accent, accent2, fire, onDone }: Props) {
  const [active, setActive] = useState(false);

  useEffect(() => {
    if (!fire) {
      setActive(false);
      return;
    }
    setActive(true);
    const t = setTimeout(() => {
      setActive(false);
      onDone?.();
    }, 900);
    return () => clearTimeout(t);
  }, [fire]);

  if (!active) return null;

  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'visible', zIndex: 10 }}>
      {Array.from({ length: SPARK_COUNT }, (_, i) => {
        const angle = (i / SPARK_COUNT) * Math.PI * 2 + Math.random() * 0.4;
        const dist = 40 + Math.random() * 36;
        const dx = Math.cos(angle) * dist;
        const dy = Math.sin(angle) * dist;
        const c = i % 2 ? accent : accent2;
        const size = 3 + Math.random() * 3;
        return (
          <span
            key={i}
            style={{
              position: 'absolute',
              left: '50%',
              top: '50%',
              width: size,
              height: size,
              borderRadius: '50%',
              background: c,
              boxShadow: `0 0 8px ${c}`,
              animation: 'gst-spark 900ms ease-out forwards',
              '--dx': `${dx}px`,
              '--dy': `${dy}px`,
            } as React.CSSProperties}
          />
        );
      })}
    </div>
  );
}
