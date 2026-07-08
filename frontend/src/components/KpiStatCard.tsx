import type { KpiResult } from "@/lib/api";

function formatValue(result: KpiResult): string {
  if (result.value === undefined || !result.unit) return "—";
  return `${result.value.toLocaleString()} ${result.unit}`;
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export default function KpiStatCard({ result }: { result: KpiResult }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border-2 border-zinc-300 bg-zinc-50 p-4 dark:border-zinc-700 dark:bg-zinc-900">
      <p className="text-xs uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        {result.kpi ? capitalize(result.kpi) : "KPI"}
        {result.period ? ` — ${result.period}` : ""}
      </p>
      <p className="text-3xl font-semibold text-black dark:text-zinc-50">
        {formatValue(result)}
      </p>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Source: {result.form ?? "?"} filed {result.filed ?? "?"}
        {result.source ? ` (${result.source})` : ""}
      </p>
    </div>
  );
}
