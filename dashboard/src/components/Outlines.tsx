import type { CSSProperties } from "react";

/**
 * The logo's hexagon, standing on a point, as SVG path data: centred on
 * (cx, cy), `radius` from the centre to each point, the points rounded as the
 * mark's are. Repeated, it is the pattern on the brand's green cards and the
 * sign-in pages.
 */
function hexagon(cx: number, cy: number, radius: number) {
  const round = 0.16 * radius;
  // A point's angle is 120 degrees, so its rounding starts this share of a side
  // away from it; every side is as long as the radius.
  const share = round / Math.tan(Math.PI / 3) / radius;
  const point = (k: number) => {
    const angle = ((60 * k - 90) * Math.PI) / 180;
    return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)] as const;
  };
  const toward = (from: readonly [number, number], to: readonly [number, number]) =>
    `${(from[0] + (to[0] - from[0]) * share).toFixed(2)} ${(from[1] + (to[1] - from[1]) * share).toFixed(2)}`;
  let path = "";
  for (let k = 0; k < 6; k++) {
    const here = point(k);
    path += `${k ? "L" : "M"}${toward(here, point(k - 1))}`;
    path += `A${round.toFixed(2)} ${round.toFixed(2)} 0 0 1 ${toward(here, point(k + 1))}`;
  }
  return `${path}Z`;
}

// A hexagon reads smaller than a square of the same width, so each outline's
// radius is a little more than the half-width it stands for.
const GROWN = 1.06;

/** Four outlines in a card's bottom corner, still. */
export function Outlines() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 260 260"
      overflow="visible"
      className="pointer-events-none absolute -end-[90px] -bottom-[110px] size-[260px]"
      fill="none"
      stroke="#ffffff"
      strokeOpacity="0.13"
      strokeWidth="1.5"
    >
      {[40, 70, 100, 128].map((half) => (
        <path key={half} d={hexagon(130, 130, GROWN * half)} />
      ))}
    </svg>
  );
}

const SMALLEST = 36;
const LARGEST = 1000;
const COUNT = 6;
// Seconds for one outline to grow from the smallest size to the largest.
const PERIOD = 42;

/**
 * Six outlines growing from the panel's top corner, each fading as it reaches
 * the far side. Under `prefers-reduced-motion` they stand still at the sizes
 * they start from.
 */
export function MovingOutlines() {
  return (
    <div
      aria-hidden
      className="fade-from-corner pointer-events-none absolute inset-0 overflow-hidden"
    >
      <svg
        viewBox={`0 0 ${2 * LARGEST} ${2 * LARGEST}`}
        overflow="visible"
        className="absolute"
        style={{
          width: 2 * LARGEST,
          height: 2 * LARGEST,
          insetInlineEnd: 96 - LARGEST,
          top: 118 - LARGEST,
        }}
        fill="none"
        stroke="var(--color-mint)"
        strokeOpacity="0.3"
        strokeWidth="1.5"
      >
        {Array.from({ length: COUNT }, (_, index) => {
          const half = SMALLEST + ((LARGEST - SMALLEST) * (index + 0.5)) / COUNT;
          const grown = (half - SMALLEST) / (LARGEST - SMALLEST);
          return (
            <path
              key={index}
              d={hexagon(LARGEST, LARGEST, GROWN * half)}
              vectorEffect="non-scaling-stroke"
              className="animate-outline"
              style={
                {
                  "--from": SMALLEST / half,
                  "--to": LARGEST / half,
                  animationDelay: `${-grown * PERIOD}s`,
                  opacity: 1 - 0.75 * grown,
                } as CSSProperties
              }
            />
          );
        })}
      </svg>
    </div>
  );
}
