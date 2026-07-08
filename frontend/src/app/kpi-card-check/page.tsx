import KpiStatCard from "@/components/KpiStatCard";
import type { KpiResult } from "@/lib/api";

const SAMPLE_KPI_RESULT: KpiResult = {
  status: "ok",
  kpi: "gross profit",
  gaap_tag: "GrossProfit",
  value: 3877800000,
  unit: "USD",
  period: "FY2025",
  form: "10-K",
  filed: "2026-01-28",
  end_date: "2025-11-30",
  tier: "Verified-from-filing",
  source: "SEC EDGAR XBRL companyfacts API",
};

export default function KpiCardCheck() {
  return (
    <div className="p-8">
      <KpiStatCard result={SAMPLE_KPI_RESULT} />
    </div>
  );
}
