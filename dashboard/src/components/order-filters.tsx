"use client";

type FilterProps = {
  source: string;
  status: string;
  onSourceChange: (v: string) => void;
  onStatusChange: (v: string) => void;
};

export function OrderFilters({
  source,
  status,
  onSourceChange,
  onStatusChange,
}: FilterProps) {
  return (
    <div className="flex gap-4 mb-6">
      <select
        value={source}
        onChange={(e) => onSourceChange(e.target.value)}
        className="border border-gray-300 rounded-md px-3 py-2 text-sm bg-white"
      >
        <option value="">Alle bronnen</option>
        <option value="semso_edi">Semso/EDI</option>
        <option value="manual">Handmatig</option>
      </select>
      <select
        value={status}
        onChange={(e) => onStatusChange(e.target.value)}
        className="border border-gray-300 rounded-md px-3 py-2 text-sm bg-white"
      >
        <option value="">Alle statussen</option>
        <option value="12">Open</option>
        <option value="20">Gedeeltelijk</option>
        <option value="21">Volledig</option>
      </select>
    </div>
  );
}
