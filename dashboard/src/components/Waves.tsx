/**
 * Waves that move slowly and never stop, for the sign-in page. Each layer is two
 * identical periods wide and slides by one period, so the loop has no seam. Under
 * `prefers-reduced-motion` they stand still.
 */
const WAVE =
  "M0 70 Q 180 10 360 70 T 720 70 T 1080 70 T 1440 70 T 1800 70 T 2160 70 T 2520 70 T 2880 70 V 220 H 0 Z";

const LAYERS = [
  { opacity: 0.1, duration: "46s", height: "100%" },
  { opacity: 0.14, duration: "33s", height: "76%" },
  { opacity: 0.2, duration: "24s", height: "54%" },
] as const;

export function Waves() {
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-x-0 bottom-0 h-[90px] overflow-hidden sm:h-[150px] lg:h-[220px]"
    >
      {LAYERS.map((layer) => (
        <svg
          key={layer.duration}
          viewBox="0 0 2880 220"
          preserveAspectRatio="none"
          className="animate-drift absolute bottom-0 left-0 w-[200%]"
          style={{ height: layer.height, ["--drift-duration" as string]: layer.duration }}
        >
          <path d={WAVE} fill="#ffffff" fillOpacity={layer.opacity} />
        </svg>
      ))}
    </div>
  );
}
