import { Flame, Thermometer, Snowflake } from "lucide-react";

const SENTIMENT_STYLES = {
  positive: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  interested: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  neutral: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  hesitant: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  frustrated: "bg-rose-500/15 text-rose-400 border-rose-500/30",
  negative: "bg-rose-500/15 text-rose-400 border-rose-500/30",
};

export function CategoryBadge({ category }) {
  const styles = {
    hot: { bg: "bg-orange-500/15 text-orange-400 border-orange-500/30", Icon: Flame, label: "Hot" },
    warm: { bg: "bg-amber-500/15 text-amber-400 border-amber-500/30", Icon: Thermometer, label: "Warm" },
    cold: { bg: "bg-sky-500/15 text-sky-400 border-sky-500/30", Icon: Snowflake, label: "Cold" },
  };
  const cfg = styles[category] || styles.cold;
  const Icon = cfg.Icon;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${cfg.bg}`}>
      <Icon className="w-3.5 h-3.5" />
      {cfg.label}
    </span>
  );
}

export function SentimentChip({ sentiment = "neutral" }) {
  const key = String(sentiment || "neutral").toLowerCase();
  const cls = SENTIMENT_STYLES[key] || SENTIMENT_STYLES.neutral;
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border capitalize ${cls}`}>
      {key}
    </span>
  );
}

export function ScoreGauge({ score = 0, category = "cold", sentiment = "neutral" }) {
  const clamped = Math.min(100, Math.max(0, Number(score) || 0));
  const radius = 32;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (clamped / 100) * circumference;

  const strokeColor =
    category === "hot"
      ? "#fb7185"
      : category === "warm"
        ? "#f59e0b"
        : "#38bdf8";

  return (
    <div className="flex items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <div className="relative w-20 h-20 flex items-center justify-center">
          <svg className="w-20 h-20 -rotate-90" viewBox="0 0 80 80" aria-label={`Lead score ${clamped} out of 100`}>
            <circle
              cx="40"
              cy="40"
              r={radius}
              fill="none"
              stroke="currentColor"
              strokeWidth="6"
              className="text-white/10"
            />
            <circle
              cx="40"
              cy="40"
              r={radius}
              fill="none"
              stroke={strokeColor}
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
              className="transition-all duration-300 ease-out"
            />
          </svg>
          <span className="absolute font-mono text-base font-semibold">{clamped}</span>
        </div>

        <div className="space-y-1.5">
          <div className="text-xs uppercase tracking-wider text-slate-400">Lead Score</div>
          <div className="flex items-center gap-2 flex-wrap">
            <CategoryBadge category={category} />
            <SentimentChip sentiment={sentiment} />
          </div>
        </div>
      </div>
    </div>
  );
}
