export type Tier =
  | "Verified-from-filing"
  | "Management-qualitative-statement"
  | "Third-party-benchmark"
  | "Model-inference";

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

export type QueryResponse = {
  question: string;
  question_type: QuestionType;
  answer: string;
  claims: Claim[];
  chunks: Chunk[];
  out_of_scope: boolean;
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
