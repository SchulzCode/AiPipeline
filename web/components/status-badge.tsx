const terminalGood = new Set(["DONE"]);
const terminalBad = new Set(["FAILED", "BLOCKED", "CANCELLED"]);

export function StatusBadge({ status }: { status: string }) {
  const tone = terminalGood.has(status)
    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
    : terminalBad.has(status)
      ? "border-rose-500/40 bg-rose-500/10 text-rose-300"
      : "border-blue-400/30 bg-blue-400/10 text-blue-200";
  return <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${tone}`}>{status}</span>;
}
