import type { Tier } from "@/lib/api";

const TIER_STYLES: Record<Tier, string> = {
  "Verified-from-filing":
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
  "Management-qualitative-statement":
    "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  "Third-party-benchmark":
    "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  "Model-inference":
    "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  "Insufficient-data":
    "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
};

export default function TierBadge({ tier }: { tier: Tier }) {
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${TIER_STYLES[tier]}`}
    >
      {tier}
    </span>
  );
}
