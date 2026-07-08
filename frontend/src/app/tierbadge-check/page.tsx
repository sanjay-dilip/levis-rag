import TierBadge from "@/components/TierBadge";
import type { Tier } from "@/lib/api";

const SAMPLE_TIERS: Tier[] = [
  "Verified-from-filing",
  "Management-qualitative-statement",
  "Third-party-benchmark",
  "Model-inference",
];

export default function TierBadgeCheck() {
  return (
    <div className="flex flex-col gap-2 p-8">
      {SAMPLE_TIERS.map((tier) => (
        <TierBadge key={tier} tier={tier} />
      ))}
    </div>
  );
}
