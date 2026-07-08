"use client";

import { useState, type FormEvent } from "react";
import { queryFilings, type Chunk, type QueryResponse } from "@/lib/api";
import TierBadge from "@/components/TierBadge";
import KpiStatCard from "@/components/KpiStatCard";
import TrendDropCard from "@/components/TrendDropCard";

function findChunk(chunks: Chunk[], id: number): Chunk | undefined {
  return chunks.find((chunk) => chunk.id === id);
}

const FISCAL_YEAR_UNSPECIFIED = "Fiscal year not specified";

// Deliberate: an explicit null and a missing key both mean "no fiscal year
// given" to the user, so both fall through to the same nullish-coalescing branch.
function formatFiscalYear(fiscalYear: string | null | undefined): string {
  return fiscalYear ?? FISCAL_YEAR_UNSPECIFIED;
}

function nonRagSourceLabel(questionType: QueryResponse["question_type"]): string {
  if (questionType === "XBRL_KPI") {
    return "No filing chunk — sourced from the XBRL KPI tool (EDGAR companyfacts).";
  }
  if (questionType === "TREND_QUERY") {
    return "No filing chunk — sourced from the Google Trends decay tool.";
  }
  return "No filing chunk — this is a model-derived inference, not a direct filing citation.";
}

export default function Home() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<QueryResponse | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    try {
      const result = await queryFilings(question);
      setResponse(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col flex-1 items-center bg-zinc-50 font-sans dark:bg-black">
      <main className="flex flex-1 w-full max-w-3xl flex-col gap-6 py-16 px-8">
        <h1 className="text-2xl font-semibold text-black dark:text-zinc-50">
          Levi&apos;s RAG Copilot
        </h1>
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            type="text"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            disabled={loading}
            placeholder="Ask a question about Levi's SEC filings..."
            className="flex-1 rounded-md border border-zinc-300 bg-white px-4 py-2 text-black disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
          />
          <button
            type="submit"
            disabled={loading}
            className="rounded-md bg-black px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-black"
          >
            Ask
          </button>
        </form>

        {loading && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Loading...
          </p>
        )}

        {error && (
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        )}

        {response && (
          <div className="flex flex-col gap-2">
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              question_type: {response.question_type}
            </p>
            <p className="text-black dark:text-zinc-50">{response.answer}</p>

            {/* T6.5 routing decision: XBRL_KPI and TREND_QUERY get the
                structured T6.2/T6.3 displays instead of the generic claims
                list — their claim_text is a near-duplicate of the structured
                data (XBRL) or strictly less informative (trend's
                "insufficient_data" claim_text vs. TrendDropCard's message),
                so showing both would be redundant. The tier badge is kept
                (paired per-card) since it answers a different question than
                confidence does: tier is "what kind of evidence is this"
                (filing-verified vs. third-party benchmark vs. model
                inference), confidence is "how reliable is this specific
                number" — not redundant with each other. */}
            {response.question_type === "XBRL_KPI" && response.kpi_result && (
              <div className="flex flex-col gap-1">
                <KpiStatCard result={response.kpi_result} />
                {response.claims[0] && (
                  <TierBadge tier={response.claims[0].tier} />
                )}
              </div>
            )}

            {response.question_type === "TREND_QUERY" &&
              response.trend_results && (
                <div className="flex flex-col gap-2">
                  {response.trend_results.map((trendResult, index) => (
                    <div
                      key={trendResult.drop_key}
                      className="flex flex-col gap-1"
                    >
                      <TrendDropCard result={trendResult} />
                      {response.claims[index] && (
                        <TierBadge tier={response.claims[index].tier} />
                      )}
                    </div>
                  ))}
                </div>
              )}

            {response.question_type !== "XBRL_KPI" &&
              response.question_type !== "TREND_QUERY" &&
              response.claims.length > 0 && (
              <ul className="flex flex-col gap-2">
                {response.claims.map((claim, index) => {
                  const chunkId = claim.supporting_chunk_id;
                  const isRagClaim = chunkId >= 0;
                  const matchedChunk = isRagClaim
                    ? findChunk(response.chunks, chunkId)
                    : undefined;

                  return (
                    <li
                      key={index}
                      className="flex flex-col gap-1 rounded-md border border-zinc-200 p-3 dark:border-zinc-800"
                    >
                      <TierBadge tier={claim.tier} />
                      <p className="text-sm text-black dark:text-zinc-50">
                        {claim.claim_text}
                      </p>
                      <p className="text-xs text-zinc-500 dark:text-zinc-400">
                        Fiscal year: {formatFiscalYear(claim.fiscal_year)}
                      </p>

                      {isRagClaim && matchedChunk && (
                        <details className="text-xs text-zinc-600 dark:text-zinc-400">
                          <summary className="cursor-pointer">
                            Chunk #{chunkId}
                          </summary>
                          <ul className="mt-1 pl-4">
                            <li>Source: {matchedChunk.source}</li>
                            <li>Section: {matchedChunk.section}</li>
                            <li>
                              Fiscal year:{" "}
                              {formatFiscalYear(matchedChunk.fiscal_year)}
                            </li>
                          </ul>
                        </details>
                      )}

                      {isRagClaim && !matchedChunk && (
                        <p className="text-xs text-red-600 dark:text-red-400">
                          Chunk #{chunkId} referenced but not found in the
                          returned chunks — data inconsistency.
                        </p>
                      )}

                      {!isRagClaim && (
                        <p className="text-xs italic text-zinc-500 dark:text-zinc-400">
                          {nonRagSourceLabel(response.question_type)}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
