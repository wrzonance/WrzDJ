import type { ReactNode, SVGProps } from 'react';

interface FixedGroupProps extends SVGProps<SVGGElement> {
  x: number;
  y: number;
  scaleX: number;
  scaleY: number;
  children: ReactNode;
}

interface FixedTextProps extends Omit<SVGProps<SVGTextElement>, 'x' | 'y'> {
  x: number;
  y: number;
  scaleX: number;
  scaleY: number;
  testId?: string;
  children: ReactNode;
}

function fixedLabelTransform(x: number, y: number, scaleX: number, scaleY: number) {
  return `translate(${x} ${y}) scale(${scaleX.toFixed(4)} ${scaleY.toFixed(4)})`;
}

export function SvgFixedGroup({ x, y, scaleX, scaleY, children, ...props }: FixedGroupProps) {
  return (
    <g {...props} data-fixed-svg-label="true" transform={fixedLabelTransform(x, y, scaleX, scaleY)}>
      {children}
    </g>
  );
}

export function SvgFixedText({ x, y, scaleX, scaleY, testId, children, ...textProps }: FixedTextProps) {
  return (
    <SvgFixedGroup x={x} y={y} scaleX={scaleX} scaleY={scaleY} data-testid={testId}>
      <text x={0} y={0} {...textProps}>{children}</text>
    </SvgFixedGroup>
  );
}
