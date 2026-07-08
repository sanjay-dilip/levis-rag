import type { TrendResult } from "@/lib/api";

const CONFIDENCE_STYLES: Record<"high" | "medium" | "low", string> = {
  high: "border-emerald-400 bg-emerald-50 dark:border-emerald-700 dark:bg-emerald-950",
  medium: "border-amber-400 bg-amber-50 dark:border-amber-700 dark:bg-amber-950",
  low: "border-red-400 bg-red-50 dark:border-red-700 dark:bg-red-950",
};

const CONFIDENCE_TEXT_STYLES: Record<"high" | "medium" | "low", string> = {
  high: "text-emerald-800 dark:text-emerald-200",
  medium: "text-amber-800 dark:text-amber-200",
  low: "text-red-800 dark:text-red-200",
};

export default function TrendDropCard({ result }: { result: TrendResult }) {
  if (result.status !== "ok") {
    return (
      <div className="flex flex-col gap-1 rounded-lg border-2 border-zinc-300 bg-zinc-50 p-4 dark:border-zinc-700 dark:bg-zinc-900">
        <p className="text-xs uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          {result.label}
        </p>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {result.status === "insufficient_data"
            ? "Insufficient signal to fit a decay curve."
            : `Status: ${result.status}`}
        </p>
      </div>
    );
  }

  const confidence = result.confidence ?? "low";

  return (
    <div
      className={`flex flex-col gap-1 rounded-lg border-2 p-4 ${CONFIDENCE_STYLES[confidence]}`}
    >
      <p className="text-xs uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        {result.label}
      </p>
      <p className="text-3xl font-semibold text-black dark:text-zinc-50">
        {result.half_life_weeks} weeks
      </p>
      <p className="text-xs text-zinc-600 dark:text-zinc-400">
        R² = {result.r_squared}
      </p>
      <p
        className={`text-sm font-bold uppercase ${CONFIDENCE_TEXT_STYLES[confidence]}`}
      >
        {confidence} confidence
      </p>
      {result.warning && (
        <p className={`text-xs ${CONFIDENCE_TEXT_STYLES[confidence]}`}>
          {result.warning}
        </p>
      )}
    </div>
  );
}
