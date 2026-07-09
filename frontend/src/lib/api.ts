export type Tier =
  | "Verified-from-filing"
  | "Management-qualitative-statement"
  | "Third-party-benchmark"
  | "Model-inference"
  | "Insufficient-data";

export type Claim = {
  claim_text: string;
  tier: Tier;
  supporting_chunk_id: number;
  fiscal_year?: string | null;
};

export type Chunk = {
  id: number;
  source: string;
  filing_type: string;
  section: string;
  fiscal_year: string | null;
  rrf_score: number;
  similarity: number;
};

export type QuestionType =
  | "FINANCIAL_LOOKUP"
  | "TREND_QUERY"
  | "XBRL_KPI"
  | "OUT_OF_SCOPE";

// Mirrors src/xbrl_tool.py's get_kpi() return dict. Only the "ok" status
// carries the full set of fields; the error statuses carry a subset.
export type KpiResult = {
  status: "ok" | "no_kpi_match" | "no_period_match" | "not_found";
  kpi?: string;
  gaap_tag?: string;
  value?: number;
  unit?: string;
  period?: string;
  form?: string;
  filed?: string;
  end_date?: string;
  tier?: Tier;
  source?: string;
  question?: string;
};

// Mirrors src/trend_decay_tool.py's analyze_drop() return dict (one per drop).
export type TrendResult = {
  keyword: string;
  drop_date: string;
  status: "ok" | "insufficient_data" | "fit_failed" | "error";
  peak_date: string | null;
  peak_value: number | null;
  half_life_weeks: number | null;
  half_life_days: number | null;
  r_squared: number | null;
  confidence: "high" | "medium" | "low" | null;
  decay_series_length: number | null;
  vs_report_claim: "within_range" | "shorter" | "longer" | null;
  methodology_note: string;
  report_claim: string;
  warning?: string;
  error_message?: string;
  drop_key: string;
  label: string;
};

export type QueryResponse = {
  question: string;
  question_type: QuestionType;
  answer: string;
  claims: Claim[];
  chunks: Chunk[];
  out_of_scope: boolean;
  kpi_result?: KpiResult | null;
  trend_results?: TrendResult[] | null;
};

export async function queryFilings(question: string): Promise<QueryResponse> {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  const response = await fetch(`${baseUrl}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });

  if (!response.ok) {
    throw new Error(
      `/query request failed: ${response.status} ${response.statusText}`
    );
  }

  return response.json() as Promise<QueryResponse>;
}
