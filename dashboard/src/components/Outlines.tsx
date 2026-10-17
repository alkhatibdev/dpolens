import type { CSSProperties } from "react";

/**
 * The logo's rounded square, repeated: the pattern on the brand's green cards.
 * The corner keeps the mark's proportion, 0.44 of half the side.
 */
function square(centre: number, half: number) {
  return {
    x: centre - half,
    y: centre - half,
    width: 2 * half,
    height: 2 * half,
    rx: 0.44 * half,
  };
}

/** Four outlines in a card's bottom corner, still. */
export function Outlines() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 260 260"
      className="pointer-events-none absolute -end-[90px] -bottom-[110px] size-[260px]"
      fill="none"
      stroke="#ffffff"
      strokeOpacity="0.13"
      strokeWidth="1.5"
    >
      {[40, 70, 100, 128].map((half) => (
        <rect key={half} {...square(130, half)} />
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
            <rect
              key={index}
              {...square(LARGEST, half)}
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
