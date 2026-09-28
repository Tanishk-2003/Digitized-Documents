import { useState, useEffect, useMemo } from "react";
import { listFinalOutput, exportAllFinalOutput } from "../api";
import Icon from "../components/Icon";
import { SkeletonTable } from "../components/Skeleton";
import { useToast } from "../components/Toast";

/**
 * ApprovedDataPage — UI-UX-Implementation.md Phase A.5 (was FinalOutputPage,
 * "Final Output"). Same uniform 12-column Stock & Sale table (P14/P16),
 * built from every persisted document regardless of its original layout —
 * renamed because "Approved Data" is what this table actually represents
 * from a business standpoint (the output of the review/approve workflow),
 * not an engineering-stage label. Sortable by any column, filterable by
 * distributor/product/file name, with a one-click Excel export of
 * everything currently shown.
 */

const COLUMNS = [
  { key: "id", label: "ID", numeric: true },
  { key: "stockist_distributor_name", label: "Distributor" },
  { key: "address", label: "Address" },
  { key: "product_name", label: "Product" },
  { key: "opening_qty", label: "Opening Qty", numeric: true },
  { key: "closing_qty", label: "Closing Qty", numeric: true },
  { key: "dump_qty", label: "Dump Qty", numeric: true },
  { key: "scan_date", label: "Scan Date" },
  { key: "file_name", label: "File" },
  { key: "scan_by", label: "Scanned By" },
  { key: "update_by", label: "Updated By" },
  { key: "updated_on", label: "Updated On" },
];

const SEARCH_KEYS = ["stockist_distributor_name", "product_name", "file_name", "address"];

function formatCell(row, col) {
  const val = row[col.key];
  if (val == null) return "—";
  if (col.key === "updated_on") return new Date(val).toLocaleString();
  if (col.numeric && typeof val === "number") return val.toLocaleString();
  return String(val);
}

function compareValues(a, b, numeric) {
  if (a == null && b == null) return 0;
  if (a == null) return 1; // nulls sort last regardless of direction
  if (b == null) return -1;
  if (numeric) return a - b;
  return String(a).localeCompare(String(b));
}

export default function ApprovedDataPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState("id");
  const [sortDir, setSortDir] = useState("desc");
  const [exporting, setExporting] = useState(false);
  const showToast = useToast();

  useEffect(() => {
    listFinalOutput()
      .then(setRows)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const toggleSort = (key) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const visibleRows = useMemo(() => {
    const col = COLUMNS.find((c) => c.key === sortKey);
    const needle = search.trim().toLowerCase();

    const filtered = needle
      ? rows.filter((r) => SEARCH_KEYS.some((k) => String(r[k] ?? "").toLowerCase().includes(needle)))
      : rows;

    const sorted = [...filtered].sort((a, b) => {
      const cmp = compareValues(a[sortKey], b[sortKey], col?.numeric);
      return sortDir === "asc" ? cmp : -cmp;
    });

    return sorted;
  }, [rows, search, sortKey, sortDir]);

  const handleExport = async () => {
    setExporting(true);
    try {
      const blob = await exportAllFinalOutput();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "approved_data.xlsx";
      a.click();
      URL.revokeObjectURL(url);
      showToast(`Exported ${rows.length} row${rows.length === 1 ? "" : "s"}`);
    } catch (e) {
      showToast(`Export failed: ${e.message}`, { type: "error" });
    } finally {
      setExporting(false);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="page-title" style={{ marginBottom: 0 }}>Approved Data</h2>
        <div className="flex items-center gap-2">
          <div style={{ position: "relative" }}>
            <Icon name="search" size={14} style={{ position: "absolute", left: 10, top: 10, color: "var(--muted-light)" }} />
            <input
              type="text"
              placeholder="Search distributor, product, file…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ width: 260, paddingLeft: 30 }}
            />
          </div>
          <button className="btn btn-primary btn-sm" onClick={handleExport} disabled={exporting || rows.length === 0}>
            {exporting ? <span className="spinner" /> : <Icon name="download" size={13} />}
            Export All
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error"><Icon name="alertTriangle" size={16} />{error}</div>}

      {loading ? (
        <SkeletonTable rows={6} cols={12} />
      ) : rows.length === 0 ? (
        <div className="empty">
          <Icon name="grid" size={36} />
          <p>No approved data yet. Statements land here once review is complete.</p>
        </div>
      ) : visibleRows.length === 0 ? (
        <div className="empty">
          <Icon name="search" size={36} />
          <p>No rows match "{search}".</p>
        </div>
      ) : (
        <div className="card">
          <div className="text-sm text-muted mb-2">
            {visibleRows.length} of {rows.length} row{rows.length === 1 ? "" : "s"}
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {COLUMNS.map((col) => (
                    <th
                      key={col.key}
                      onClick={() => toggleSort(col.key)}
                      style={{ cursor: "pointer", userSelect: "none" }}
                      title="Click to sort"
                    >
                      {col.label}
                      {sortKey === col.key && (sortDir === "asc" ? " ▲" : " ▼")}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => (
                  <tr key={row.id}>
                    {COLUMNS.map((col) => (
                      <td
                        key={col.key}
                        className={col.key === "address" || col.key === "product_name" ? "truncate" : ""}
                        title={col.key === "address" || col.key === "product_name" ? formatCell(row, col) : undefined}
                      >
                        {formatCell(row, col)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
