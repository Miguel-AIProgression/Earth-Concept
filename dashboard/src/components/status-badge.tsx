const STATUS_STYLES: Record<number, { label: string; className: string }> = {
  12: { label: "Open", className: "bg-yellow-100 text-yellow-800" },
  20: { label: "Gedeeltelijk", className: "bg-blue-100 text-blue-800" },
  21: { label: "Volledig", className: "bg-green-100 text-green-800" },
};

export function StatusBadge({ status }: { status: number }) {
  const style = STATUS_STYLES[status] || {
    label: `Status ${status}`,
    className: "bg-gray-100 text-gray-800",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${style.className}`}
    >
      {style.label}
    </span>
  );
}
