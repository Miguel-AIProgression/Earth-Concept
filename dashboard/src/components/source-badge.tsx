export function SourceBadge({ source }: { source: string }) {
  const isAuto = source === "semso_edi";
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
        isAuto
          ? "bg-purple-100 text-purple-800"
          : "bg-orange-100 text-orange-800"
      }`}
    >
      {isAuto ? "Semso/EDI" : "Handmatig"}
    </span>
  );
}
