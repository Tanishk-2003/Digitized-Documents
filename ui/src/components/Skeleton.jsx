/** Skeleton — shimmering placeholder shown while data loads, instead of a
 * bare spinner, so the page's eventual layout is visible immediately. */
export function Skeleton({ width = "100%", height = 14, radius = 6, style }) {
  return (
    <span
      className="skeleton"
      style={{ display: "inline-block", width, height, borderRadius: radius, ...style }}
    />
  );
}

/** A skeleton shaped like a row of the card-list pages (Review Queue). */
export function SkeletonCard() {
  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <div style={{ flex: 1 }}>
          <Skeleton width="40%" height={16} style={{ marginBottom: 8 }} />
          <Skeleton width="60%" height={12} />
        </div>
        <Skeleton width={84} height={34} radius={8} />
      </div>
    </div>
  );
}

/** A skeleton shaped like a data table (Documents, Final Output). */
export function SkeletonTable({ rows = 5, cols = 6 }) {
  return (
    <div className="card">
      <div className="table-scroll">
        <table>
          <tbody>
            {Array.from({ length: rows }).map((_, r) => (
              <tr key={r}>
                {Array.from({ length: cols }).map((__, c) => (
                  <td key={c}>
                    <Skeleton width={c === 0 ? "60%" : "80%"} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
