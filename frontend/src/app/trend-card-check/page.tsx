import TrendDropCard from "@/components/TrendDropCard";
import type { TrendResult } from "@/lib/api";

const SAMPLE_RESULTS: TrendResult[] = [
  {
    keyword: "Levi's McLaren",
    drop_date: "2024-07-03",
    status: "ok",
    peak_date: "2024-07-08",
    peak_value: 33.1,
    half_life_weeks: 0.3,
    half_life_days: 2,
    r_squared: 1.0,
    confidence: "low",
    decay_series_length: 3,
    vs_report_claim: "shorter",
    methodology_note: "Sample data for isolated visual check.",
    report_claim: "6–8 week trend cycle (half-life interpreted as 3–4 weeks)",
    warning:
      "Signal is impulse-like (≤2 non-zero post-peak weeks) — half-life estimate is not reliable; interpret with caution",
    drop_key: "silverstone_2024",
    label: "Silverstone / British Grand Prix",
  },
  {
    keyword: "Levi's McLaren",
    drop_date: "2024-10-17",
    status: "insufficient_data",
    peak_date: null,
    peak_value: null,
    half_life_weeks: null,
    half_life_days: null,
    r_squared: null,
    confidence: null,
    decay_series_length: null,
    vs_report_claim: null,
    methodology_note: "Sample data for isolated visual check.",
    report_claim: "6–8 week trend cycle (half-life interpreted as 3–4 weeks)",
    drop_key: "austin_2024",
    label: "Austin / U.S. Grand Prix",
  },
  {
    keyword: "Hypothetical Keyword",
    drop_date: "2024-01-01",
    status: "ok",
    peak_date: "2024-01-05",
    peak_value: 80,
    half_life_weeks: 4.2,
    half_life_days: 29,
    r_squared: 0.91,
    confidence: "high",
    decay_series_length: 8,
    vs_report_claim: "within_range",
    methodology_note: "Hypothetical high-confidence sample for visual contrast.",
    report_claim: "6–8 week trend cycle (half-life interpreted as 3–4 weeks)",
    drop_key: "hypothetical",
    label: "Hypothetical high-confidence drop (contrast sample)",
  },
];

export default function TrendCardCheck() {
  return (
    <div className="flex flex-col gap-4 p-8">
      {SAMPLE_RESULTS.map((result) => (
        <TrendDropCard key={result.drop_key} result={result} />
      ))}
    </div>
  );
}
